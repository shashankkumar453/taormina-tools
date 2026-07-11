from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from .inventory import InventoryItem
from .listing_content import generate_body_plain, generate_short_description, generate_title


def generate_catalog_feed(items: list[InventoryItem], output_dir: Path = Path("out")) -> Path:
    """Generate a Facebook Commerce Manager vehicle catalog feed (CSV)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    output_path = output_dir / f"fb-catalog-feed-{today}.csv"

    fieldnames = [
        "id", "vehicle_id", "title", "url", "price", "availability",
        "image[0].url", "image[1].url", "image[2].url", "image[3].url",
        "make", "model", "year", "mileage.value", "mileage.unit",
        "body_style", "condition", "drivetrain", "exterior_color",
        "fuel_type", "state_of_vehicle", "transmission", "trim", "vin",
        "description",
        "address.city", "address.region", "address.country", "address.postal_code",
    ]

    with output_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for item in items:
            photos = item.photo_urls or []

            row = {
                "id": item.vin,
                "vehicle_id": item.vin,
                "title": generate_title(item),
                "url": item.website_url,
                "price": f"{item.price} USD" if item.price else "",
                "availability": "in stock",
                "image[0].url": photos[0] if len(photos) > 0 else "",
                "image[1].url": photos[1] if len(photos) > 1 else "",
                "image[2].url": photos[2] if len(photos) > 2 else "",
                "image[3].url": photos[3] if len(photos) > 3 else "",
                "make": item.make,
                "model": item.model,
                "year": str(item.year) if item.year else "",
                "mileage.value": str(item.miles) if item.miles else "",
                "mileage.unit": "MI",
                "body_style": item.body_style,
                "condition": "excellent" if item.title_status.lower() == "clean" else "good",
                "drivetrain": item.drivetrain,
                "exterior_color": item.exterior_color,
                "fuel_type": item.fuel_type,
                "state_of_vehicle": "used",
                "transmission": item.transmission,
                "trim": item.trim,
                "vin": item.vin,
                "description": generate_short_description(item),
                "address.city": item.dealer_city,
                "address.region": item.dealer_state,
                "address.country": "US",
                "address.postal_code": item.dealer_zip,
            }
            writer.writerow(row)

    return output_path


def generate_manual_posts(items: list[InventoryItem], output_dir: Path = Path("out")) -> Path:
    """Generate manual posting templates for Facebook (copy-paste friendly)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    output_path = output_dir / f"fb-manual-posts-{today}.csv"

    fieldnames = ["vin", "title", "price", "body", "photo_urls"]

    with output_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for item in items:
            writer.writerow({
                "vin": item.vin,
                "title": generate_title(item),
                "price": item.price,
                "body": generate_body_plain(item),
                "photo_urls": "|".join(item.photo_urls),
            })

    return output_path
