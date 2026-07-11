"""Search classified ad sections of car forums and listing sites.

Targets actual classified sub-domains/sections (e.g. ads.ferrarichat.com)
rather than main discussion threads, plus major listing sites filtered for
problem-car keywords.  Scans the last 3 months for cars being sold with
mechanical issues, transmission problems, or owners dumping cars cheap.

These are prime buying opportunities — private sellers on forums price
lower than dealers and often disclose problems honestly.

Usage:
    python -m taormina_tools.buying.forum_search
    python -m taormina_tools.buying.forum_search --models "F430" "Gallardo" "911"
    python -m taormina_tools.buying.forum_search --max-queries 50
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


CLASSIFIED_SITES: list[dict[str, str]] = [
    # Forum classified subdomains/domains (Serper needs plain domains, no paths)
    {"name": "FerrariChat Classifieds", "site": "ads.ferrarichat.com", "focus": "ferrari"},
    {"name": "Rennlist", "site": "rennlist.com", "focus": "porsche"},
    {"name": "Lamborghini Talk", "site": "lamborghini-talk.com", "focus": "lamborghini"},
    {"name": "6SpeedOnline", "site": "6speedonline.com", "focus": "general"},
    {"name": "McLaren Life", "site": "mclarenlife.com", "focus": "mclaren"},
    # Listing sites — search with problem keywords
    {"name": "AutoTrader", "site": "autotrader.com", "focus": "general", "problem_search": True},
    {"name": "CarGurus", "site": "cargurus.com", "focus": "general", "problem_search": True},
]

REJECT_URL_PATTERNS: list[str] = [
    "/gassing/",
    "/forum/threads/",
    "/tags/",
    "/topic.asp",
    "/members/",
    "/profile/",
    "/search?",
    "/about/",
    "/news/",
    "/reviews/",
]

MODELS: list[dict[str, str | list[str]]] = [
    {"name": "Ferrari F355", "make": "ferrari", "keywords": ["F355", "355"]},
    {"name": "Ferrari 360", "make": "ferrari", "keywords": ["360", "360 modena", "360 spider"]},
    {"name": "Ferrari F430", "make": "ferrari", "keywords": ["F430", "430"]},
    {"name": "Ferrari 575M", "make": "ferrari", "keywords": ["575M", "575"]},
    {"name": "Ferrari 599", "make": "ferrari", "keywords": ["599", "599 GTB"]},
    {"name": "Ferrari 612", "make": "ferrari", "keywords": ["612", "612 Scaglietti"]},
    {"name": "Ferrari 458", "make": "ferrari", "keywords": ["458"]},
    {"name": "Ferrari 488", "make": "ferrari", "keywords": ["488"]},
    {"name": "Ferrari California", "make": "ferrari", "keywords": ["California"]},
    {"name": "Lamborghini Gallardo", "make": "lamborghini", "keywords": ["Gallardo"]},
    {"name": "Lamborghini Murcielago", "make": "lamborghini", "keywords": ["Murcielago"]},
    {"name": "Lamborghini Diablo", "make": "lamborghini", "keywords": ["Diablo"]},
    {"name": "Lamborghini Countach", "make": "lamborghini", "keywords": ["Countach"]},
    {"name": "Porsche 911 GT3", "make": "porsche", "keywords": ["GT3", "911 GT3"]},
    {"name": "Porsche 911 Turbo", "make": "porsche", "keywords": ["911 Turbo"]},
    {"name": "Porsche 991", "make": "porsche", "keywords": ["991", "911 Carrera"]},
    {"name": "Porsche 992", "make": "porsche", "keywords": ["992"]},
    {"name": "Porsche Cayman GT4", "make": "porsche", "keywords": ["GT4", "Cayman GT4"]},
    {"name": "McLaren 570S", "make": "mclaren", "keywords": ["570S", "570"]},
    {"name": "McLaren 720S", "make": "mclaren", "keywords": ["720S", "720"]},
    {"name": "McLaren 650S", "make": "mclaren", "keywords": ["650S"]},
    {"name": "Aston Martin Vantage", "make": "aston martin", "keywords": ["Vantage", "V8 Vantage"]},
    {"name": "BMW M3", "make": "bmw", "keywords": ["M3"]},
    {"name": "BMW M4", "make": "bmw", "keywords": ["M4"]},
    {"name": "Maserati GranTurismo", "make": "maserati", "keywords": ["GranTurismo"]},
]

# Default focus set for the weekly report — Ferrari 355, F430, 575M, 599.
# MODELS above stays the full catalog for ad-hoc `--models` searches.
FOCUS_MODELS: list[str] = [
    "Ferrari F355",
    "Ferrari F430",
    "Ferrari 575M",
    "Ferrari 599",
]

PROBLEM_KEYWORDS: list[str] = [
    "needs work",
    "needs repair",
    "transmission issue",
    "transmission problem",
    "engine issue",
    "engine problem",
    "not running",
    "doesn't run",
    "won't start",
    "overheating",
    "oil leak",
    "check engine",
    "limp mode",
    "as-is",
    "as is",
    "no longer want to fix",
    "too expensive to fix",
    "don't want to fix",
    "project",
    "mechanic special",
    "F1 pump",
    "F1 clutch",
    "e-gear",
    "clutch worn",
    "needs clutch",
    "blown",
    "seized",
    "misfire",
]

SALE_KEYWORDS: list[str] = [
    "for sale",
    "selling",
    "FS:",
    "WTS",
    "must sell",
    "price drop",
    "reduced",
    "OBO",
    "or best offer",
    "make offer",
    "taking offers",
]


@dataclass
class ForumListing:
    forum: str
    model: str
    title: str
    url: str
    snippet: str
    problem_matched: str
    sale_signal: str
    has_price: bool = False


def _get_relevant_sites(make: str) -> list[dict[str, str]]:
    """Return classified sites relevant to a given make, plus general sites."""
    return [s for s in CLASSIFIED_SITES if s["focus"] == make or s["focus"] == "general"]


def _build_queries(models: list[str] | None = None) -> list[tuple[str, str, str]]:
    """Returns (query, model_name, site_name) tuples.

    Uses OR-combined keywords to minimize query count.  1 query per model
    per site:
    - Forum classified sites: sale keywords
    - Listing sites (problem_search=True): problem keywords
    Interleaved round-robin so --max-queries spreads budget evenly.
    """
    if models:
        models_to_check = [m for m in MODELS if m["name"] in models or
                           any(kw.lower() in name.lower() for name in models for kw in m["keywords"])]
    else:
        models_to_check = MODELS

    per_model: list[list[tuple[str, str, str]]] = []

    for model_cfg in models_to_check:
        model_name = model_cfg["name"]
        make = model_cfg["make"]
        primary_kw = model_cfg["keywords"][0]
        relevant_sites = _get_relevant_sites(make)

        model_queries: list[tuple[str, str, str]] = []
        for site in relevant_sites:
            site_domain = site["site"]
            if site.get("problem_search"):
                # Listing sites — search make + model + one problem keyword
                query = f'site:{site_domain} {make} {primary_kw} salvage OR "needs work"'
            else:
                # Forum classified sections — just search the model (it's already a for-sale section)
                query = f'site:{site_domain} {primary_kw}'
            model_queries.append((query, model_name, site["name"]))

        per_model.append(model_queries)

    # Round-robin across models so budget is spread evenly
    queries: list[tuple[str, str, str]] = []
    max_depth = max((len(mq) for mq in per_model), default=0)
    for i in range(max_depth):
        for mq in per_model:
            if i < len(mq):
                queries.append(mq[i])

    return queries


def search_forums(
    models: list[str] | None = None,
    max_queries: int | None = None,
) -> list[ForumListing]:
    """Search classified sections and listing sites for cars being sold with problems."""
    queries = _build_queries(models)
    if max_queries:
        queries = queries[:max_queries]

    # 3-month recency window
    client = GoogleCSEClient(recency="qdr:m3")
    results: list[ForumListing] = []
    seen_urls: set[str] = set()

    with client:
        for query_str, model_name, site_name in queries:
            try:
                search_results = client.search(query_str, num=10)
            except Exception as e:
                print(f"  [error] {query_str}: {e}", file=sys.stderr)
                continue

            for r in search_results:
                if r.link in seen_urls:
                    continue

                # Reject non-listing URLs (discussion threads, profiles, etc.)
                if any(pattern in r.link for pattern in REJECT_URL_PATTERNS):
                    continue

                seen_urls.add(r.link)

                combined = f"{r.title.lower()} {r.snippet.lower()}"

                problem_matched = ""
                for kw in PROBLEM_KEYWORDS:
                    if kw.lower() in combined:
                        problem_matched = kw
                        break

                sale_signal = ""
                for kw in SALE_KEYWORDS:
                    if kw.lower() in combined:
                        sale_signal = kw
                        break

                if not problem_matched and not sale_signal:
                    continue

                has_price = bool(re.search(r'\$[\d,]+', f"{r.title} {r.snippet}"))

                results.append(ForumListing(
                    forum=site_name,
                    model=model_name,
                    title=r.title,
                    url=r.link,
                    snippet=r.snippet[:300],
                    problem_matched=problem_matched,
                    sale_signal=sale_signal,
                    has_price=has_price,
                ))

    # Results with prices rank higher; then problem+sale > problem-only > sale-only
    results.sort(
        key=lambda x: (
            bool(x.problem_matched and x.sale_signal),
            x.has_price,
            bool(x.problem_matched),
        ),
        reverse=True,
    )
    return results


def _write_csv(results: list[ForumListing], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    scraped_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    fieldnames = ["scraped_at", "forum", "model", "title", "url", "problem_matched", "sale_signal", "snippet", "contacted"]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            writer.writerow({
                "scraped_at": scraped_at,
                "forum": r.forum,
                "model": r.model,
                "title": r.title,
                "url": r.url,
                "problem_matched": r.problem_matched,
                "sale_signal": r.sale_signal,
                "snippet": r.snippet,
                "contacted": "",
            })


def run(*, models: list[str] | None, max_queries: int | None, output: Path) -> int:
    queries = _build_queries(models)
    if max_queries:
        queries = queries[:max_queries]

    n_models = len(models) if models else len(MODELS)
    print(f"Searching classifieds for problem cars (last 3 months)...")
    print(f"  {len(queries)} queries across {n_models} models, {len(CLASSIFIED_SITES)} classified sites")
    print(f"  Sites: {', '.join(s['name'] for s in CLASSIFIED_SITES)}")
    print(f"  (uses Serper API — each query = 1 credit)")

    results = search_forums(models, max_queries)

    _write_csv(results, output)

    with_problems = [r for r in results if r.problem_matched]
    with_sale = [r for r in results if r.sale_signal]
    both = [r for r in results if r.problem_matched and r.sale_signal]
    with_price = [r for r in results if r.has_price]

    print(f"\nDone: {len(results)} classified listings found, written to {output}.")
    print(f"  With problem keywords: {len(with_problems)}")
    print(f"  With sale signals: {len(with_sale)}")
    print(f"  Both (highest priority): {len(both)}")
    print(f"  With price detected: {len(with_price)}")
    if results:
        print(f"  Top hit: [{results[0].forum}] {results[0].title}")
    return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Search classifieds for problem cars being sold (last 3 months)")
    p.add_argument(
        "--models", nargs="+", default=FOCUS_MODELS,
        help=f"Models to search (default: focus set {', '.join(FOCUS_MODELS)})",
    )
    p.add_argument(
        "--max-queries", type=int, default=None,
        help="Cap total queries (default: no cap)",
    )
    p.add_argument(
        "--output", type=Path,
        default=Path("out") / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}-forums.csv",
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
