from __future__ import annotations

from .inventory import InventoryItem


def _key_feature(item: InventoryItem) -> str:
    """Pick the most marketable feature to highlight in the title."""
    trans_lower = item.transmission.lower()
    if "manual" in trans_lower or "6-speed" in trans_lower or "6 speed" in trans_lower:
        return "6-Speed Manual"
    if item.miles and item.miles < 10_000:
        return f"{item.miles:,}mi"
    if item.engine:
        return item.engine
    return ""


def generate_title(item: InventoryItem) -> str:
    """Generate a listing title optimized for search and attention."""
    parts = [str(item.year), item.make, item.model]
    if item.trim:
        parts.append(item.trim)
    title = " ".join(parts)

    feature = _key_feature(item)
    if feature and feature != f"{item.miles:,}mi":
        title += f" - {item.miles:,}mi - {feature}"
    else:
        title += f" - {item.miles:,}mi"

    return title


def generate_body_plain(item: InventoryItem) -> str:
    """Generate plain-text listing body for Facebook/general use."""
    lines: list[str] = []

    lines.append(generate_title(item))
    lines.append("")

    specs: list[str] = []
    if item.year:
        specs.append(f"Year: {item.year}")
    if item.make:
        specs.append(f"Make: {item.make}")
    if item.model:
        specs.append(f"Model: {item.model}")
    if item.trim:
        specs.append(f"Trim: {item.trim}")
    if item.miles:
        specs.append(f"Mileage: {item.miles:,} miles")
    if item.engine:
        specs.append(f"Engine: {item.engine}")
    if item.transmission:
        specs.append(f"Transmission: {item.transmission}")
    if item.drivetrain:
        specs.append(f"Drivetrain: {item.drivetrain}")
    if item.exterior_color:
        specs.append(f"Exterior: {item.exterior_color}")
    if item.interior_color:
        specs.append(f"Interior: {item.interior_color}")
    if item.body_style:
        specs.append(f"Body Style: {item.body_style}")
    if item.fuel_type:
        specs.append(f"Fuel: {item.fuel_type}")
    if item.title_status:
        specs.append(f"Title: {item.title_status}")

    lines.append("\n".join(specs))
    lines.append("")

    if item.description:
        lines.append(item.description)
        lines.append("")

    if item.price:
        lines.append(f"Price: ${item.price:,}")
        lines.append("")

    lines.append(f"VIN: {item.vin}")

    if item.website_url:
        lines.append(f"Full listing: {item.website_url}")

    if item.dealer_phone:
        lines.append(f"Call/Text: {item.dealer_phone}")

    return "\n".join(lines)


def generate_body_html(item: InventoryItem) -> str:
    """Generate light HTML body for Craigslist."""
    parts: list[str] = []

    parts.append(f"<h2>{generate_title(item)}</h2>")

    specs: list[str] = []
    if item.miles:
        specs.append(f"<li><b>Mileage:</b> {item.miles:,} miles</li>")
    if item.engine:
        specs.append(f"<li><b>Engine:</b> {item.engine}</li>")
    if item.transmission:
        specs.append(f"<li><b>Transmission:</b> {item.transmission}</li>")
    if item.drivetrain:
        specs.append(f"<li><b>Drivetrain:</b> {item.drivetrain}</li>")
    if item.exterior_color:
        specs.append(f"<li><b>Exterior:</b> {item.exterior_color}</li>")
    if item.interior_color:
        specs.append(f"<li><b>Interior:</b> {item.interior_color}</li>")
    if item.body_style:
        specs.append(f"<li><b>Body Style:</b> {item.body_style}</li>")
    if item.title_status:
        specs.append(f"<li><b>Title:</b> {item.title_status}</li>")

    if specs:
        parts.append("<ul>" + "\n".join(specs) + "</ul>")

    if item.description:
        parts.append(f"<p>{item.description}</p>")

    parts.append(f"<p><b>VIN:</b> {item.vin}</p>")

    if item.website_url:
        parts.append(f'<p>Full listing: <a href="{item.website_url}">{item.website_url}</a></p>')

    if item.dealer_phone:
        parts.append(f"<p>Call/Text: {item.dealer_phone}</p>")

    return "\n".join(parts)


def generate_short_description(item: InventoryItem, max_chars: int = 500) -> str:
    """Generate a short description for Google/feed use (character-limited)."""
    parts: list[str] = []
    parts.append(f"{item.year} {item.make} {item.model}")
    if item.trim:
        parts.append(f"{item.trim}")
    parts.append(f"with {item.miles:,} miles.")

    highlights: list[str] = []
    if item.transmission:
        highlights.append(item.transmission)
    if item.engine:
        highlights.append(item.engine)
    if item.exterior_color:
        highlights.append(f"{item.exterior_color} exterior")
    if highlights:
        parts.append(" ".join(highlights) + ".")

    if item.title_status and item.title_status.lower() == "clean":
        parts.append("Clean title.")

    desc = " ".join(parts)
    if len(desc) > max_chars:
        desc = desc[: max_chars - 3] + "..."
    return desc
