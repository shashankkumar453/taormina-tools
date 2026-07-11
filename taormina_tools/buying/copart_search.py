"""Copart & IAA salvage auction search for mechanically-damaged exotics.

Searches Copart and IAA via Google (Serper) for exotic cars listed with
mechanical damage, non-running status, or drivetrain issues. These are
insurance total-loss cars or dealer trade-ins with expensive problems —
exactly what we want for fix-and-flip or manual-swap projects.

Usage:
    python -m taormina_tools.buying.copart_search
    python -m taormina_tools.buying.copart_search --models "F430" "360 Modena" "Gallardo"
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from ..google_search import GoogleCSEClient


TARGET_MODELS: dict[str, dict] = {
    # Ferrari manual-swap targets
    "Ferrari 360": {"make": "ferrari", "keywords": ["360 modena", "360 spider", "360"]},
    "Ferrari F430": {"make": "ferrari", "keywords": ["f430", "430"]},
    "Ferrari 575M": {"make": "ferrari", "keywords": ["575m", "575 maranello"]},
    "Ferrari 599": {"make": "ferrari", "keywords": ["599 gtb", "599"]},
    "Ferrari 612": {"make": "ferrari", "keywords": ["612 scaglietti", "612"]},
    "Ferrari F355": {"make": "ferrari", "keywords": ["f355", "355"]},
    "Ferrari 550": {"make": "ferrari", "keywords": ["550 maranello", "550"]},
    # Ferrari modern
    "Ferrari 458": {"make": "ferrari", "keywords": ["458"]},
    "Ferrari 488": {"make": "ferrari", "keywords": ["488"]},
    "Ferrari California": {"make": "ferrari", "keywords": ["california"]},
    # Lamborghini manual-swap targets
    "Lamborghini Gallardo": {"make": "lamborghini", "keywords": ["gallardo"]},
    "Lamborghini Murcielago": {"make": "lamborghini", "keywords": ["murcielago"]},
    # Lamborghini — classic
    "Lamborghini Diablo": {"make": "lamborghini", "keywords": ["diablo"]},
    "Lamborghini Countach": {"make": "lamborghini", "keywords": ["countach"]},
    # Lamborghini modern
    "Lamborghini Urus": {"make": "lamborghini", "keywords": ["urus"]},
    # Porsche
    "Porsche 911 GT3": {"make": "porsche", "keywords": ["911 gt3", "gt3"]},
    "Porsche 911 Turbo": {"make": "porsche", "keywords": ["911 turbo"]},
    "Porsche 911": {"make": "porsche", "keywords": ["911"]},
    "Porsche 991": {"make": "porsche", "keywords": ["991", "911 carrera"]},
    "Porsche 992": {"make": "porsche", "keywords": ["992"]},
    "Porsche Cayman GT4": {"make": "porsche", "keywords": ["cayman gt4", "gt4"]},
    # McLaren
    "McLaren 570S": {"make": "mclaren", "keywords": ["570s", "570"]},
    "McLaren 720S": {"make": "mclaren", "keywords": ["720s", "720"]},
    "McLaren 650S": {"make": "mclaren", "keywords": ["650s"]},
    "McLaren MP4-12C": {"make": "mclaren", "keywords": ["mp4-12c", "12c"]},
    # Others
    "Aston Martin V8 Vantage": {"make": "aston martin", "keywords": ["v8 vantage", "vantage"]},
    "Maserati GranTurismo": {"make": "maserati", "keywords": ["granturismo"]},
}

# Default focus set for the weekly report — Ferrari 355, F430, 575M, 599.
# Keywords on each TARGET_MODELS entry already cover Spider variants.
# TARGET_MODELS above stays the full catalog for ad-hoc `--models` searches.
FOCUS_MODELS: list[str] = [
    "Ferrari F355",
    "Ferrari F430",
    "Ferrari 575M",
    "Ferrari 599",
]

SALVAGE_SITES = [
    "copart.com",
    "iaai.com",
]

DAMAGE_KEYWORDS = [
    "mechanical",
    "engine",
    "transmission",
    "runs and drives",
    "non-runner",
    "not running",
]


@dataclass
class SalvageListing:
    source: str
    model: str
    title: str
    url: str
    snippet: str
    damage_type: str


def _build_queries(models: list[str] | None = None) -> list[tuple[str, str]]:
    """Build (query_string, model_name) pairs for Copart/IAA searches.

    Uses OR-combined keywords to minimize query count — one broad query
    and one damage-focused query per model per site (4 queries per model
    instead of 8). Interleaved across models for fair --max-queries.
    """
    models_to_check = models or list(TARGET_MODELS.keys())
    damage_or = " OR ".join(f'"{d}"' for d in DAMAGE_KEYWORDS)
    per_model: list[list[tuple[str, str]]] = []

    for model_name in models_to_check:
        cfg = TARGET_MODELS.get(model_name)
        if not cfg:
            for key, val in TARGET_MODELS.items():
                if model_name.lower() in key.lower() or any(model_name.lower() in kw for kw in val["keywords"]):
                    cfg = val
                    model_name = key
                    break
        if not cfg:
            continue

        model_queries: list[tuple[str, str]] = []
        primary_kw = cfg["keywords"][0]
        make = cfg["make"]
        for site in SALVAGE_SITES:
            # One damage-focused query (combines all damage keywords)
            model_queries.append((
                f'site:{site} "{make}" "{primary_kw}" ({damage_or})',
                model_name,
            ))
            # One broad query (catches listings without damage keywords in snippet)
            model_queries.append((
                f'site:{site} "{make}" "{primary_kw}"',
                model_name,
            ))
        per_model.append(model_queries)

    # Round-robin across models so budget is spread evenly
    queries: list[tuple[str, str]] = []
    max_depth = max((len(mq) for mq in per_model), default=0)
    for i in range(max_depth):
        for mq in per_model:
            if i < len(mq):
                queries.append(mq[i])

    return queries


def search_salvage(models: list[str] | None = None, max_queries: int | None = None) -> list[SalvageListing]:
    """Search Copart and IAA for exotic cars with mechanical damage."""
    queries = _build_queries(models)
    if max_queries:
        queries = queries[:max_queries]

    client = GoogleCSEClient(recency="qdr:m")
    results: list[SalvageListing] = []
    seen_urls: set[str] = set()

    with client:
        for query_str, model_name in queries:
            try:
                search_results = client.search(query_str, num=10)
            except Exception as e:
                print(f"  [error] {query_str}: {e}", file=sys.stderr)
                continue

            for r in search_results:
                if r.link in seen_urls:
                    continue
                seen_urls.add(r.link)

                snippet_lower = r.snippet.lower()
                title_lower = r.title.lower()
                combined = f"{title_lower} {snippet_lower}"

                # Validate the actual car matches what we searched for
                cfg = TARGET_MODELS.get(model_name)
                make_lower = cfg["make"].lower() if cfg else ""
                model_keywords = [kw.lower() for kw in cfg["keywords"]] if cfg else []
                if not (make_lower in title_lower or any(kw in title_lower for kw in model_keywords)):
                    continue

                # Reject Prop 65 boilerplate (California cancer warnings)
                if any(pat in snippet_lower for pat in ("cause cancer", "reproductive harm", "prop 65")):
                    continue

                damage_type = ""
                for dmg in DAMAGE_KEYWORDS:
                    if dmg.lower() in combined:
                        damage_type = dmg
                        break

                results.append(SalvageListing(
                    source="Copart" if "copart.com" in r.link else "IAA",
                    model=model_name,
                    title=r.title,
                    url=r.link,
                    snippet=r.snippet[:300],
                    damage_type=damage_type,
                ))

    results.sort(key=lambda x: (x.damage_type != "", x.model), reverse=True)
    return results


def _write_csv(results: list[SalvageListing], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    scraped_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    fieldnames = ["scraped_at", "source", "model", "title", "url", "damage_type", "snippet", "contacted"]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            writer.writerow({
                "scraped_at": scraped_at,
                "source": r.source,
                "model": r.model,
                "title": r.title,
                "url": r.url,
                "damage_type": r.damage_type,
                "snippet": r.snippet,
                "contacted": "",
            })


def run(*, models: list[str] | None, max_queries: int | None, output: Path) -> int:
    queries = _build_queries(models)
    if max_queries:
        queries = queries[:max_queries]

    print(f"Searching Copart & IAA for damaged exotics...")
    print(f"  {len(queries)} queries across {len(set(q[1] for q in queries))} models")
    print(f"  (uses Serper API — each query = 1 credit)")

    results = search_salvage(models, max_queries)

    _write_csv(results, output)
    print(f"\nDone: {len(results)} salvage listings found, written to {output}.")
    if results:
        print(f"  Top hit: {results[0].title}")
        mech = [r for r in results if r.damage_type]
        print(f"  {len(mech)} with identified mechanical/drivetrain damage")
    return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Search Copart/IAA for mechanically-damaged exotics")
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
        default=Path("out") / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}-salvage.csv",
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
