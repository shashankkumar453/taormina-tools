"""Thin wrapper around the Serper.dev Google Search API.

Serper returns Google search results via a simple JSON API.
Free tier: 2,500 queries/month, no credit card required.
Docs: https://serper.dev/docs
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Iterator

import httpx


SERPER_ENDPOINT = "https://google.serper.dev/search"


@dataclass(frozen=True)
class SearchResult:
    title: str
    link: str
    snippet: str


class GoogleCSEClient:
    """Synchronous client backed by Serper.dev.

    Kept the class name for backwards compatibility with forum_scrape.py.
    Each `search()` call = one Serper API query.
    Free tier: 2,500 queries/month.
    """

    def __init__(
        self,
        api_key: str | None = None,
        cx: str | None = None,
        request_delay_seconds: float = 0.2,
        timeout_seconds: float = 20.0,
        recency: str = "qdr:m",
    ) -> None:
        self.api_key = api_key or os.environ.get("SERPER_API_KEY", "")
        if not self.api_key:
            raise RuntimeError(
                "SERPER_API_KEY must be set (get one free at https://serper.dev)"
            )
        self.request_delay_seconds = request_delay_seconds
        self.timeout_seconds = timeout_seconds
        self.recency = recency
        self._client = httpx.Client(timeout=timeout_seconds)

    def __enter__(self) -> GoogleCSEClient:
        return self

    def __exit__(self, *_: object) -> None:
        self._client.close()

    def search(self, query: str, num: int = 10) -> list[SearchResult]:
        """Run one search query, return up to `num` results (max 10 per call)."""
        headers = {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "q": query,
            "num": min(num, 10),
            "tbs": self.recency,
        }
        resp = self._client.post(SERPER_ENDPOINT, headers=headers, json=payload)
        time.sleep(self.request_delay_seconds)

        if resp.status_code == 429:
            raise RuntimeError(
                "Serper returned 429 — rate limited or monthly quota exceeded."
            )
        resp.raise_for_status()

        data = resp.json()
        items = data.get("organic", [])
        return [
            SearchResult(
                title=item.get("title", ""),
                link=item.get("link", ""),
                snippet=item.get("snippet", ""),
            )
            for item in items
        ]

    def search_many(
        self, queries: list[str], num: int = 10
    ) -> Iterator[tuple[str, list[SearchResult]]]:
        """Yield (query, results) pairs for a batch of queries."""
        for q in queries:
            yield q, self.search(q, num=num)
