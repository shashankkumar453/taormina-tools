from __future__ import annotations

from datetime import date
from pathlib import Path

from .inventory import InventoryItem
from .listing_content import generate_body_html, generate_title


def generate_posts(
    items: list[InventoryItem],
    region: str = "sfbay",
    output_dir: Path = Path("out"),
) -> Path:
    """Generate Craigslist posting template files (one per car)."""
    today = date.today().isoformat()
    post_dir = output_dir / f"craigslist-posts-{today}"
    post_dir.mkdir(parents=True, exist_ok=True)

    for item in items:
        filename = f"{item.vin}.txt"
        filepath = post_dir / filename

        header_lines = [
            f"# Craigslist Posting Template",
            f"# Region: {region}",
            f"# Category: cars+trucks - by dealer",
            f"# Post URL: https://{region}.craigslist.org/post",
            f"#",
            f"# Title: {generate_title(item)}",
            f"# Price: {item.price}",
            f"# VIN: {item.vin}",
            f"#",
            f"# Photos to upload ({len(item.photo_urls)}):",
        ]
        for i, url in enumerate(item.photo_urls, 1):
            header_lines.append(f"#   {i}. {url}")

        header_lines.append("#")
        header_lines.append("# --- BODY (copy below this line) ---")
        header_lines.append("")

        body = generate_body_html(item)

        content = "\n".join(header_lines) + body + "\n"
        filepath.write_text(content)

    return post_dir
