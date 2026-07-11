"""Search for exotic "project cars" on eBay Motors, FB Marketplace, and Craigslist.

Targets private sellers dumping broken exotics cheap — keywords like
"needs work," "as-is," "mechanic special," "not running," "project."
Also searches for F1/e-gear specific keywords to find manual-swap candidates.

Usage:
    python -m taormina_tools.buying.project_car_search
    python -m taormina_tools.buying.project_car_search --models "F430" "Gallardo" "360"
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from ..google_search import GoogleCSEClient


MODELS: list[str] = [
    # Ferrari — manual swap targets
    "Ferrari 360",
    "Ferrari F430",
    "Ferrari 575M",
    "Ferrari 599",
    "Ferrari 612",
    "Ferrari F355",
    "Ferrari 550",
    # Ferrari — modern
    "Ferrari 458",
    "Ferrari 488",
    "Ferrari California",
    # Lamborghini — manual swap targets
    "Lamborghini Gallardo",
    "Lamborghini Murcielago",
    # Lamborghini — classic
    "Lamborghini Diablo",
    "Lamborghini Countach",
    # Lamborghini — modern
    "Lamborghini Urus",
    # Porsche
    "Porsche 911 GT3",
    "Porsche 911 Turbo",
    "Porsche 991",
    "Porsche 992",
    "Porsche Cayman GT4",
    # McLaren
    "McLaren 570S",
    "McLaren 720S",
    "McLaren 650S",
    "McLaren 12C",
    # Others
    "Aston Martin Vantage",
    "Maserati GranTurismo",
]

# Default focus set for the weekly report — Ferrari 355, F430, 575M, 599.
# The "Ferrari <model>" strings also surface Spider variants via substring match.
# MODELS above stays the full catalog for ad-hoc `--models` searches.
FOCUS_MODELS: list[str] = [
    "Ferrari F355",
    "Ferrari F430",
    "Ferrari 575M",
    "Ferrari 599",
]

# Sites where private sellers list broken cars
LISTING_SITES: list[str] = [
    "ebay.com",
    "facebook.com/marketplace",
    "craigslist.org",
]

# Keywords that signal a car needs work (= buying opportunity)
PROJECT_KEYWORDS: list[str] = [
    "needs work",
    "as-is",
    "as is",
    "mechanic special",
    "not running",
    "non running",
    "project car",
    "project",
    "needs repair",
    "does not run",
    "no start",
    "blown engine",
    "bad transmission",
    "for parts",
    "parts car",
    "salvage title",
    "rebuilt title",
]

# Keywords specific to manual-swap candidates
TRANSMISSION_KEYWORDS: list[str] = [
    "F1 transmission",
    "F1 gearbox",
    "e-gear",
    "egear",
    "e gear",
    "F1 pump",
    "F1 clutch",
    "cambiocorsa",
    "single clutch",
    "automated manual",
    "paddle shift",
    "selespeed",
]


@dataclass
class ProjectListing:
    model: str
    title: str
    url: str
    snippet: str
    keyword_matched: str
    category: str  # "project" or "manual_swap_candidate"
    site: str


def _build_queries(models: list[str] | None = None) -> list[tuple[str, str, str, str]]:
    """Returns (query, model, keyword, category) tuples.

    Uses OR-combined keywords to minimize query count. Per model:
    - 1 swap query (all transmission keywords combined)
    - 1 project query per listing site (all project keywords combined)
    - 1 eBay parts query
    = 5 queries per model instead of ~31. Interleaved for fair --max-queries.
    """
    models_to_check = models or MODELS
    project_or = " OR ".join(f'"{k}"' for k in PROJECT_KEYWORDS[:8])
    swap_or = " OR ".join(f'"{k}"' for k in TRANSMISSION_KEYWORDS[:6])
    per_model: list[list[tuple[str, str, str, str]]] = []

    for model in models_to_check:
        model_queries: list[tuple[str, str, str, str]] = []

        # One combined swap query — highest value
        model_queries.append((
            f'"{model}" ({swap_or}) for sale',
            model,
            "F1/e-gear keywords",
            "manual_swap_candidate",
        ))

        # One combined project query per listing site
        for site in LISTING_SITES:
            model_queries.append((
                f'site:{site} "{model}" ({project_or})',
                model,
                "project keywords",
                "project",
            ))

        # eBay parts/not-running
        model_queries.append((
            f'site:ebay.com "{model}" "parts only" OR "not running" OR "for parts"',
            model,
            "parts/not running",
            "project",
        ))

        per_model.append(model_queries)

    # Round-robin across models so budget is spread evenly
    queries: list[tuple[str, str, str, str]] = []
    max_depth = max((len(mq) for mq in per_model), default=0)
    for i in range(max_depth):
        for mq in per_model:
            if i < len(mq):
                queries.append(mq[i])

    return queries


def search_project_cars(
    models: list[str] | None = None,
    max_queries: int | None = None,
) -> list[ProjectListing]:
    """Search for project cars and manual-swap candidates."""
    queries = _build_queries(models)
    if max_queries:
        queries = queries[:max_queries]

    client = GoogleCSEClient(recency="qdr:m")
    results: list[ProjectListing] = []
    seen_urls: set[str] = set()

    with client:
        for query_str, model, keyword, category in queries:
            try:
                search_results = client.search(query_str, num=10)
            except Exception as e:
                print(f"  [error] {query_str}: {e}", file=sys.stderr)
                continue

            for r in search_results:
                if r.link in seen_urls:
                    continue
                seen_urls.add(r.link)

                site = "eBay"
                if "facebook.com/marketplace" in r.link:
                    site = "Facebook Marketplace"
                elif "facebook.com" in r.link:
                    continue  # group post, not a listing
                elif "craigslist" in r.link:
                    site = "Craigslist"
                elif "ebay" in r.link:
                    site = "eBay"
                else:
                    site = "Other"

                # Validate model name appears in the result
                model_lower = model.lower()
                combined_text = f"{r.title.lower()} {r.snippet.lower()}"
                model_parts = model.split()
                if not any(part.lower() in combined_text for part in model_parts):
                    continue

                results.append(ProjectListing(
                    model=model,
                    title=r.title,
                    url=r.link,
                    snippet=r.snippet[:300],
                    keyword_matched=keyword,
                    category=category,
                    site=site,
                ))

    def _score(r: ProjectListing) -> float:
        s = 0.0
        # Swap candidates are highest value
        if r.category == "manual_swap_candidate":
            s += 50
        # Actual listing sites beat random "Other" results
        if r.site in ("eBay", "Craigslist"):
            s += 20
        elif r.site == "Facebook Marketplace":
            s += 15
        # Stronger problem signals
        snippet_lower = r.snippet.lower()
        for strong in ("not running", "blown", "needs work", "mechanic special", "as-is", "as is"):
            if strong in snippet_lower:
                s += 10
                break
        # Price mentioned = real listing, not just a discussion
        if "$" in r.snippet or "obo" in snippet_lower or "asking" in snippet_lower:
            s += 10
        else:
            s -= 20  # no price = probably not a real listing
        return s

    results.sort(key=_score, reverse=True)
    return results


def _write_csv(results: list[ProjectListing], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    scraped_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    fieldnames = ["scraped_at", "category", "model", "site", "title", "url", "keyword_matched", "snippet", "contacted"]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            writer.writerow({
                "scraped_at": scraped_at,
                "category": r.category,
                "model": r.model,
                "site": r.site,
                "title": r.title,
                "url": r.url,
                "keyword_matched": r.keyword_matched,
                "snippet": r.snippet,
                "contacted": "",
            })


def run(*, models: list[str] | None, max_queries: int | None, top: int | None, output: Path) -> int:
    queries = _build_queries(models)
    if max_queries:
        queries = queries[:max_queries]

    n_models = len(models or MODELS)
    print(f"Searching for project cars & manual-swap candidates...")
    print(f"  {len(queries)} queries across {n_models} models")
    print(f"  Sites: eBay Motors, FB Marketplace, Craigslist + general web")
    print(f"  (uses Serper API — each query = 1 credit)")

    results = search_project_cars(models, max_queries)

    if top and len(results) > top:
        print(f"  Keeping top {top} of {len(results)} results (ranked by quality)")
        results = results[:top]

    _write_csv(results, output)

    swap_candidates = [r for r in results if r.category == "manual_swap_candidate"]
    projects = [r for r in results if r.category == "project"]

    print(f"\nDone: {len(results)} listings written to {output}.")
    print(f"  Manual-swap candidates: {len(swap_candidates)}")
    print(f"  Project/mechanic-special cars: {len(projects)}")
    if results:
        print(f"  Top hit: {results[0].title}")
    return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Search for project cars and manual-swap candidates")
    p.add_argument(
        "--models", nargs="+", default=FOCUS_MODELS,
        help=f"Models to search (default: focus set {', '.join(FOCUS_MODELS)})",
    )
    p.add_argument(
        "--max-queries", type=int, default=None,
        help="Cap total queries (default: no cap)",
    )
    p.add_argument(
        "--top", type=int, default=30,
        help="Keep only the top N results ranked by quality (default: 30, 0 = no limit)",
    )
    p.add_argument(
        "--output", type=Path,
        default=Path("out") / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}-projects.csv",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = _parse_args(argv)
    try:
        return run(models=args.models, max_queries=args.max_queries, top=args.top or None, output=args.output)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
