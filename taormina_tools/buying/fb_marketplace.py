"""Score Facebook Marketplace listings as deals against BaT + Cars & Bids.

Finds Facebook Marketplace listings for the focus models via Serper, parses
price / mileage / year out of the search title + snippet, and scores each one
against the *same* Bring a Trailer + Cars & Bids baseline (mileage + year
adjusted regression) used by the dealer Deal Finder in `price_compare`.

Unlike the dealer deal-finder (which gets structured data from MarketCheck),
Facebook listings only come to us as Google search snippets — so price and
mileage aren't always present, and Google indexes Marketplace inconsistently.
Expect a modest number of fully scored hits. Listings with unknown mileage
fall back to a flat-median discount, exactly as `price_compare` does when
miles == 0.

Usage:
    python -m taormina_tools.buying.fb_marketplace
    python -m taormina_tools.buying.fb_marketplace --models "F430" "599 GTB"
    python -m taormina_tools.buying.fb_marketplace --max-queries 12
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from ..google_search import GoogleCSEClient
from .price_compare import (
    FOCUS_MODELS,
    MODEL_CONFIG,
    MODEL_MILEAGE_EXPECTATIONS,
    MarketBaseline,
    _expected_price,
    _parse_miles_from_title,
    _parse_year_from_title,
    get_market_baselines,
)


# Snippet/title words that mean the car is NOT a clean-title car — used to knock
# down the expected price the same way price_compare does for salvage/rebuilt.
NON_CLEAN_TITLE_WORDS: list[str] = [
    "salvage", "rebuilt", "branded", "flood", "lemon", "theft recovery",
]

# A bare "$" amount only. The negative lookbehind rejects foreign currency
# codes that embed a dollar sign (HK$, CA$, AU$, NZ$, US$, S$, R$) so a
# HK$190,000 listing isn't mistaken for USD.
PRICE_RE = re.compile(r"(?<![A-Za-z])\$\s?([\d][\d,]{3,})")


@dataclass
class FBDeal:
    model: str
    year: int
    heading: str
    url: str
    snippet: str
    price: int
    miles: int
    market_median: int
    discount_pct: float
    adj_discount_pct: float
    score: float


def _model_tokens(model_key: str) -> list[str]:
    """Lowercase tokens that should appear in a listing to confirm the model.

    Combines the focus key (e.g. "F430 Spider") with the MarketCheck model
    string from MODEL_CONFIG (e.g. "f430") so both "f430" and "spider" count.
    """
    cfg = MODEL_CONFIG.get(model_key, {})
    raw = f"{model_key} {cfg.get('model', '')}".lower()
    return [t for t in re.split(r"\s+", raw) if t]


def _build_queries(models: list[str]) -> list[tuple[str, str]]:
    """Return (query, model_key) pairs — one Marketplace query per model.

    Targets `/marketplace/item` pages specifically: the bare `/marketplace`
    queries only return FB's localized category landing pages (no price or
    mileage), whereas item pages carry the real listing details in their
    snippet (e.g. "$95,500 Listed 34,501 miles").
    """
    queries: list[tuple[str, str]] = []
    for model_key in models:
        cfg = MODEL_CONFIG.get(model_key)
        if not cfg:
            continue
        make = cfg["make"]
        # Un-quoted term keeps Google fuzzy (more hits); we validate the model
        # actually appears in each result below.
        queries.append((
            f"site:facebook.com/marketplace/item {make} {model_key}",
            model_key,
        ))
    return queries


def _parse_price(text: str) -> int:
    """First plausible exotic-car price ($) in the text, else 0."""
    for m in PRICE_RE.finditer(text):
        val = int(m.group(1).replace(",", ""))
        if 15000 <= val <= 900000:
            return val
    return 0


def _parse_miles_general(text: str) -> int:
    """Extract mileage from free-form FB text.

    Handles "45,000 miles", "45000 mi", "45k miles", and falls back to the
    BaT-style "45k-Mile" parser. Requires an explicit mileage unit so model
    years (e.g. 2006) are never mistaken for mileage.
    """
    # "45k miles" / "45K mi"
    m = re.search(r"(\d{1,3})\s*[kK]\s*(?:miles|mile|mi)\b", text)
    if m:
        return int(m.group(1)) * 1000
    # "45,000 miles" / "45000 mi"
    m = re.search(r"([\d,]{3,})\s*(?:miles|mile|mi)\b", text, re.IGNORECASE)
    if m:
        return int(m.group(1).replace(",", ""))
    # BaT-style "45k-Mile" embedded in a shared title
    return _parse_miles_from_title(text)


def _mileage_adjustment(miles: int, avg_miles: int) -> float:
    """Same mileage-ratio score nudge price_compare.find_deals uses."""
    if miles <= 0:
        return 0.0
    ratio = miles / avg_miles
    if ratio > 1.5:
        return -10.0
    if ratio > 1.0:
        return -3.0 * (ratio - 1.0)
    if ratio < 0.5:
        return 5.0
    return 2.0 * (1.0 - ratio)


def find_fb_deals(
    models: list[str],
    baselines: dict[str, MarketBaseline],
    max_queries: int | None = None,
) -> list[FBDeal]:
    """Search Facebook Marketplace and score hits against BaT + C&B baselines."""
    scored_models = [m for m in models if m in baselines]
    queries = _build_queries(scored_models)
    if max_queries:
        queries = queries[:max_queries]

    # Past-year window: Google indexes FB Marketplace item pages with lag, so a
    # tight 1-month window returns almost nothing. Sold listings get delisted,
    # which keeps most surviving results live.
    client = GoogleCSEClient(recency="qdr:y")
    deals: list[FBDeal] = []
    seen_urls: set[str] = set()

    with client:
        for query_str, model_key in queries:
            try:
                results = client.search(query_str, num=10)
            except Exception as e:
                print(f"  [error] {query_str}: {e}", file=sys.stderr)
                continue

            baseline = baselines[model_key]
            avg_miles, max_miles = MODEL_MILEAGE_EXPECTATIONS.get(model_key, (30000, 60000))
            tokens = _model_tokens(model_key)

            for r in results:
                if "/marketplace/item" not in r.link:
                    continue
                if r.link in seen_urls:
                    continue

                combined = f"{r.title} {r.snippet}"
                combined_lower = combined.lower()

                # Confirm it's the right car: make + at least one model token.
                if "ferrari" not in combined_lower:
                    continue
                if not any(tok in combined_lower for tok in tokens):
                    continue

                price = _parse_price(combined)
                if not price:
                    continue  # can't score a listing without a (USD) price

                # Guard against FB's aggregated snippets, where the price can
                # belong to a different (cheap, unrelated) item than the Ferrari
                # mention. A real running car of these models never sells this
                # far below market, so treat it as a mismatch, not a deal.
                if price < baseline.median_sold * 0.35:
                    continue

                seen_urls.add(r.link)

                miles = _parse_miles_general(combined)
                if miles and miles > max_miles:
                    continue  # too many miles for this model — not a deal

                year = _parse_year_from_title(r.title) or _parse_year_from_title(r.snippet)
                clean_title = not any(w in combined_lower for w in NON_CLEAN_TITLE_WORDS)

                discount = (baseline.median_sold - price) / baseline.median_sold * 100
                ep = _expected_price(baseline, miles, year, clean_title)
                adj_discount = (ep - price) / ep * 100 if ep else discount

                # Only surface actual deals (at or below market). Same spirit as
                # the dealer deal-finder's below-median price filter.
                if discount < 0 and adj_discount < 0:
                    continue

                mileage_adj = _mileage_adjustment(miles, avg_miles)
                score = adj_discount + mileage_adj

                deals.append(FBDeal(
                    model=model_key,
                    year=year,
                    heading=r.title,
                    url=r.link,
                    snippet=r.snippet[:300],
                    price=price,
                    miles=miles,
                    market_median=baseline.median_sold,
                    discount_pct=round(discount, 1),
                    adj_discount_pct=round(adj_discount, 1),
                    score=round(score, 1),
                ))

    deals.sort(key=lambda d: d.score, reverse=True)
    return deals


def _write_csv(deals: list[FBDeal], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    scraped_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    fieldnames = [
        "scraped_at", "score", "model", "year", "heading", "price",
        "market_median", "discount_pct", "adj_discount_pct",
        "miles", "miles_vs_avg", "source", "url", "snippet", "contacted",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for d in deals:
            avg_miles = MODEL_MILEAGE_EXPECTATIONS.get(d.model, (30000, 60000))[0]
            miles_label = f"{d.miles / avg_miles:.1f}x avg" if d.miles > 0 else "unknown"
            writer.writerow({
                "scraped_at": scraped_at,
                "score": d.score,
                "model": d.model,
                "year": d.year or "",
                "heading": d.heading,
                "price": d.price,
                "market_median": d.market_median,
                "discount_pct": d.discount_pct,
                "adj_discount_pct": d.adj_discount_pct,
                "miles": d.miles or "",
                "miles_vs_avg": miles_label,
                "source": "Facebook Marketplace",
                "url": d.url,
                "snippet": d.snippet,
                "contacted": "",
            })


def run(*, models: list[str], max_queries: int | None, output: Path) -> int:
    print(f"Step 1: Building market baselines for {len(models)} models (BaT + Cars & Bids)...")
    baselines = get_market_baselines(models)
    scored = [m for m in models if m in baselines]
    print(f"  Got baselines for {len(baselines)} models: {', '.join(scored) or 'none'}")
    missing = [m for m in models if m not in baselines]
    if missing:
        print(f"  Skipping (insufficient sold data): {', '.join(missing)}")
    if not baselines:
        print("No baselines available — cannot score Facebook listings.")
        _write_csv([], output)
        return 1

    print(f"\nStep 2: Searching Facebook Marketplace (Serper — 1 credit/query)...")
    print(f"  Note: Google indexes FB Marketplace inconsistently; mileage is often")
    print(f"  missing from snippets, so expect a modest number of fully scored hits.")

    deals = find_fb_deals(models, baselines, max_queries)
    _write_csv(deals, output)

    with_miles = sum(1 for d in deals if d.miles > 0)
    print(f"\nDone: {len(deals)} Facebook Marketplace deals written to {output}.")
    print(f"  {with_miles} had mileage parsed (mileage-adjusted); rest use flat median.")
    if deals:
        top = deals[0]
        print(
            f"Best FB deal: {top.year or '?'} {top.model} — ${top.price:,} vs "
            f"${top.market_median:,} median ({top.adj_discount_pct}% adj. below market)"
        )
    return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Score Facebook Marketplace listings as deals vs BaT + Cars & Bids"
    )
    p.add_argument(
        "--models", nargs="+", default=FOCUS_MODELS,
        help=f"Models to search (default: focus set {', '.join(FOCUS_MODELS)})",
    )
    p.add_argument(
        "--max-queries", type=int, default=None,
        help="Cap total Serper queries (default: one per model)",
    )
    p.add_argument(
        "--output", type=Path,
        default=Path("out") / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}-fbmarket.csv",
        help="Output CSV path (default: out/YYYY-MM-DD-fbmarket.csv)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = _parse_args(argv)
    try:
        return run(models=args.models, max_queries=args.max_queries, output=args.output)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
