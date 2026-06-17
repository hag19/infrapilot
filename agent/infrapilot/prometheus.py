"""Thin read-only Prometheus HTTP API client (instant + range queries)."""
from __future__ import annotations

import time
from typing import Any

import requests


class Prometheus:
    def __init__(self, base_url: str, timeout: float = 15.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def query(self, expr: str) -> dict[str, Any]:
        """Instant query (current value of a PromQL expression)."""
        r = requests.get(
            f"{self.base_url}/api/v1/query",
            params={"query": expr},
            timeout=self.timeout,
        )
        r.raise_for_status()
        return r.json()

    def query_range(
        self, expr: str, minutes: int = 30, step: str = "60s"
    ) -> dict[str, Any]:
        """Range query over the last `minutes` minutes."""
        now = time.time()
        r = requests.get(
            f"{self.base_url}/api/v1/query_range",
            params={
                "query": expr,
                "start": now - minutes * 60,
                "end": now,
                "step": step,
            },
            timeout=self.timeout,
        )
        r.raise_for_status()
        return r.json()
