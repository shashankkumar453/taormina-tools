from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class InventoryItem:
    vin: str
    year: int
    make: str
    model: str
    trim: str = ""
    price: int = 0
    miles: int = 0
    exterior_color: str = ""
    interior_color: str = ""
    transmission: str = ""
    engine: str = ""
    drivetrain: str = ""
    body_style: str = ""
    fuel_type: str = ""
    title_status: str = "Clean"
    description: str = ""
    photo_urls: list[str] = field(default_factory=list)
    dealer_name: str = ""
    dealer_phone: str = ""
    dealer_address: str = ""
    dealer_city: str = ""
    dealer_state: str = ""
    dealer_zip: str = ""
    website_url: str = ""


COLUMN_ALIASES: dict[str, list[str]] = {
    "vin": ["vin", "VIN", "Vehicle ID", "vehicle_identification_number", "Stock #"],
    "year": ["year", "Year", "model_year", "Model Year"],
    "make": ["make", "Make", "Manufacturer"],
    "model": ["model", "Model"],
    "trim": ["trim", "Trim", "Trim Level", "Series"],
    "price": ["price", "Price", "selling_price", "Selling Price", "Asking Price", "Internet Price", "List Price"],
    "miles": ["miles", "mileage", "Mileage", "Miles", "Odometer", "Odometer Reading"],
    "exterior_color": ["exterior_color", "Exterior Color", "Ext Color", "Color"],
    "interior_color": ["interior_color", "Interior Color", "Int Color"],
    "transmission": ["transmission", "Transmission", "Trans"],
    "engine": ["engine", "Engine", "Engine Description"],
    "drivetrain": ["drivetrain", "Drivetrain", "Drive Type", "Drive"],
    "body_style": ["body_style", "Body Style", "Body", "Body Type", "Style"],
    "fuel_type": ["fuel_type", "Fuel Type", "Fuel"],
    "title_status": ["title_status", "Title", "Title Status"],
    "description": ["description", "Description", "Comments", "Vehicle Description", "Seller Comments"],
    "dealer_name": ["dealer_name", "Dealer Name", "Dealer"],
    "dealer_phone": ["dealer_phone", "Dealer Phone", "Phone"],
    "dealer_address": ["dealer_address", "Address", "Street"],
    "dealer_city": ["dealer_city", "City"],
    "dealer_state": ["dealer_state", "State"],
    "dealer_zip": ["dealer_zip", "Zip", "Zip Code", "Postal Code"],
    "website_url": ["website_url", "URL", "VDP URL", "Listing URL", "Link"],
}


def _build_column_map(headers: list[str]) -> dict[str, str]:
    """Map CSV column headers to canonical field names."""
    col_map: dict[str, str] = {}
    for field_name, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            normalized = alias.strip().lower()
            for header in headers:
                if header.strip().lower() == normalized:
                    col_map[field_name] = header
                    break
            if field_name in col_map:
                break
    return col_map


def _parse_photos(row: dict[str, str], headers: list[str]) -> list[str]:
    """Extract photo URLs from columns like Photo 1, Photo 2, ... or a delimited field."""
    photos: list[str] = []
    for h in headers:
        lower = h.strip().lower()
        if lower.startswith("photo") or lower.startswith("image"):
            val = row.get(h, "").strip()
            if val:
                if "|" in val:
                    photos.extend(u.strip() for u in val.split("|") if u.strip())
                elif "," in val and val.startswith("http"):
                    photos.extend(u.strip() for u in val.split(",") if u.strip())
                else:
                    photos.append(val)
    return photos


def load_inventory(csv_path: str | Path) -> list[InventoryItem]:
    """Load inventory from a DealerCenter CSV export."""
    path = Path(csv_path)
    items: list[InventoryItem] = []

    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        col_map = _build_column_map(headers)

        for row in reader:
            def get(field_name: str, default: str = "") -> str:
                header = col_map.get(field_name)
                if header is None:
                    return default
                return row.get(header, default).strip()

            vin = get("vin")
            if not vin:
                continue

            year_str = get("year", "0")
            year = int(year_str) if year_str.isdigit() else 0

            price_str = get("price", "0").replace(",", "").replace("$", "").replace(" ", "")
            price = int(float(price_str)) if price_str else 0

            miles_str = get("miles", "0").replace(",", "").replace(" ", "")
            miles = int(float(miles_str)) if miles_str else 0

            photos = _parse_photos(row, headers)

            items.append(InventoryItem(
                vin=vin,
                year=year,
                make=get("make"),
                model=get("model"),
                trim=get("trim"),
                price=price,
                miles=miles,
                exterior_color=get("exterior_color"),
                interior_color=get("interior_color"),
                transmission=get("transmission"),
                engine=get("engine"),
                drivetrain=get("drivetrain"),
                body_style=get("body_style"),
                fuel_type=get("fuel_type"),
                title_status=get("title_status", "Clean"),
                description=get("description"),
                photo_urls=photos,
                dealer_name=get("dealer_name"),
                dealer_phone=get("dealer_phone"),
                dealer_address=get("dealer_address"),
                dealer_city=get("dealer_city"),
                dealer_state=get("dealer_state"),
                dealer_zip=get("dealer_zip"),
                website_url=get("website_url"),
            ))

    return items
