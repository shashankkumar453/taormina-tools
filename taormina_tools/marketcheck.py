"""Thin wrapper around the MarketCheck API for dealer inventory search.

Free tier: 500 API calls/month, 5 requests/second.
Docs: https://docs.marketcheck.com
Signup: https://universe.marketcheck.com
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

import httpx


BASE_URL = "https://api.marketcheck.com/v2"


@dataclass(frozen=True)
class Listing:
    vin: str
    year: int
    make: str
    model: str
    trim: str
    price: int
    miles: int
    days_on_market: int
    dealer_name: str
    dealer_city: str
    dealer_state: str
    dealer_phone: str
    url: str
    transmission: str
    exterior_color: str
    carfax_1_owner: bool
    carfax_clean_title: bool
    heading: str


class MarketCheckClient:
    """Synchronous client for MarketCheck's active inventory endpoint."""

    def __init__(
        self,
        api_key: str | None = None,
        request_delay_seconds: float = 0.25,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.api_key = api_key or os.environ.get("MARKETCHECK_API_KEY", "")
        if not self.api_key:
            raise RuntimeError(
                "MARKETCHECK_API_KEY must be set (get one free at https://universe.marketcheck.com)"
            )
        self.request_delay_seconds = request_delay_seconds
        self._client = httpx.Client(timeout=timeout_seconds)

    def __enter__(self) -> MarketCheckClient:
        return self

    def __exit__(self, *_: object) -> None:
        self._client.close()

    def search(
        self,
        make: str,
        model: str,
        *,
        year_range: str | None = None,
        price_range: str | None = None,
        miles_range: str | None = None,
        zip_code: str | None = None,
        radius: int = 100,
        rows: int = 50,
        start: int = 0,
        sort_by: str = "price",
        sort_order: str = "asc",
    ) -> list[Listing]:
        """Search active dealer inventory. Each call = 1 API credit."""
        params: dict[str, str | int] = {
            "api_key": self.api_key,
            "car_type": "used",
            "make": make,
            "model": model,
            "rows": rows,
            "start": start,
            "sort_by": sort_by,
            "sort_order": sort_order,
        }
        if year_range:
            params["year_range"] = year_range
        if price_range:
            params["price_range"] = price_range
        if miles_range:
            params["miles_range"] = miles_range
        if zip_code:
            params["zip"] = zip_code
            params["radius"] = radius

        resp = self._client.get(f"{BASE_URL}/search/car/active", params=params)
        time.sleep(self.request_delay_seconds)

        if resp.status_code == 429:
            raise RuntimeError(
                "MarketCheck returned 429 — rate limited or monthly quota exceeded."
            )
        resp.raise_for_status()

        data = resp.json()
        listings_raw = data.get("listings", [])
        results: list[Listing] = []

        for item in listings_raw:
            build = item.get("build", {})
            dealer = item.get("dealer", {})
            price = item.get("price")
            if not price:
                continue
            results.append(Listing(
                vin=item.get("vin", ""),
                year=build.get("year", 0),
                make=build.get("make", ""),
                model=build.get("model", ""),
                trim=build.get("trim", ""),
                price=int(price),
                miles=item.get("miles", 0) or 0,
                days_on_market=item.get("dom", 0) or item.get("dom_active", 0) or 0,
                dealer_name=dealer.get("name", ""),
                dealer_city=dealer.get("city", ""),
                dealer_state=dealer.get("state", ""),
                dealer_phone=dealer.get("phone", ""),
                url=item.get("vdp_url", ""),
                transmission=build.get("transmission", ""),
                exterior_color=item.get("exterior_color", ""),
                carfax_1_owner=bool(item.get("carfax_1_owner", False)),
                carfax_clean_title=bool(item.get("carfax_clean_title", False)),
                heading=item.get("heading", ""),
            ))

        return results

    def search_all_pages(
        self,
        make: str,
        model: str,
        *,
        max_pages: int = 3,
        **kwargs,
    ) -> list[Listing]:
        """Paginate through results (up to max_pages × 50 rows). Each page = 1 API credit."""
        all_listings: list[Listing] = []
        for page in range(max_pages):
            results = self.search(make, model, start=page * 50, rows=50, **kwargs)
            all_listings.extend(results)
            if len(results) < 50:
                break
        return all_listings
