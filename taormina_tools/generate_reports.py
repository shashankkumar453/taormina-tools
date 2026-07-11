"""Generate a single HTML report from all CSV output files.

Reads CSV files produced by the buying scripts (deals, swaps, salvage,
projects, forums) and renders them into one combined, browsable HTML page
with a navigation bar to jump between sections.

Usage:
    python -m taormina_tools.generate_reports out/2026-05-05-*.csv
    python -m taormina_tools.generate_reports out/*.csv --output-dir docs
"""

from __future__ import annotations

import argparse
import csv
import html
import re
from collections import defaultdict
from pathlib import Path


BASE_CSS = """\
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 1400px; margin: 40px auto; padding: 0 20px; color: #1a1a1a; line-height: 1.5; }
h1 { font-size: 28px; margin-bottom: 4px; }
.subtitle { color: #666; margin-bottom: 10px; font-size: 14px; }
nav { display: flex; gap: 8px; margin: 16px 0 30px; flex-wrap: wrap; }
nav a { display: inline-block; padding: 8px 16px; border-radius: 6px; background: #2c3e50; color: white; font-size: 13px; font-weight: 600; text-decoration: none; }
nav a:hover { background: #1a252f; }
nav a .nav-count { opacity: 0.7; font-weight: 400; margin-left: 4px; }
.report-section { margin-bottom: 60px; }
.report-header { font-size: 24px; margin: 0 0 4px; padding-top: 30px; border-top: 3px solid #8b1c1c; }
.report-desc { color: #666; font-size: 13px; margin-bottom: 16px; }
.stats { display: flex; gap: 16px; margin: 16px 0 20px; flex-wrap: wrap; }
.stat-card { background: #f8f9fa; border-radius: 8px; padding: 14px 20px; border-left: 3px solid #8b1c1c; }
.stat-card .num { font-size: 24px; font-weight: 700; color: #8b1c1c; }
.stat-card .label { font-size: 12px; color: #666; }
.method { background: #f0f7f0; border: 1px solid #c3e6c3; border-radius: 6px; padding: 14px 18px; margin: 12px 0 20px; font-size: 13px; }
.method strong { color: #1a5c1a; }
table { border-collapse: collapse; width: 100%; font-size: 13px; margin-top: 16px; }
th { background: #2c3e50; color: white; padding: 10px 8px; text-align: left; position: sticky; top: 0; z-index: 1; }
td { padding: 8px; border-bottom: 1px solid #eee; vertical-align: top; }
tr:hover td { background: #f5f5f5; }
a { color: #2980b9; text-decoration: none; }
a:hover { text-decoration: underline; }
.good { color: #27ae60; font-weight: 600; }
.bad { color: #c0392b; }
.tag { display: inline-block; padding: 2px 6px; border-radius: 3px; font-size: 11px; font-weight: 600; }
.tag-clean { background: #d4edda; color: #155724; }
.tag-salvage { background: #f8d7da; color: #721c24; }
.tag-1owner { background: #cce5ff; color: #004085; }
.tag-swap { background: #fff3cd; color: #856404; }
.tag-project { background: #e2e3e5; color: #383d41; }
.low-miles { color: #27ae60; }
.high-miles { color: #c0392b; }
.model-title { font-size: 18px; margin: 30px 0 8px; padding-top: 16px; border-top: 1px solid #eee; }
.baseline-info { font-size: 12px; color: #666; margin: 4px 0 12px; }
.highlight-row td { background: #f0fff0; }
.snippet { max-width: 400px; font-size: 12px; color: #555; word-break: break-word; }
.footer { color: #666; font-size: 12px; margin-top: 40px; border-top: 1px solid #eee; padding-top: 12px; }
"""


def _esc(text: str) -> str:
    return html.escape(str(text)) if text else ""


def _stat_card(num: str | int, label: str) -> str:
    return f'<div class="stat-card"><div class="num">{_esc(str(num))}</div><div class="label">{_esc(label)}</div></div>'


# Spider/variant model names the weekly report rolls into their base model, so
# each car shows as a single section instead of separate coupe/Spider columns.
MODEL_ROLLUP: dict[str, str] = {
    "F355 Spider": "F355",
    "F430 Spider": "F430",
    "360 Modena": "360",
    "360 Spider": "360",
}


def _normalize_model(name: str) -> str:
    return MODEL_ROLLUP.get((name or "").strip(), name)


def _group_rows(rows: list[dict], col: str) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        key = row.get(col, "Unknown")
        if col == "model":
            key = _normalize_model(key)
        groups[key].append(row)
    return dict(groups)


def _format_price(val: str) -> str:
    try:
        n = int(float(val))
        return f"${n:,}"
    except (ValueError, TypeError):
        return val or ""


def _score_class(val: str) -> str:
    try:
        return "good" if float(val) > 0 else "bad" if float(val) < 0 else ""
    except (ValueError, TypeError):
        return ""


def _pct_class(val: str) -> str:
    try:
        return "good" if float(val) > 0 else "bad" if float(val) < 0 else ""
    except (ValueError, TypeError):
        return ""


def _miles_class(val: str) -> str:
    if not val:
        return ""
    try:
        mult = float(val.replace("x avg", "").strip())
        return "low-miles" if mult < 0.9 else "high-miles" if mult > 1.1 else ""
    except (ValueError, TypeError):
        return ""


# ── Market values summary ──────────────────────────────────────────

def _render_market_values(deals_rows: list[dict], baselines_rows: list[dict] | None = None) -> str:
    models: dict[str, dict] = {}

    # Seed from baselines CSV (all searched models, even those with 0 listings).
    # Spider variants roll into their base model; the first (base) baseline wins.
    if baselines_rows:
        for r in baselines_rows:
            name = _normalize_model(r.get("model", ""))
            if not name or name in models:
                continue
            models[name] = {
                "median": r.get("median_sold", ""),
                "num_sales": r.get("num_sales", ""),
                "p25": r.get("p25_sold", ""),
                "p75": r.get("p75_sold", ""),
                "price_per_mile": r.get("price_per_mile", ""),
                "price_per_year": r.get("price_per_year", ""),
                "avg_miles": r.get("avg_comp_miles", ""),
                "avg_year": r.get("avg_comp_year", ""),
                "count": 0,
                "best_price": None,
                "best_disc": None,
            }

    # Overlay deal stats
    for r in deals_rows:
        model = _normalize_model(r.get("model", ""))
        if not model:
            continue
        if model not in models:
            models[model] = {
                "median": r.get("market_median", ""),
                "num_sales": "",
                "p25": "",
                "p75": "",
                "price_per_mile": "",
                "price_per_year": "",
                "avg_miles": "",
                "avg_year": "",
                "count": 0,
                "best_price": None,
                "best_disc": None,
            }
        models[model]["count"] += 1
        try:
            price = float(r.get("price", 0) or 0)
            adj = float(r.get("adj_discount_pct", 0) or 0)
            if models[model]["best_disc"] is None or adj > models[model]["best_disc"]:
                models[model]["best_disc"] = adj
                models[model]["best_price"] = price
        except (ValueError, TypeError):
            pass

    parts = [
        '<div class="report-section" id="values">',
        '<h2 class="report-header">Estimated Market Values</h2>',
        '<p class="report-desc">Based on recent Bring a Trailer + Cars &amp; Bids sold prices (mileage + year adjusted regression)</p>',
        "<table>",
        "<tr><th>Model</th><th>Est. Market Value</th><th>Range (P25–P75)</th>"
        "<th>Avg Miles</th><th>$/Mile</th><th>$/Year</th><th>Sales Sampled</th>"
        "<th>Listings Found</th><th>Best Deal</th><th>Best Adj. Disc.</th></tr>",
    ]

    for model, info in sorted(models.items(), key=lambda x: -float(x[1]["median"] or 0)):
        median_fmt = _format_price(info["median"]) if info["median"] else "N/A"
        p25 = _format_price(info["p25"]) if info["p25"] else ""
        p75 = _format_price(info["p75"]) if info["p75"] else ""
        range_fmt = f"{p25}–{p75}" if p25 and p75 else "—"
        avg_miles = info.get("avg_miles", "")
        avg_miles_fmt = f"{int(float(avg_miles)):,}" if avg_miles and avg_miles != "0" else "—"
        ppm = info.get("price_per_mile", "")
        ppm_fmt = f"${float(ppm):,.0f}" if ppm and ppm != "0" and ppm != "0.0" else "—"
        ppy = info.get("price_per_year", "")
        ppy_fmt = f"${float(ppy):,.0f}" if ppy and ppy != "0" and ppy != "0.0" else "—"
        num_sales = info.get("num_sales", "") or "—"
        best_price_fmt = _format_price(str(int(info["best_price"]))) if info["best_price"] else "—"
        best_disc_fmt = f'{info["best_disc"]:.1f}%' if info["best_disc"] is not None else "—"
        disc_class = "good" if (info["best_disc"] or 0) > 0 else "bad" if (info["best_disc"] or 0) < 0 else ""
        parts.append("<tr>")
        parts.append(f"  <td><strong>{_esc(model)}</strong></td>")
        parts.append(f"  <td>{median_fmt}</td>")
        parts.append(f"  <td>{range_fmt}</td>")
        parts.append(f"  <td>{avg_miles_fmt}</td>")
        parts.append(f"  <td>{ppm_fmt}</td>")
        parts.append(f"  <td>{ppy_fmt}</td>")
        parts.append(f"  <td>{_esc(str(num_sales))}</td>")
        parts.append(f"  <td>{info['count']}</td>")
        parts.append(f"  <td>{best_price_fmt}</td>")
        parts.append(f'  <td class="{disc_class}">{best_disc_fmt}</td>')
        parts.append("</tr>")

    parts.append("</table>")
    parts.append("</div>")
    return "\n".join(parts)


# ── Manual swap economics ──────────────────────────────────────────

MANUAL_SWAP_DATA: dict[str, dict] = {
    "360 Modena": {"manual_value": 140000, "swap_cost": 18000, "notes": "F1-to-gated 6-speed. Most common swap; well-documented process."},
    "360 Spider": {"manual_value": 110000, "swap_cost": 18000, "notes": "Same drivetrain as Modena. Spiders trade lower but manual premium still strong."},
    "F430": {"manual_value": 260000, "swap_cost": 22000, "notes": "F1-to-gated 6-speed. Largest profit margin — manual F430s are highly sought."},
    "F430 Spider": {"manual_value": 180000, "swap_cost": 22000, "notes": "Same swap as coupe. Spider manual premiums slightly lower but still significant."},
    "575M": {"manual_value": 175000, "swap_cost": 20000, "notes": "F1-to-gated 6-speed. V12 GT cruiser with strong manual demand."},
    "599 GTB": {"manual_value": 250000, "swap_cost": 25000, "notes": "F1-to-gated 6-speed. Low production manual cars; swap adds huge value."},
    "Gallardo": {"manual_value": 180000, "swap_cost": 20000, "notes": "E-gear to gated 6-speed. Well-proven swap with strong aftermarket support."},
    "Gallardo Spyder": {"manual_value": 145000, "swap_cost": 20000, "notes": "Same e-gear swap as coupe. Spyder manual variants are very rare."},
    "Murcielago": {"manual_value": 600000, "swap_cost": 25000, "notes": "E-gear to gated 6-speed. Manual Murcielagos are unicorns — massive premium."},
}


def _render_swap_economics(baselines_rows: list[dict] | None, deals_rows: list[dict] | None) -> str:
    medians: dict[str, int] = {}
    if baselines_rows:
        for r in baselines_rows:
            name = r.get("model", "")
            try:
                medians[name] = int(float(r.get("median_sold", 0)))
            except (ValueError, TypeError):
                pass
    if deals_rows:
        for r in deals_rows:
            name = r.get("model", "")
            if name and name not in medians:
                try:
                    medians[name] = int(float(r.get("market_median", 0)))
                except (ValueError, TypeError):
                    pass

    parts = [
        '<div class="report-section" id="swap-economics">',
        '<h2 class="report-header">Manual Swap Targets</h2>',
        '<p class="report-desc">F1/e-gear exotics where converting to manual gearbox unlocks significant value. '
        'Swap cost is for parts + labor at a specialist shop.</p>',
        "<table>",
        "<tr><th>Model</th><th>F1/E-gear Value</th><th>Manual Value</th>"
        "<th>Swap Cost</th><th>Potential Profit</th><th>ROI</th><th>Notes</th></tr>",
    ]

    for model, data in MANUAL_SWAP_DATA.items():
        f1_value = medians.get(model)
        if not f1_value:
            continue
        manual_value = data["manual_value"]
        swap_cost = data["swap_cost"]
        profit = manual_value - f1_value - swap_cost
        roi = profit / (f1_value + swap_cost) * 100 if (f1_value + swap_cost) > 0 else 0
        profit_class = "good" if profit > 0 else "bad"

        parts.append("<tr>")
        parts.append(f"  <td><strong>{_esc(model)}</strong></td>")
        parts.append(f"  <td>{_format_price(str(f1_value))}</td>")
        parts.append(f"  <td>{_format_price(str(manual_value))}</td>")
        parts.append(f"  <td>{_format_price(str(swap_cost))}</td>")
        parts.append(f'  <td class="{profit_class}"><strong>{_format_price(str(profit))}</strong></td>')
        parts.append(f'  <td class="{profit_class}">{roi:.0f}%</td>')
        parts.append(f'  <td class="snippet">{_esc(data["notes"])}</td>')
        parts.append("</tr>")

    parts.append("</table>")
    parts.append("</div>")
    return "\n".join(parts)


# ── Section renderers ───────────────────────────────────────────────

def _render_deals_section(rows: list[dict], report_type: str) -> str:
    anchor = report_type
    if report_type == "stale":
        title = "Stale Inventory (Problem Signals)"
        method_text = (
            "<strong>Stale inventory:</strong> Dealer listings sitting 120+ days on market, "
            "sorted by days on lot. Cars that sit this long usually have undisclosed problems — "
            "mechanical issues, title problems, or dealers who can't move them. "
            "The longer it sits, the more negotiable the price. Non-clean titles are highlighted "
            "as fixable opportunities."
        )
    elif report_type == "swaps":
        title = "Manual Swap Candidates"
        method_text = (
            "<strong>Manual-swap economics:</strong> F1/e-gear exotics (Ferrari 360, F430, "
            "Gallardo, etc.) trade 30-50% below their manual equivalents. Converting the "
            "transmission costs $15-25k but unlocks $50-100k+ in value. This section shows "
            "F1/e-gear cars priced below mileage-adjusted market value — the best swap candidates."
        )
    else:
        title = "Deal Finder"
        method_text = (
            '<strong>How market price is determined:</strong> Recent sold prices from '
            "Bring a Trailer (with mileage and year from titles) + Cars &amp; Bids (via Google). "
            "A multivariate regression on price vs. mileage and model year calculates what each car "
            "<em>should</em> cost at its specific odometer reading and year. "
            'The "Adj. Disc." column shows how far below that adjusted expected price '
            "this listing is — a much more accurate picture than a flat median comparison."
        )

    rows.sort(key=lambda r: -float(r.get("score", 0) or 0))
    groups = _group_rows(rows, "model")

    positive_scores = sum(1 for r in rows if float(r.get("score", 0) or 0) > 0)

    parts = [
        f'<div class="report-section" id="{anchor}">',
        f'<h2 class="report-header">{_esc(title)}</h2>',
        f'<p class="report-desc">{len(rows)} listings found</p>',
        f'<div class="method">{method_text}</div>',
        '<div class="stats">',
        _stat_card(len(rows), "Total Listings"),
        _stat_card(positive_scores, "Positive Score"),
        _stat_card(len(groups), "Models"),
        "</div>",
    ]

    for model, model_rows in groups.items():
        model_rows.sort(key=lambda r: -float(r.get("score", 0) or 0))
        median = model_rows[0].get("market_median", "")
        median_str = _format_price(median) if median else "N/A"
        parts.append(f'<h3 class="model-title">{_esc(model)} ({len(model_rows)} listings)</h3>')
        parts.append(f'<div class="baseline-info">Market baseline: Median {median_str}</div>')
        parts.append("<table>")
        parts.append(
            "<tr><th>Score</th><th>Year</th><th>Listing</th><th>Price</th>"
            "<th>Disc.</th><th>Adj. Disc.</th><th>Miles</th><th>vs Avg</th>"
            "<th>Days</th><th>Trans.</th><th>Color</th>"
            "<th>Dealer</th><th>State</th><th>Phone</th></tr>"
        )
        for r in model_rows:
            score = r.get("score", "")
            url = r.get("url", "")
            heading = r.get("heading", "") or f'{r.get("year", "")} {model}'
            link = f'<a href="{_esc(url)}" target="_blank">{_esc(heading)}</a>' if url else _esc(heading)
            disc = r.get("discount_pct", "")
            adj_disc = r.get("adj_discount_pct", "")
            miles = r.get("miles", "")
            miles_fmt = f"{int(float(miles)):,}" if miles else ""
            vs_avg = r.get("miles_vs_avg", "")
            days = r.get("days_on_market", "")
            color = r.get("color", "")
            trans = r.get("transmission", "")
            trans_lower = trans.lower() if trans else ""
            model_lower = model.lower()
            is_f1_egear_model = any(m in model_lower for m in (
                "360", "f430", "430", "575", "599", "612", "f355", "355",
                "gallardo", "murcielago",
            ))
            manual_pats = ("manual", "6-speed", "6 speed", "6spd", "5-speed",
                           "5 speed", "stick", "gated", "3-pedal", "h-pattern")
            is_manual = (
                any(p in trans_lower for p in manual_pats)
                and "automated" not in trans_lower
            )
            is_f1 = any(p in trans_lower for p in (
                "f1", "e-gear", "egear", "automated", "cambiocorsa", "paddle",
                "sequential", "selespeed", "robotized", "single clutch",
            ))
            if not is_f1 and is_f1_egear_model and trans_lower in ("automatic", ""):
                is_f1 = True
            if is_manual:
                trans_html = '<span class="tag tag-clean">Manual</span>'
            elif is_f1:
                trans_html = '<span class="tag tag-swap">F1/e-gear</span>'
            else:
                trans_html = _esc(trans) if trans else "Auto"

            parts.append("<tr>")
            parts.append(f'  <td class="{_score_class(score)}">{_esc(score)}</td>')
            parts.append(f"  <td>{_esc(r.get('year', ''))}</td>")
            parts.append(f"  <td>{link}</td>")
            parts.append(f"  <td><strong>{_format_price(r.get('price', ''))}</strong></td>")
            parts.append(f"  <td>{_esc(disc)}{'%' if disc else ''}</td>")
            parts.append(f'  <td class="{_pct_class(adj_disc)}">{_esc(adj_disc)}{"%" if adj_disc else ""}</td>')
            parts.append(f"  <td>{miles_fmt}</td>")
            parts.append(f'  <td class="{_miles_class(vs_avg)}">{_esc(vs_avg)}</td>')
            parts.append(f"  <td>{_esc(days)}</td>")
            parts.append(f"  <td>{trans_html}</td>")
            parts.append(f"  <td>{_esc(color)}</td>")
            parts.append(f"  <td>{_esc(r.get('dealer_name', ''))}</td>")
            parts.append(f"  <td>{_esc(r.get('dealer_state', ''))}</td>")
            parts.append(f"  <td>{_esc(r.get('dealer_phone', ''))}</td>")
            parts.append("</tr>")
        parts.append("</table>")

    parts.append("</div>")
    return "\n".join(parts)


def _render_fbmarket_section(rows: list[dict]) -> str:
    rows.sort(key=lambda r: -float(r.get("score", 0) or 0))
    groups = _group_rows(rows, "model")
    positive_scores = sum(1 for r in rows if float(r.get("score", 0) or 0) > 0)
    with_miles = sum(1 for r in rows if (r.get("miles", "") or "").strip())

    parts = [
        '<div class="report-section" id="fbmarket">',
        '<h2 class="report-header">Facebook Marketplace</h2>',
        f'<p class="report-desc">{len(rows)} listings found</p>',
        '<div class="method">'
        "<strong>Facebook Marketplace deals:</strong> Private-seller listings scored against the "
        "<em>same</em> Bring a Trailer + Cars &amp; Bids baseline as the Deal Finder "
        "(mileage + year adjusted). Price, mileage, and year are parsed from each listing's "
        "search snippet, so coverage depends on what Google indexes — rows with mileage are "
        "mileage-adjusted; rows without fall back to the flat median, and the snippet is shown "
        "so you can sanity-check before reaching out."
        "</div>",
        '<div class="stats">',
        _stat_card(len(rows), "Total Listings"),
        _stat_card(positive_scores, "Positive Score"),
        _stat_card(with_miles, "With Mileage"),
        _stat_card(len(groups), "Models"),
        "</div>",
    ]

    for model, model_rows in groups.items():
        model_rows.sort(key=lambda r: -float(r.get("score", 0) or 0))
        median = model_rows[0].get("market_median", "")
        median_str = _format_price(median) if median else "N/A"
        parts.append(f'<h3 class="model-title">{_esc(model)} ({len(model_rows)} listings)</h3>')
        parts.append(f'<div class="baseline-info">Market baseline: Median {median_str}</div>')
        parts.append("<table>")
        parts.append(
            "<tr><th>Score</th><th>Year</th><th>Listing</th><th>Price</th>"
            "<th>Disc.</th><th>Adj. Disc.</th><th>Miles</th><th>vs Avg</th><th>Snippet</th></tr>"
        )
        for r in model_rows:
            score = r.get("score", "")
            url = r.get("url", "")
            heading = r.get("heading", "") or f'{r.get("year", "")} {model}'
            link = f'<a href="{_esc(url)}" target="_blank">{_esc(heading)}</a>' if url else _esc(heading)
            disc = r.get("discount_pct", "")
            adj_disc = r.get("adj_discount_pct", "")
            miles = r.get("miles", "")
            miles_fmt = f"{int(float(miles)):,}" if miles else ""
            vs_avg = r.get("miles_vs_avg", "")

            parts.append("<tr>")
            parts.append(f'  <td class="{_score_class(score)}">{_esc(score)}</td>')
            parts.append(f"  <td>{_esc(r.get('year', ''))}</td>")
            parts.append(f"  <td>{link}</td>")
            parts.append(f"  <td><strong>{_format_price(r.get('price', ''))}</strong></td>")
            parts.append(f"  <td>{_esc(disc)}{'%' if disc else ''}</td>")
            parts.append(f'  <td class="{_pct_class(adj_disc)}">{_esc(adj_disc)}{"%" if adj_disc else ""}</td>')
            parts.append(f"  <td>{miles_fmt}</td>")
            parts.append(f'  <td class="{_miles_class(vs_avg)}">{_esc(vs_avg)}</td>')
            parts.append(f'  <td class="snippet">{_esc(r.get("snippet", ""))}</td>')
            parts.append("</tr>")
        parts.append("</table>")

    parts.append("</div>")
    return "\n".join(parts)


def _render_salvage_section(rows: list[dict]) -> str:
    groups = _group_rows(rows, "model")
    with_damage = sum(1 for r in rows if r.get("damage_type", "").strip())
    copart = sum(1 for r in rows if r.get("source", "").strip().lower() == "copart")
    iaa = sum(1 for r in rows if r.get("source", "").strip().lower() == "iaa")

    parts = [
        '<div class="report-section" id="salvage">',
        '<h2 class="report-header">Salvage Auctions</h2>',
        f'<p class="report-desc">{len(rows)} listings found</p>',
        '<div class="method">'
        "<strong>Salvage auction search:</strong> Copart &amp; IAA listings found via Google "
        "for mechanically-damaged exotics — engine, transmission, drivetrain issues. "
        "These are insurance total-loss or dealer trade-ins with expensive problems, "
        "ideal for fix-and-flip or manual-swap donor cars."
        "</div>",
        '<div class="stats">',
        _stat_card(len(rows), "Total Listings"),
        _stat_card(with_damage, "With Damage Type"),
        _stat_card(copart, "Copart"),
        _stat_card(iaa, "IAA"),
        _stat_card(len(groups), "Models"),
        "</div>",
    ]

    for model, model_rows in groups.items():
        parts.append(f'<h3 class="model-title">{_esc(model)} ({len(model_rows)} listings)</h3>')
        parts.append("<table>")
        parts.append("<tr><th>Source</th><th>Listing</th><th>Damage Type</th><th>Snippet</th></tr>")
        for r in model_rows:
            url = r.get("url", "")
            title = r.get("title", "") or "View listing"
            link = f'<a href="{_esc(url)}" target="_blank">{_esc(title)}</a>' if url else _esc(title)
            damage = r.get("damage_type", "")
            damage_html = f'<span class="tag tag-salvage">{_esc(damage)}</span>' if damage else ""

            parts.append("<tr>")
            parts.append(f"  <td>{_esc(r.get('source', ''))}</td>")
            parts.append(f"  <td>{link}</td>")
            parts.append(f"  <td>{damage_html}</td>")
            parts.append(f'  <td class="snippet">{_esc(r.get("snippet", ""))}</td>')
            parts.append("</tr>")
        parts.append("</table>")

    parts.append("</div>")
    return "\n".join(parts)


def _render_forums_section(rows: list[dict]) -> str:
    groups = _group_rows(rows, "model")
    with_problem = sum(1 for r in rows if r.get("problem_matched", "").strip())
    with_signal = sum(1 for r in rows if r.get("sale_signal", "").strip())
    both = sum(
        1 for r in rows
        if r.get("problem_matched", "").strip() and r.get("sale_signal", "").strip()
    )

    parts = [
        '<div class="report-section" id="forums">',
        '<h2 class="report-header">Forum Listings</h2>',
        f'<p class="report-desc">{len(rows)} listings found</p>',
        '<div class="method">'
        "<strong>Forum search:</strong> Enthusiast forums (FerrariChat, Rennlist, "
        "Lamborghini Talk, 6SpeedOnline, PistonHeads, etc.) scanned for &quot;for sale&quot; "
        "posts mentioning mechanical issues or urgency signals. "
        "Rows highlighted green have <em>both</em> a problem keyword and a sale signal — highest priority."
        "</div>",
        '<div class="stats">',
        _stat_card(len(rows), "Total Listings"),
        _stat_card(with_problem, "With Problem Keyword"),
        _stat_card(with_signal, "With Sale Signal"),
        _stat_card(both, "Both (High Priority)"),
        _stat_card(len(groups), "Models"),
        "</div>",
    ]

    for model, model_rows in groups.items():
        parts.append(f'<h3 class="model-title">{_esc(model)} ({len(model_rows)} listings)</h3>')
        parts.append("<table>")
        parts.append("<tr><th>Forum</th><th>Listing</th><th>Problem</th><th>Sale Signal</th><th>Snippet</th></tr>")
        for r in model_rows:
            url = r.get("url", "")
            title = r.get("title", "") or "View post"
            link = f'<a href="{_esc(url)}" target="_blank">{_esc(title)}</a>' if url else _esc(title)
            problem = r.get("problem_matched", "").strip()
            signal = r.get("sale_signal", "").strip()
            is_hot = bool(problem and signal)
            row_class = ' class="highlight-row"' if is_hot else ""
            problem_html = f'<span class="tag tag-salvage">{_esc(problem)}</span>' if problem else ""
            signal_html = f'<span class="tag tag-clean">{_esc(signal)}</span>' if signal else ""

            parts.append(f"<tr{row_class}>")
            parts.append(f"  <td>{_esc(r.get('forum', ''))}</td>")
            parts.append(f"  <td>{link}</td>")
            parts.append(f"  <td>{problem_html}</td>")
            parts.append(f"  <td>{signal_html}</td>")
            parts.append(f'  <td class="snippet">{_esc(r.get("snippet", ""))}</td>')
            parts.append("</tr>")
        parts.append("</table>")

    parts.append("</div>")
    return "\n".join(parts)


# ── Combined report ─────────────────────────────────────────────────

# Sections rendered in the report, in order. The Swap Candidates and Project Cars
# listings sections were removed; the Manual Swap Targets summary table is kept.
SECTION_ORDER = ["deals", "fbmarket", "stale", "salvage", "forums"]
# CSV types we still parse — swaps/projects CSVs from older runs load without
# error but no longer get their own section.
ALL_CSV_TYPES = SECTION_ORDER + ["swaps", "projects", "baselines"]

SECTION_LABELS = {
    "deals": "Deals",
    "fbmarket": "FB Marketplace",
    "stale": "Stale Inventory",
    "salvage": "Salvage",
    "forums": "Classifieds",
}


def _detect_type(filename: str) -> str | None:
    for suffix in ALL_CSV_TYPES:
        if filename.endswith(f"-{suffix}.csv"):
            return suffix
    return None


def _extract_date(filename: str) -> str:
    m = re.match(r"(\d{4}-\d{2}-\d{2})", filename)
    return m.group(1) if m else "unknown"


def _load_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def generate_combined_report(csv_paths: list[Path], output_dir: Path) -> Path | None:
    sections: dict[str, list[dict]] = {}
    report_date = "unknown"

    for path in csv_paths:
        rtype = _detect_type(path.name)
        if not rtype:
            print(f"  Skipping {path.name} — unrecognized CSV type")
            continue
        rows = _load_csv(path)
        if not rows:
            print(f"  Skipping {path.name} — empty CSV")
            continue
        sections[rtype] = rows
        d = _extract_date(path.name)
        if d != "unknown":
            report_date = d

    if not sections:
        print("No valid CSVs to report on.")
        return None

    total_listings = sum(len(rows) for key, rows in sections.items() if key in SECTION_ORDER)
    num_sources = sum(1 for key in sections if key in SECTION_ORDER)

    # Navigation bar
    nav_parts = ["<nav>"]
    has_deals = "deals" in sections or "swaps" in sections
    if has_deals:
        nav_parts.append('<a href="#values">Market Values</a>')
        nav_parts.append('<a href="#swap-economics">Swap Targets</a>')
    for key in SECTION_ORDER:
        if key in sections:
            count = len(sections[key])
            label = SECTION_LABELS[key]
            nav_parts.append(
                f'<a href="#{key}">{_esc(label)}<span class="nav-count">({count})</span></a>'
            )
    nav_parts.append("</nav>")
    nav_html = "\n".join(nav_parts)

    # Render each section
    body_parts = [nav_html]

    # Market values summary (baselines + deals/swaps stats)
    value_rows = (
        sections.get("deals", [])
        + sections.get("fbmarket", [])
        + sections.get("swaps", [])
        + sections.get("stale", [])
    )
    baselines_rows = sections.get("baselines")
    if value_rows or baselines_rows:
        body_parts.append(_render_market_values(value_rows, baselines_rows))
        body_parts.append(_render_swap_economics(baselines_rows, value_rows))

    for key in SECTION_ORDER:
        if key not in sections:
            continue
        rows = sections[key]
        if key in ("deals", "stale"):
            body_parts.append(_render_deals_section(rows, key))
        elif key == "fbmarket":
            body_parts.append(_render_fbmarket_section(rows))
        elif key == "salvage":
            body_parts.append(_render_salvage_section(rows))
        elif key == "forums":
            body_parts.append(_render_forums_section(rows))

    body_parts.append('<div class="footer">')
    body_parts.append(
        '<strong>How to read deals/swaps:</strong> "Disc." = raw discount vs flat median. '
        '"Adj. Disc." = discount vs mileage+year adjusted expected price (the real signal). '
        "Score combines adjusted discount + days on lot + title status + owner history. "
        "Positive score = genuinely underpriced."
    )
    body_parts.append("</div>")

    body = "\n".join(body_parts)

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"report-{report_date}.html"

    page = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Taormina Tools — Weekly Report {_esc(report_date)}</title>
<style>
{BASE_CSS}
</style>
</head>
<body>
<h1>Weekly Report</h1>
<p class="subtitle">Generated {_esc(report_date)} | {total_listings} total leads across {num_sources} sources</p>
{body}
</body>
</html>"""

    out_path.write_text(page, encoding="utf-8")
    print(f"  Wrote {out_path}")
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a combined HTML report from CSV files")
    parser.add_argument("csv_files", nargs="+", type=Path, help="CSV files to include")
    parser.add_argument("--output-dir", type=Path, default=Path("docs"), help="Output directory (default: docs)")
    args = parser.parse_args(argv)

    valid = [p for p in args.csv_files if p.exists()]
    missing = [p for p in args.csv_files if not p.exists()]
    for p in missing:
        print(f"  File not found: {p}")

    if not valid:
        print("No CSV files found.")
        return 1

    result = generate_combined_report(valid, args.output_dir)
    return 0 if result else 1


if __name__ == "__main__":
    raise SystemExit(main())
