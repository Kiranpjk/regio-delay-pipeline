"""Extract step: fetch departures from the public transport.rest API, or from recorded fixtures.

The API (https://v6.db.transport.rest) is a free community wrapper around Deutsche Bahn data.
Its docs ask clients to stay below 100 requests/minute, so the live client enforces a minimum
interval between requests and sends an identifying User-Agent.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Protocol

import httpx

DEFAULT_BASE_URL = "https://v6.db.transport.rest"
USER_AGENT = "regio-delays/0.1 (portfolio project; github.com/kiranpjk/regio-delay-pipeline)"

# Only products that are valid with a Deutschlandticket: no ICE / IC / EC.
REGIONAL_ONLY = {"nationalExpress": "false", "national": "false"}


class DepartureSource(Protocol):
    def departures(self, station_id: str, duration_min: int = 60) -> dict: ...


class RateLimiter:
    """Blocks so that calls are at least `min_interval` seconds apart."""

    def __init__(self, min_interval: float, clock=time.monotonic, sleep=time.sleep):
        self.min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None

    def wait(self) -> None:
        now = self._clock()
        if self._last is not None:
            remaining = self.min_interval - (now - self._last)
            if remaining > 0:
                self._sleep(remaining)
                now = self._clock()
        self._last = now


class ApiSource:
    """Live client. 1 request/second by default, well under the documented limit."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        min_interval: float = 1.0,
        client: httpx.Client | None = None,
        retries: int = 3,
    ):
        self.base_url = base_url.rstrip("/")
        self.limiter = RateLimiter(min_interval)
        self.client = client or httpx.Client(timeout=20, headers={"User-Agent": USER_AGENT})
        self.retries = retries

    def departures(self, station_id: str, duration_min: int = 60) -> dict:
        params = {"duration": str(duration_min), "remarks": "false", **REGIONAL_ONLY}
        url = f"{self.base_url}/stops/{station_id}/departures"
        for attempt in range(1, self.retries + 1):
            self.limiter.wait()
            resp = self.client.get(url, params=params)
            if resp.status_code in (429, 500, 502, 503) and attempt < self.retries:
                time.sleep(2**attempt)  # back off; never hammer the service
                continue
            resp.raise_for_status()
            return resp.json()
        raise RuntimeError("unreachable")


class FixtureSource:
    """Reads `<fixture_dir>/<station_id>*.json` files that were saved from the API."""

    def __init__(self, fixture_dir: Path):
        self.fixture_dir = Path(fixture_dir)

    def departures(self, station_id: str, duration_min: int = 60) -> dict:
        merged: list[dict] = []
        files = sorted(self.fixture_dir.glob(f"{station_id}*.json"))
        if not files:
            raise FileNotFoundError(f"no fixture for station {station_id} in {self.fixture_dir}")
        for f in files:
            merged.extend(json.loads(f.read_text(encoding="utf-8"))["departures"])
        return {"departures": merged}
