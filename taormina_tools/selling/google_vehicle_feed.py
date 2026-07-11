from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from .inventory import InventoryItem
from .listing_content import generate_short_description, generate_title


def generate_feed(items: list[InventoryItem], output_dir: Path = Path("out")) -> Path:
    """Generate a Google Merchant Center vehicle inventory feed (TSV)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    output_path = output_dir / f"google-vehicle-feed-{today}.tsv"

    fieldnames = [
        "id", "title", "description", "link", "image_link",
        "additional_image_link", "price", "condition", "brand",
        "model", "year", "mileage.value", "mileage.unit", "color",
        "vehicle_id", "trim", "transmission", "drivetrain", "engine",
        "fuel_type", "body_style", "vin",
        "vehicle_fulfillment.store_code", "vehicle_fulfillment.pickup_method",
    ]

    with output_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()

        for item in items:
            photos = item.photo_urls or []
            primary_image = photos[0] if photos else ""
            additional_images = ",".join(photos[1:11]) if len(photos) > 1 else ""

            row = {
                "id": item.vin,
                "title": generate_title(item),
                "description": generate_short_description(item),
                "link": item.website_url,
                "image_link": primary_image,
                "additional_image_link": additional_images,
                "price": f"{item.price} USD" if item.price else "",
                "condition": "used",
                "brand": item.make,
                "model": item.model,
                "year": str(item.year) if item.year else "",
                "mileage.value": str(item.miles) if item.miles else "",
                "mileage.unit": "MI",
                "color": item.exterior_color,
                "vehicle_id": item.vin,
                "trim": item.trim,
                "transmission": item.transmission,
                "drivetrain": item.drivetrain,
                "engine": item.engine,
                "fuel_type": item.fuel_type,
                "body_style": item.body_style,
                "vin": item.vin,
                "vehicle_fulfillment.store_code": item.dealer_zip,
                "vehicle_fulfillment.pickup_method": "buy",
            }
            writer.writerow(row)

    return output_path
