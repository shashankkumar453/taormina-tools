"""Compare dealer listing prices against BaT sold-price baselines.

Pulls recent BaT sold prices per model to establish market value, then
queries MarketCheck for active dealer inventory priced below that baseline.
Flags cars that are both underpriced AND sitting long (high days-on-market).

Usage:
    python -m taormina_tools.buying.price_compare
    python -m taormina_tools.buying.price_compare --models "458" "GT3" --discount 15
    python -m taormina_tools.buying.price_compare --zip 90210 --radius 100
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

from ..marketcheck import Listing, MarketCheckClient


# Models where F1/e-gear versions exist and manual swaps make economic sense.
# The profit opportunity: F1 cars trade 30-50% below their manual equivalent.
MANUAL_SWAP_MODELS: list[str] = [
    "F355", "F355 Spider",
    "360 Modena", "360 Spider",
    "F430", "F430 Spider",
    "575M", "599 GTB", "612 Scaglietti",
    "Gallardo", "Gallardo Spyder", "Murcielago",
]

# The cars the weekly report is pointed at, going forward: Ferrari 355, 360,
# F430, 575M, 599 — coupes plus Spider variants where they exist. This is the
# default model set when no --models is passed. MODEL_CONFIG still holds the full
# catalog, so `--models <anything>` continues to work for ad-hoc searches.
FOCUS_MODELS: list[str] = [
    "F355", "F355 Spider",
    "360 Modena", "360 Spider",
    "F430", "F430 Spider",
    "575M", "599 GTB",
]

# Transmission strings that indicate F1/e-gear (automated single-clutch)
F1_EGEAR_TRANS_PATTERNS: list[str] = [
    "f1", "e-gear", "egear", "e gear", "cambiocorsa",
    "automated manual", "single clutch", "paddle",
    "sequential", "selespeed", "robotized",
]

MANUAL_TRANS_PATTERNS: list[str] = [
    "manual", "6-speed", "6 speed", "6spd", "5-speed", "5 speed",
    "stick", "gated", "3-pedal", "three pedal", "h-pattern",
]


# Map model names to (make, model) for MarketCheck queries + BaT slug for sold prices.
# MarketCheck uses standardized make/model strings.
MODEL_CONFIG: dict[str, dict] = {
    # Ferrari — modern
    "458": {"make": "ferrari", "model": "458", "bat_slug": "ferrari/458", "year_range": "2010-2015"},
    "458 Spider": {"make": "ferrari", "model": "458 spider", "bat_slug": "ferrari/458-spider", "year_range": "2012-2015"},
    "458 Speciale": {"make": "ferrari", "model": "458 speciale", "bat_slug": "ferrari/458-speciale", "year_range": "2014-2015"},
    "488": {"make": "ferrari", "model": "488", "bat_slug": "ferrari/488", "year_range": "2016-2020"},
    "488 Spider": {"make": "ferrari", "model": "488 spider", "bat_slug": "ferrari/488-spider", "year_range": "2016-2020"},
    "F12": {"make": "ferrari", "model": "f12", "bat_slug": "ferrari/f12berlinetta", "year_range": "2013-2017"},
    "812 Superfast": {"make": "ferrari", "model": "812", "bat_slug": "ferrari/812-superfast", "year_range": "2018-2024"},
    "Portofino": {"make": "ferrari", "model": "portofino", "bat_slug": "ferrari/portofino", "year_range": "2018-2024"},
    "Roma": {"make": "ferrari", "model": "roma", "bat_slug": "ferrari/roma", "year_range": "2021-2024"},
    "California": {"make": "ferrari", "model": "california", "bat_slug": "ferrari/california", "year_range": "2009-2017"},
    # Ferrari — manual-swap targets (F1 transmission cars)
    "F355": {"make": "ferrari", "model": "f355", "bat_slug": "ferrari/f355", "year_range": "1995-1999"},
    "F355 Spider": {"make": "ferrari", "model": "f355 spider", "bat_slug": "ferrari/f355-spider", "year_range": "1995-1999"},
    "360 Modena": {"make": "ferrari", "model": "360", "bat_slug": "ferrari/360", "year_range": "1999-2005"},
    "360 Spider": {"make": "ferrari", "model": "360 spider", "bat_slug": "ferrari/360-spider", "year_range": "2000-2005"},
    "F430": {"make": "ferrari", "model": "f430", "bat_slug": "ferrari/f430", "year_range": "2005-2009"},
    "F430 Spider": {"make": "ferrari", "model": "f430 spider", "bat_slug": "ferrari/f430-spider", "year_range": "2005-2009"},
    "430 Scuderia": {"make": "ferrari", "model": "430 scuderia", "bat_slug": "ferrari/430-scuderia", "year_range": "2008-2009"},
    "575M": {"make": "ferrari", "model": "575m", "bat_slug": "ferrari/575m-maranello", "year_range": "2002-2006"},
    "550 Maranello": {"make": "ferrari", "model": "550", "bat_slug": "ferrari/550-maranello", "year_range": "1997-2001"},
    "599 GTB": {"make": "ferrari", "model": "599", "bat_slug": "ferrari/599-gtb", "year_range": "2007-2012"},
    "612 Scaglietti": {"make": "ferrari", "model": "612", "bat_slug": "ferrari/612-scaglietti", "year_range": "2004-2011"},
    # Lamborghini
    "Urus": {"make": "lamborghini", "model": "urus", "bat_slug": "lamborghini/urus", "year_range": "2019-2024"},
    "Gallardo": {"make": "lamborghini", "model": "gallardo", "bat_slug": "lamborghini/gallardo", "year_range": "2004-2014"},
    "Gallardo Spyder": {"make": "lamborghini", "model": "gallardo spyder", "bat_slug": "lamborghini/gallardo-spyder", "year_range": "2006-2014"},
    "Murcielago": {"make": "lamborghini", "model": "murcielago", "bat_slug": "lamborghini/murcielago", "year_range": "2002-2010"},
    "Diablo": {"make": "lamborghini", "model": "diablo", "bat_slug": "lamborghini/diablo", "year_range": "1990-2001"},
    "Countach": {"make": "lamborghini", "model": "countach", "bat_slug": "lamborghini/countach", "year_range": "1974-1990"},
    # Porsche
    "GT3": {"make": "porsche", "model": "911 gt3", "bat_slug": "porsche/911-gt3", "year_range": "2004-2024"},
    "GT4": {"make": "porsche", "model": "cayman gt4", "bat_slug": "porsche/cayman-gt4", "year_range": "2016-2024"},
    "GT2 RS": {"make": "porsche", "model": "911 gt2", "bat_slug": "porsche/911-gt2-rs", "year_range": "2011-2024"},
    "911 Turbo": {"make": "porsche", "model": "911 turbo", "bat_slug": "porsche/911-turbo", "year_range": "2001-2024"},
    "911 Turbo S": {"make": "porsche", "model": "911 turbo s", "bat_slug": "porsche/911-turbo-s", "year_range": "2010-2024"},
    "996": {"make": "porsche", "model": "911", "bat_slug": "porsche/996-911", "year_range": "1999-2004"},
    "997": {"make": "porsche", "model": "911", "bat_slug": "porsche/997", "year_range": "2005-2012"},
    "991": {"make": "porsche", "model": "911", "bat_slug": "porsche/991-911", "year_range": "2012-2018"},
    "992": {"make": "porsche", "model": "911", "bat_slug": "porsche/992-911", "year_range": "2019-2026"},
    "Cayman S": {"make": "porsche", "model": "cayman s", "bat_slug": "porsche/cayman-s", "year_range": "2006-2024"},
    # McLaren
    "MP4-12C": {"make": "mclaren", "model": "mp4-12c", "bat_slug": "mclaren/mp4-12c", "year_range": "2012-2014"},
    "650S": {"make": "mclaren", "model": "650s", "bat_slug": "mclaren/650s", "year_range": "2015-2017"},
    "570S": {"make": "mclaren", "model": "570s", "bat_slug": "mclaren/570s", "year_range": "2016-2021"},
    "570GT": {"make": "mclaren", "model": "570gt", "bat_slug": "mclaren/570gt", "year_range": "2017-2020"},
    "600LT": {"make": "mclaren", "model": "600lt", "bat_slug": "mclaren/600lt", "year_range": "2019-2020"},
    "720S": {"make": "mclaren", "model": "720s", "bat_slug": "mclaren/720s", "year_range": "2018-2024"},
    # BMW
    "M3": {"make": "bmw", "model": "m3", "bat_slug": "bmw/m3", "year_range": "2008-2024"},
    "M4": {"make": "bmw", "model": "m4", "bat_slug": "bmw/m4", "year_range": "2015-2024"},
    # Maserati
    "GranTurismo": {"make": "maserati", "model": "granturismo", "bat_slug": "maserati/granturismo", "year_range": "2008-2019"},
    # Aston Martin
    "V8 Vantage": {"make": "aston martin", "model": "v8 vantage", "bat_slug": "aston-martin/v8-vantage", "year_range": "2006-2017"},
    "DB9": {"make": "aston martin", "model": "db9", "bat_slug": "aston-martin/db9", "year_range": "2005-2016"},
}


# Typical mileage ranges for each model class. Used to judge whether a
# listing's mileage is low/average/high for its type, which affects
# whether the "discount" is real or just mileage-justified.
# Format: (average_miles, max_acceptable_miles)
MODEL_MILEAGE_EXPECTATIONS: dict[str, tuple[int, int]] = {
    # Older Ferraris — typically 20-40k miles at this age
    "F355": (30000, 60000),
    "F355 Spider": (30000, 60000),
    "360 Modena": (25000, 50000),
    "360 Spider": (25000, 50000),
    "F430": (20000, 45000),
    "F430 Spider": (20000, 45000),
    "430 Scuderia": (12000, 30000),
    "575M": (25000, 50000),
    "550 Maranello": (30000, 55000),
    "599 GTB": (15000, 40000),
    "612 Scaglietti": (25000, 50000),
    # Modern Ferraris — lower miles expected
    "458": (15000, 35000),
    "458 Spider": (12000, 30000),
    "458 Speciale": (8000, 20000),
    "488": (10000, 25000),
    "488 Spider": (10000, 25000),
    "F12": (10000, 25000),
    "812 Superfast": (5000, 15000),
    "California": (20000, 45000),
    "Portofino": (8000, 20000),
    "Roma": (5000, 15000),
    # Lamborghini
    "Gallardo": (25000, 50000),
    "Gallardo Spyder": (20000, 45000),
    "Murcielago": (15000, 35000),
    "Urus": (15000, 35000),
    "Diablo": (15000, 35000),
    "Countach": (10000, 25000),
    # Porsche
    "GT3": (15000, 35000),
    "GT4": (12000, 30000),
    "GT2 RS": (5000, 15000),
    "911 Turbo": (20000, 45000),
    "911 Turbo S": (15000, 35000),
    "996": (50000, 80000),
    "997": (40000, 70000),
    "991": (35000, 65000),
    "992": (12000, 30000),
    "Cayman S": (30000, 60000),
    # McLaren
    "MP4-12C": (15000, 35000),
    "650S": (12000, 30000),
    "570S": (12000, 30000),
    "570GT": (15000, 35000),
    "600LT": (5000, 15000),
    "720S": (8000, 20000),
    # Others
    "M3": (30000, 60000),
    "M4": (25000, 50000),
    "GranTurismo": (30000, 60000),
    "V8 Vantage": (25000, 50000),
    "DB9": (25000, 50000),
}


@dataclass
class SoldComp:
    """A single sold comparison — price + mileage + year (if known)."""
    price: int
    miles: int  # 0 if unknown
    year: int   # 0 if unknown
    source: str  # "BaT" or "C&B"


@dataclass
class RegressionResult:
    """Coefficients from price = b0 + b1*miles + b2*year regression."""
    intercept: float
    price_per_mile: float
    price_per_year: float
    has_year: bool


@dataclass
class MarketBaseline:
    model: str
    median_sold: int
    num_sales: int
    p25_sold: int
    p75_sold: int
    price_per_mile: float
    price_per_year: float
    avg_comp_miles: int
    avg_comp_year: float
    has_year_regression: bool


@dataclass
class Deal:
    model: str
    listing: Listing
    market_median: int
    discount_pct: float
    mileage_adjusted_discount_pct: float
    score: float


def _parse_miles_from_title(title: str) -> int:
    """Extract mileage from BaT-style titles like '22k-Mile' or '8,400-Mile'."""
    m = re.search(r"([\d,]+)[kK]-[Mm]ile", title)
    if m:
        return int(m.group(1).replace(",", "")) * 1000
    m = re.search(r"([\d,]+)-[Mm]ile", title)
    if m:
        return int(m.group(1).replace(",", ""))
    return 0


def _parse_year_from_title(title: str) -> int:
    """Extract model year from BaT/C&B titles like '2005 Ferrari F430...'
    or '22k-Mile 2005 Ferrari F430...'."""
    m = re.search(r"\b(19[6-9]\d|20[0-2]\d)\s+(?:Ferrari|Lamborghini|Porsche|McLaren|Audi|Mercedes|BMW|Aston|Maserati)", title, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.match(r"(?:No Reserve:\s*)?(\d{4})\s", title)
    if m:
        year = int(m.group(1))
        if 1960 <= year <= 2030:
            return year
    return 0


def _fetch_bat_sold_comps(session: httpx.Client, slug: str) -> list[SoldComp]:
    """Fetch recent sold prices + mileage from BaT model page."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    }
    url = f"https://bringatrailer.com/{slug}/"
    resp = session.get(url, headers=headers, follow_redirects=True)
    if resp.status_code != 200:
        return []

    match = re.search(
        r"var auctionsCompletedInitialData = (\{.*?\});\s*\n",
        resp.text,
        re.DOTALL,
    )
    if not match:
        return []

    data = json.loads(match.group(1))
    items = data.get("items", [])
    comps: list[SoldComp] = []

    for item in items:
        sold_text = item.get("sold_text", "")
        bid = item.get("current_bid", 0)
        title = item.get("title", "")
        if "Sold" in sold_text and bid >= 20000:
            miles = _parse_miles_from_title(title)
            year = _parse_year_from_title(title)
            comps.append(SoldComp(price=bid, miles=miles, year=year, source="BaT"))

    return comps


def _fetch_cab_sold_comps(client, model_name: str) -> list[SoldComp]:
    """Fetch Cars & Bids sold prices via Serper (1 API call per model)."""
    query = f'site:carsandbids.com/auctions "{model_name}" "sold for"'
    try:
        results = client.search(query, num=10)
    except Exception:
        return []

    comps: list[SoldComp] = []
    for r in results:
        if "/auctions/" not in r.link:
            continue
        price_match = re.search(r"Sold for \$([\d,]+)", r.snippet)
        if not price_match:
            continue
        price = int(price_match.group(1).replace(",", ""))
        if price < 20000:
            continue
        miles = _parse_miles_from_title(r.title)
        year = _parse_year_from_title(r.title)
        comps.append(SoldComp(price=price, miles=miles, year=year, source="C&B"))

    return comps


def _ols_2var(data: list[tuple[int, int, int]]) -> RegressionResult:
    """Solve price = b0 + b1*miles + b2*year via normal equations."""
    n = len(data)
    s_x1 = s_x2 = s_y = 0.0
    s_x1x1 = s_x1x2 = s_x2x2 = 0.0
    s_x1y = s_x2y = 0.0
    for price, miles, year in data:
        p, m, yr = float(price), float(miles), float(year)
        s_x1 += m; s_x2 += yr; s_y += p
        s_x1x1 += m * m; s_x1x2 += m * yr; s_x2x2 += yr * yr
        s_x1y += m * p; s_x2y += yr * p

    A = [
        [float(n), s_x1, s_x2, s_y],
        [s_x1, s_x1x1, s_x1x2, s_x1y],
        [s_x2, s_x1x2, s_x2x2, s_x2y],
    ]
    for col in range(3):
        max_row = max(range(col, 3), key=lambda r: abs(A[r][col]))
        A[col], A[max_row] = A[max_row], A[col]
        if abs(A[col][col]) < 1e-12:
            return RegressionResult(0, 0, 0, False)
        for row in range(col + 1, 3):
            factor = A[row][col] / A[col][col]
            for j in range(col, 4):
                A[row][j] -= factor * A[col][j]
    x = [0.0, 0.0, 0.0]
    for i in range(2, -1, -1):
        x[i] = A[i][3]
        for j in range(i + 1, 3):
            x[i] -= A[i][j] * x[j]
        x[i] /= A[i][i]

    return RegressionResult(intercept=x[0], price_per_mile=x[1], price_per_year=x[2], has_year=True)


def _calculate_price_regression(comps: list[SoldComp]) -> RegressionResult:
    """2-variable OLS: price = b0 + b1*miles + b2*year.

    Falls back to 1-variable (miles only) if fewer than 6 comps have
    both miles and year. Returns zeros if insufficient data.
    """
    with_both = [(c.price, c.miles, c.year) for c in comps if c.miles > 0 and c.year > 0]
    if len(with_both) >= 6:
        return _ols_2var(with_both)

    with_miles = [(c.price, c.miles) for c in comps if c.miles > 0]
    if len(with_miles) >= 4:
        n = len(with_miles)
        sum_x = sum(m for _, m in with_miles)
        sum_y = sum(p for p, _ in with_miles)
        sum_xy = sum(p * m for p, m in with_miles)
        sum_x2 = sum(m * m for _, m in with_miles)
        denom = n * sum_x2 - sum_x * sum_x
        if denom != 0:
            slope = (n * sum_xy - sum_x * sum_y) / denom
            return RegressionResult(intercept=0, price_per_mile=slope, price_per_year=0, has_year=False)

    return RegressionResult(intercept=0, price_per_mile=0, price_per_year=0, has_year=False)


def get_market_baselines(models: list[str], include_cab: bool = True) -> dict[str, MarketBaseline]:
    """Build market baselines from BaT + Cars & Bids sold data.

    BaT provides price + mileage (from title parsing). C&B provides
    additional price points (mileage not available from search snippets).
    Combined, this gives a more robust market picture.
    """
    from ..google_search import GoogleCSEClient

    baselines: dict[str, MarketBaseline] = {}
    cab_client = None

    if include_cab:
        try:
            cab_client = GoogleCSEClient(recency="qdr:y")
        except RuntimeError:
            include_cab = False

    with httpx.Client(timeout=20) as session:
        for model in models:
            cfg = MODEL_CONFIG.get(model)
            if not cfg:
                continue

            # BaT comps (free)
            comps = _fetch_bat_sold_comps(session, cfg["bat_slug"])
            time.sleep(0.5)

            # C&B comps (1 Serper query per model)
            if include_cab and cab_client:
                cab_comps = _fetch_cab_sold_comps(cab_client, model)
                comps.extend(cab_comps)
                time.sleep(0.2)

            prices = [c.price for c in comps]
            if len(prices) < 3:
                continue

            prices.sort()
            regression = _calculate_price_regression(comps)
            comps_with_miles = [c for c in comps if c.miles > 0]
            avg_miles = int(statistics.mean([c.miles for c in comps_with_miles])) if comps_with_miles else 0
            comps_with_year = [c for c in comps if c.year > 0]
            avg_year = statistics.mean([c.year for c in comps_with_year]) if comps_with_year else 0.0

            baselines[model] = MarketBaseline(
                model=model,
                median_sold=int(statistics.median(prices)),
                num_sales=len(prices),
                p25_sold=prices[len(prices) // 4],
                p75_sold=prices[3 * len(prices) // 4],
                price_per_mile=round(regression.price_per_mile, 2),
                price_per_year=round(regression.price_per_year, 2),
                avg_comp_miles=avg_miles,
                avg_comp_year=round(avg_year, 1),
                has_year_regression=regression.has_year,
            )

    if cab_client:
        cab_client._client.close()

    return baselines


def _expected_price(baseline: MarketBaseline, miles: int, year: int, clean_title: bool = True) -> float | None:
    """Mileage+year adjusted expected price, or None if no adjustment possible.

    Non-clean title (salvage/rebuilt) cars trade ~35% below clean title
    equivalents, so the expected price is reduced accordingly.
    """
    can_miles = miles > 0 and baseline.price_per_mile != 0 and baseline.avg_comp_miles > 0
    can_year = year > 0 and baseline.price_per_year != 0 and baseline.avg_comp_year > 0
    if not (can_miles or can_year):
        if not clean_title:
            return float(baseline.median_sold) * 0.65
        return None
    expected = float(baseline.median_sold)
    if can_miles:
        expected += baseline.price_per_mile * (miles - baseline.avg_comp_miles)
    if can_year:
        expected += baseline.price_per_year * (year - baseline.avg_comp_year)
    if not clean_title:
        expected *= 0.65
    return max(expected, baseline.p25_sold * 0.7)


def find_deals(
    models: list[str],
    baselines: dict[str, MarketBaseline],
    *,
    min_discount_pct: float = 10.0,
    zip_code: str | None = None,
    radius: int = 100,
    max_days_on_market: int = 180,
) -> list[Deal]:
    """Query MarketCheck for active listings below BaT median, return scored deals."""
    deals: list[Deal] = []

    with MarketCheckClient() as mc:
        for model in models:
            cfg = MODEL_CONFIG.get(model)
            baseline = baselines.get(model)
            if not cfg or not baseline:
                continue

            max_price = int(baseline.median_sold * (1 - min_discount_pct / 100))
            price_range = f"1000-{max_price}"
            avg_miles, max_miles = MODEL_MILEAGE_EXPECTATIONS.get(model, (30000, 60000))

            try:
                listings = mc.search(
                    make=cfg["make"],
                    model=cfg["model"],
                    year_range=cfg.get("year_range"),
                    price_range=price_range,
                    zip_code=zip_code,
                    radius=radius,
                    rows=50,
                    sort_by="price",
                    sort_order="asc",
                )
            except Exception as e:
                print(f"  [error] {model}: {e}", file=sys.stderr)
                continue

            for listing in listings:
                if listing.miles > max_miles:
                    continue
                if max_days_on_market and listing.days_on_market > max_days_on_market:
                    continue

                # Raw discount vs flat median
                discount = (baseline.median_sold - listing.price) / baseline.median_sold * 100

                ep = _expected_price(baseline, listing.miles, listing.year, listing.carfax_clean_title)
                if ep is not None:
                    mileage_adj_discount = (ep - listing.price) / ep * 100
                else:
                    mileage_adj_discount = discount

                if listing.miles > 0:
                    mileage_ratio = listing.miles / avg_miles
                    if mileage_ratio > 1.5:
                        mileage_adj = -10.0
                    elif mileage_ratio > 1.0:
                        mileage_adj = -3.0 * (mileage_ratio - 1.0)
                    elif mileage_ratio < 0.5:
                        mileage_adj = 5.0
                    else:
                        mileage_adj = 2.0 * (1.0 - mileage_ratio)
                else:
                    mileage_adj = 0.0

                dom_bonus = min(listing.days_on_market / 10, 5.0)
                owner_adj = 3.0 if listing.carfax_1_owner else 0.0
                score = mileage_adj_discount + dom_bonus + mileage_adj + owner_adj
                deals.append(Deal(
                    model=model,
                    listing=listing,
                    market_median=baseline.median_sold,
                    discount_pct=round(discount, 1),
                    mileage_adjusted_discount_pct=round(mileage_adj_discount, 1),
                    score=round(score, 1),
                ))

    deals.sort(key=lambda d: d.score, reverse=True)
    return deals


def _is_f1_egear(transmission: str) -> bool | None:
    """Check if a transmission string indicates F1/e-gear.

    Returns True for F1/e-gear, False for confirmed manual, None for unknown.
    Only used for MANUAL_SWAP_MODELS where "Automatic" means F1/e-gear
    (these cars never had torque-converter autos).
    """
    trans_lower = transmission.lower().strip()
    if any(pat in trans_lower for pat in F1_EGEAR_TRANS_PATTERNS):
        return True
    if any(pat in trans_lower for pat in MANUAL_TRANS_PATTERNS):
        if "automated" not in trans_lower:
            return False
    if "automatic" in trans_lower:
        return True
    if not trans_lower or trans_lower in ("other", "—", "-", "n/a"):
        return None
    return None


def find_swap_candidates(
    baselines: dict[str, MarketBaseline],
    *,
    zip_code: str | None = None,
    radius: int = 100,
    max_days_on_market: int = 180,
) -> list[Deal]:
    """Find F1/e-gear cars — manual swap candidates.

    Unlike find_deals(), this doesn't require a discount below median.
    ANY F1/e-gear car is interesting because the swap itself creates the value.
    We still score by price (cheaper = better) and days on market.
    """
    deals: list[Deal] = []
    swap_models = [m for m in MANUAL_SWAP_MODELS if m in baselines]

    with MarketCheckClient() as mc:
        for model in swap_models:
            cfg = MODEL_CONFIG.get(model)
            baseline = baselines.get(model)
            if not cfg or not baseline:
                continue

            avg_miles, max_miles = MODEL_MILEAGE_EXPECTATIONS.get(model, (30000, 60000))

            try:
                listings = mc.search(
                    make=cfg["make"],
                    model=cfg["model"],
                    year_range=cfg.get("year_range"),
                    zip_code=zip_code,
                    radius=radius,
                    rows=50,
                    sort_by="price",
                    sort_order="asc",
                )
            except Exception as e:
                print(f"  [error] {model}: {e}", file=sys.stderr)
                continue

            for listing in listings:
                if not _is_f1_egear(listing.transmission):
                    continue
                if listing.miles > max_miles:
                    continue
                if max_days_on_market and listing.days_on_market > max_days_on_market:
                    continue

                discount = (baseline.median_sold - listing.price) / baseline.median_sold * 100

                ep = _expected_price(baseline, listing.miles, listing.year, listing.carfax_clean_title)
                if ep is not None:
                    mileage_adj_discount = (ep - listing.price) / ep * 100
                else:
                    mileage_adj_discount = discount

                if listing.miles > 0:
                    mileage_ratio = listing.miles / avg_miles
                    if mileage_ratio > 1.5:
                        mileage_adj = -10.0
                    elif mileage_ratio > 1.0:
                        mileage_adj = -3.0 * (mileage_ratio - 1.0)
                    elif mileage_ratio < 0.5:
                        mileage_adj = 5.0
                    else:
                        mileage_adj = 2.0 * (1.0 - mileage_ratio)
                else:
                    mileage_adj = 0.0

                dom_bonus = min(listing.days_on_market / 10, 5.0)
                swap_bonus = 10.0
                owner_adj = 3.0 if listing.carfax_1_owner else 0.0
                score = mileage_adj_discount + dom_bonus + mileage_adj + swap_bonus + owner_adj
                deals.append(Deal(
                    model=model,
                    listing=listing,
                    market_median=baseline.median_sold,
                    discount_pct=round(discount, 1),
                    mileage_adjusted_discount_pct=round(mileage_adj_discount, 1),
                    score=round(score, 1),
                ))

    deals.sort(key=lambda d: d.score, reverse=True)
    return deals


def find_stale_inventory(
    models: list[str],
    baselines: dict[str, MarketBaseline],
    *,
    min_days_on_market: int = 120,
    zip_code: str | None = None,
    radius: int = 100,
) -> list[Deal]:
    """Find cars sitting 120+ days — likely have undisclosed problems.

    Sorted by days on market DESC. Non-clean-title is a bonus here
    (salvage/rebuilt = fixable opportunity). High DOM is the primary signal.
    """
    deals: list[Deal] = []

    with MarketCheckClient() as mc:
        for model in models:
            cfg = MODEL_CONFIG.get(model)
            baseline = baselines.get(model)
            if not cfg or not baseline:
                continue

            avg_miles, max_miles = MODEL_MILEAGE_EXPECTATIONS.get(model, (30000, 60000))

            try:
                listings = mc.search(
                    make=cfg["make"],
                    model=cfg["model"],
                    year_range=cfg.get("year_range"),
                    zip_code=zip_code,
                    radius=radius,
                    rows=50,
                    sort_by="dom",
                    sort_order="desc",
                )
            except Exception as e:
                print(f"  [error] {model}: {e}", file=sys.stderr)
                continue

            for listing in listings:
                if listing.days_on_market < min_days_on_market:
                    continue
                if listing.miles > max_miles:
                    continue

                discount = (baseline.median_sold - listing.price) / baseline.median_sold * 100

                ep = _expected_price(baseline, listing.miles, listing.year, listing.carfax_clean_title)
                if ep is not None:
                    mileage_adj_discount = (ep - listing.price) / ep * 100
                else:
                    mileage_adj_discount = discount

                if listing.miles > 0:
                    mileage_ratio = listing.miles / avg_miles
                    if mileage_ratio > 1.5:
                        mileage_adj = -10.0
                    elif mileage_ratio > 1.0:
                        mileage_adj = -3.0 * (mileage_ratio - 1.0)
                    elif mileage_ratio < 0.5:
                        mileage_adj = 5.0
                    else:
                        mileage_adj = 2.0 * (1.0 - mileage_ratio)
                else:
                    mileage_adj = 0.0

                # Inverted scoring: high DOM and non-clean title are GOOD signals
                dom_bonus = min(listing.days_on_market / 30, 15.0)
                title_adj = 10.0 if not listing.carfax_clean_title else 0.0
                discount_bonus = max(mileage_adj_discount * 0.3, 0)
                score = dom_bonus + title_adj + discount_bonus + mileage_adj
                deals.append(Deal(
                    model=model,
                    listing=listing,
                    market_median=baseline.median_sold,
                    discount_pct=round(discount, 1),
                    mileage_adjusted_discount_pct=round(mileage_adj_discount, 1),
                    score=round(score, 1),
                ))

    deals.sort(key=lambda d: d.score, reverse=True)
    return deals


def _write_csv(deals: list[Deal], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    scraped_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    fieldnames = [
        "scraped_at", "score", "model", "year", "trim", "heading",
        "price", "market_median", "discount_pct", "adj_discount_pct",
        "miles", "miles_vs_avg", "days_on_market",
        "clean_title", "one_owner", "color",
        "transmission", "dealer_name", "dealer_city", "dealer_state",
        "dealer_phone", "url", "vin", "contacted",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for d in deals:
            avg_miles = MODEL_MILEAGE_EXPECTATIONS.get(d.model, (30000, 60000))[0]
            if d.listing.miles > 0:
                miles_label = f"{d.listing.miles / avg_miles:.1f}x avg"
            else:
                miles_label = "unknown"
            writer.writerow({
                "scraped_at": scraped_at,
                "score": d.score,
                "model": d.model,
                "year": d.listing.year,
                "trim": d.listing.trim,
                "heading": d.listing.heading,
                "price": d.listing.price,
                "market_median": d.market_median,
                "discount_pct": d.discount_pct,
                "adj_discount_pct": d.mileage_adjusted_discount_pct,
                "miles": d.listing.miles,
                "miles_vs_avg": miles_label,
                "days_on_market": d.listing.days_on_market,
                "clean_title": "Yes" if d.listing.carfax_clean_title else "No",
                "one_owner": "Yes" if d.listing.carfax_1_owner else "No",
                "color": d.listing.exterior_color,
                "transmission": d.listing.transmission,
                "dealer_name": d.listing.dealer_name,
                "dealer_city": d.listing.dealer_city,
                "dealer_state": d.listing.dealer_state,
                "dealer_phone": d.listing.dealer_phone,
                "url": d.listing.url,
                "vin": d.listing.vin,
                "contacted": "",
            })


def _write_baselines_csv(baselines: dict[str, MarketBaseline], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "model", "median_sold", "num_sales", "p25_sold", "p75_sold",
        "price_per_mile", "price_per_year", "avg_comp_miles", "avg_comp_year",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for name, b in baselines.items():
            writer.writerow({
                "model": name,
                "median_sold": b.median_sold,
                "num_sales": b.num_sales,
                "p25_sold": b.p25_sold,
                "p75_sold": b.p75_sold,
                "price_per_mile": b.price_per_mile,
                "price_per_year": b.price_per_year,
                "avg_comp_miles": b.avg_comp_miles,
                "avg_comp_year": b.avg_comp_year,
            })


def run(
    *,
    models: list[str],
    min_discount: float,
    zip_code: str | None,
    radius: int,
    swap_only: bool,
    stale: bool,
    max_days: int,
    output: Path,
) -> int:
    print(f"Step 1: Building market baselines for {len(models)} models (BaT + Cars & Bids)...")
    baselines = get_market_baselines(models)
    print(f"  Got baselines for {len(baselines)} models:")
    for name, b in baselines.items():
        miles_info = f", avg {b.avg_comp_miles:,}mi" if b.avg_comp_miles else ""
        slope_info = f", ${b.price_per_mile:,.0f}/mi" if b.price_per_mile else ""
        year_info = f", ${b.price_per_year:,.0f}/yr" if b.price_per_year else ""
        print(f"    {name}: median ${b.median_sold:,} ({b.num_sales} sales{miles_info}{slope_info}{year_info})")

    missing = [m for m in models if m not in baselines]
    if missing:
        print(f"  Skipping (insufficient BaT data): {', '.join(missing)}")

    if not baselines:
        print("No baselines available. Cannot compare prices.")
        return 1

    if stale:
        api_calls = len(baselines)
        print(f"\nStep 2: Searching for stale inventory — 120+ days on market ({api_calls} API calls)...")
        if zip_code:
            print(f"  Location: {zip_code}, {radius}mi radius")

        deals = find_stale_inventory(
            list(baselines.keys()),
            baselines,
            zip_code=zip_code,
            radius=radius,
        )
    elif swap_only:
        swap_models_available = [m for m in MANUAL_SWAP_MODELS if m in baselines]
        api_calls = len(swap_models_available)
        print(f"\nStep 2: Searching for F1/e-gear manual-swap candidates ({api_calls} API calls)...")
        print(f"  Targeting: {', '.join(swap_models_available)}")
        if zip_code:
            print(f"  Location: {zip_code}, {radius}mi radius")

        deals = find_swap_candidates(
            baselines,
            zip_code=zip_code,
            radius=radius,
            max_days_on_market=max_days,
        )
    else:
        api_calls = len(baselines)
        print(f"\nStep 2: Querying MarketCheck for underpriced listings ({api_calls} API calls)...")
        print(f"  Filter: >{min_discount}% below BaT median, listed within {max_days} days")
        if zip_code:
            print(f"  Location: {zip_code}, {radius}mi radius")

        deals = find_deals(
            list(baselines.keys()),
            baselines,
            min_discount_pct=min_discount,
            zip_code=zip_code,
            radius=radius,
            max_days_on_market=max_days,
        )

    _write_csv(deals, output)
    baselines_name = output.name.replace("-deals", "-baselines").replace("-swaps", "-baselines").replace("-stale", "-baselines")
    _write_baselines_csv(baselines, output.parent / baselines_name)
    print(f"\nDone: {len(deals)} listings written to {output}.")
    if deals:
        top = deals[0]
        if stale:
            label = "Most stale"
            print(
                f"{label}: {top.listing.year} {top.model} {top.listing.trim} — "
                f"${top.listing.price:,} ({top.listing.days_on_market} days on lot, "
                f"{'non-clean title' if not top.listing.carfax_clean_title else 'clean title'})"
            )
        else:
            label = "Best swap candidate" if swap_only else "Best deal"
            print(
                f"{label}: {top.listing.year} {top.model} {top.listing.trim} — "
                f"${top.listing.price:,} vs ${top.market_median:,} median "
                f"({top.discount_pct}% below market, {top.listing.days_on_market} days on lot)"
            )
            if swap_only:
                print(f"  {len(deals)} F1/e-gear cars found — all are manual-swap candidates")
    return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Find dealer listings priced below BaT market value")
    all_models = list(MODEL_CONFIG.keys())
    p.add_argument(
        "--models", nargs="+",
        default=FOCUS_MODELS,
        help=(
            f"Models to check (default: focus set {', '.join(FOCUS_MODELS)}). "
            f"Available: {', '.join(all_models)}"
        ),
    )
    p.add_argument(
        "--discount", type=float, default=10.0,
        help="Minimum discount %% below BaT median to flag (default: 10)",
    )
    p.add_argument(
        "--zip", type=str, default=None,
        help="ZIP code for location-based search (default: nationwide)",
    )
    p.add_argument(
        "--radius", type=int, default=100,
        help="Search radius in miles from zip (default: 100)",
    )
    p.add_argument(
        "--swap-only", action="store_true",
        help="Only search for F1/e-gear manual-swap candidates (360, F430, Gallardo, etc.)",
    )
    p.add_argument(
        "--stale", action="store_true",
        help="Find stale inventory — cars sitting 120+ days (likely have problems)",
    )
    p.add_argument(
        "--max-days", type=int, default=180,
        help="Max days on market — filter out stale listings (default: 180)",
    )
    p.add_argument(
        "--output", type=Path,
        default=None,
        help="Output CSV path (default: out/YYYY-MM-DD-deals.csv or -swaps.csv)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = _parse_args(argv)
    if args.output:
        output = args.output
    elif args.stale:
        output = Path("out") / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}-stale.csv"
    elif args.swap_only:
        output = Path("out") / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}-swaps.csv"
    else:
        output = Path("out") / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}-deals.csv"

    if args.swap_only:
        # Respect the focus (or any explicit --models), limited to cars where a
        # manual swap actually makes sense.
        models = [m for m in args.models if m in MANUAL_SWAP_MODELS]
    else:
        models = args.models

    try:
        return run(
            models=models,
            min_discount=args.discount,
            zip_code=args.zip,
            radius=args.radius,
            swap_only=args.swap_only,
            stale=args.stale,
            max_days=args.max_days,
            output=output,
        )
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
