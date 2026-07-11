from __future__ import annotations

import argparse
from pathlib import Path

from .craigslist_post import generate_posts as cl_posts
from .fb_catalog_feed import generate_catalog_feed, generate_manual_posts
from .google_vehicle_feed import generate_feed as google_feed
from .inventory import load_inventory
from .posting_tracker import is_posted, load_log, mark_posted, save_log

PLATFORMS = ("fb-catalog", "fb-manual", "craigslist", "google")


def run(
    input_path: str,
    platforms: list[str] | None = None,
    cl_region: str = "sfbay",
    vins: list[str] | None = None,
    output_dir: str = "out",
) -> None:
    out = Path(output_dir)
    items = load_inventory(input_path)

    if not items:
        print("No inventory items found in input file.")
        return

    if vins:
        vin_set = set(v.upper() for v in vins)
        items = [i for i in items if i.vin.upper() in vin_set]
        if not items:
            print(f"No items matched VINs: {vins}")
            return

    target_platforms = platforms or list(PLATFORMS)
    log = load_log(out / "posting-log.json")

    print(f"Loaded {len(items)} inventory items.")

    for platform in target_platforms:
        already_posted = [i for i in items if is_posted(log, i.vin, platform)]
        new_items = [i for i in items if not is_posted(log, i.vin, platform)]

        if already_posted:
            print(f"  [{platform}] Skipping {len(already_posted)} already-posted items.")

        if not new_items:
            print(f"  [{platform}] Nothing new to generate.")
            continue

        if platform == "google":
            path = google_feed(new_items, out)
            print(f"  [{platform}] Generated: {path}")
        elif platform == "fb-catalog":
            path = generate_catalog_feed(new_items, out)
            print(f"  [{platform}] Generated: {path}")
        elif platform == "fb-manual":
            path = generate_manual_posts(new_items, out)
            print(f"  [{platform}] Generated: {path}")
        elif platform == "craigslist":
            path = cl_posts(new_items, region=cl_region, output_dir=out)
            print(f"  [{platform}] Generated: {path}")
        else:
            print(f"  Unknown platform: {platform}")
            continue

        for item in new_items:
            mark_posted(log, item.vin, platform)

    save_log(log, out / "posting-log.json")
    print("Done. Posting log updated.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cross-post vehicle inventory to multiple platforms."
    )
    parser.add_argument("--input", required=True, help="Path to inventory CSV (DealerCenter export)")
    parser.add_argument(
        "--platform",
        choices=PLATFORMS,
        action="append",
        help="Target platform (can specify multiple). Omit for all.",
    )
    parser.add_argument("--cl-region", default="sfbay", help="Craigslist region (default: sfbay)")
    parser.add_argument("--vins", nargs="+", help="Only process specific VINs")
    parser.add_argument("--output-dir", default="out", help="Output directory (default: out)")

    args = parser.parse_args()
    run(
        input_path=args.input,
        platforms=args.platform,
        cl_region=args.cl_region,
        vins=args.vins,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    main()
