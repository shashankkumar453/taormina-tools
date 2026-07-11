"""Run the sourcing scripts and generate HTML reports.

Orchestrates the buying scripts (deals, Facebook Marketplace, stale
inventory, salvage, classifieds) and then generates a combined HTML report
from the resulting CSVs.

Usage:
    python -m taormina_tools.run_weekly
    python -m taormina_tools.run_weekly --skip-stale
    python -m taormina_tools.run_weekly --skip-reports
    python -m taormina_tools.run_weekly --max-queries 30
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def run_weekly(
    *,
    skip_stale: bool = False,
    skip_reports: bool = False,
    models: list[str] | None = None,
    max_queries: int | None = None,
    max_days: int = 180,
    output_dir: Path = Path("out"),
) -> int:
    python = sys.executable
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    failures = 0

    scripts: list[tuple[str, list[str]]] = []

    # Serper budget per Serper-backed script (default 50 each)
    serper_budget = max_queries or 50

    # Deal finder
    deal_cmd = [python, "-m", "taormina_tools.buying.price_compare", "--max-days", str(max_days)]
    if models:
        deal_cmd += ["--models"] + models
    scripts.append(("Deal Finder", deal_cmd))

    # Facebook Marketplace deals — scored against the same BaT + C&B baseline as
    # the Deal Finder (mileage + year adjusted).
    fb_cmd = [python, "-m", "taormina_tools.buying.fb_marketplace", "--max-queries", str(serper_budget)]
    if models:
        fb_cmd += ["--models"] + models
    scripts.append(("Facebook Marketplace", fb_cmd))

    # Stale inventory (problem signals — 120+ days on market)
    if not skip_stale:
        stale_cmd = [python, "-m", "taormina_tools.buying.price_compare", "--stale"]
        if models:
            stale_cmd += ["--models"] + models
        scripts.append(("Stale Inventory", stale_cmd))

    # Salvage auctions
    salvage_cmd = [python, "-m", "taormina_tools.buying.copart_search", "--max-queries", str(serper_budget)]
    if models:
        salvage_cmd += ["--models"] + models
    scripts.append(("Copart/IAA Salvage", salvage_cmd))

    # Classifieds search
    forum_cmd = [python, "-m", "taormina_tools.buying.forum_search", "--max-queries", str(serper_budget)]
    if models:
        forum_cmd += ["--models"] + models
    scripts.append(("Classifieds Search", forum_cmd))

    for desc, cmd in scripts:
        print(f"\n{'=' * 60}")
        print(f"  {desc}")
        print(f"{'=' * 60}\n")
        result = subprocess.run(cmd)
        if result.returncode != 0:
            print(f"\n  WARNING: {desc} exited with code {result.returncode}")
            failures += 1

    if not skip_reports:
        csv_files = sorted(output_dir.glob(f"{today}-*.csv"))
        if csv_files:
            print(f"\n{'=' * 60}")
            print(f"  Generating HTML report ({len(csv_files)} CSVs)")
            print(f"{'=' * 60}\n")
            report_cmd = [python, "-m", "taormina_tools.generate_reports"] + [str(f) for f in csv_files]
            subprocess.run(report_cmd)
        else:
            print(f"\nNo CSVs found for {today} in {output_dir} — skipping reports.")

        # Rebuild the landing page so the published site links the newest report.
        subprocess.run([python, "-m", "taormina_tools.generate_index"])

    print(f"\n{'=' * 60}")
    print(f"  Weekly run complete — {len(scripts) - failures}/{len(scripts)} scripts succeeded")
    print(f"{'=' * 60}")
    return 1 if failures == len(scripts) else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the sourcing scripts and generate HTML reports")
    parser.add_argument("--skip-stale", action="store_true", help="Skip stale inventory search")
    parser.add_argument("--skip-reports", action="store_true", help="Run searches but skip HTML generation")
    parser.add_argument("--models", nargs="+", help="Limit which models to search")
    parser.add_argument("--max-queries", type=int, help="Max queries for salvage/classifieds scripts")
    parser.add_argument("--max-days", type=int, default=180, help="Max days on market for the deals search (default: 180)")
    parser.add_argument("--output-dir", type=Path, default=Path("out"), help="CSV output directory (default: out)")
    args = parser.parse_args(argv)

    return run_weekly(
        skip_stale=args.skip_stale,
        skip_reports=args.skip_reports,
        models=args.models,
        max_queries=args.max_queries,
        max_days=args.max_days,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    raise SystemExit(main())
