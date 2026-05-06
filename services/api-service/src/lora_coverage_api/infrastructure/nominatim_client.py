"""HTTP client cho Nominatim (OpenStreetMap geocoding).

Tier 2 trong geocoding cascade. Free, nhưng RATE-LIMITED 1 req/sec
theo TOS (https://operations.osmfoundation.org/policies/nominatim/).
Trong production: chạy self-hosted Nominatim (docker) khi traffic > vài req/giây.

`User-Agent` BẮT BUỘC theo TOS — không gửi sẽ bị block.
"""

from __future__ import annotations

import time
from threading import Lock
from typing import Any

import httpx

from ..application.address_service import NominatimUnavailable
from ..domain.address import AddressLookupResult, GeocodingProvider

_DEFAULT_BASE_URL = "https://nominatim.openstreetmap.org"
_DEFAULT_USER_AGENT = "lora-coverage-platform/0.2 (https://github.com/...)"

# 1 req/sec global (theo TOS). Áp dụng kể cả khi nhiều thread.
_MIN_INTERVAL_SEC = 1.05
_lock = Lock()
_last_request_at: float = 0.0


def _throttle() -> None:
    """Block tối đa _MIN_INTERVAL_SEC giữa 2 request liên tiếp.

    Toàn cục cho mọi instance — TOS Nominatim tính theo IP, không theo client.
    """
    global _last_request_at
    with _lock:
        now = time.monotonic()
        delay = _MIN_INTERVAL_SEC - (now - _last_request_at)
        if delay > 0:
            time.sleep(delay)
        _last_request_at = time.monotonic()


class NominatimHttpClient:
    """Sync httpx client. Sync vì nằm trong endpoint sync; async hoá khi cần.

    Theo rule-design-security.md: timeout cứng (không infinite),
    User-Agent identifiable, bias countrycodes=vn.
    """

    def __init__(
        self,
        base_url: str = _DEFAULT_BASE_URL,
        user_agent: str = _DEFAULT_USER_AGENT,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {"User-Agent": user_agent, "Accept": "application/json"}
        self._timeout = timeout_seconds

    def search(self, query: str) -> AddressLookupResult | None:
        _throttle()

        params: dict[str, str | int] = {
            "q": query,
            "format": "jsonv2",
            "limit": 1,
            "addressdetails": 0,
            "countrycodes": "vn",  # bias VN; Nominatim trả VN-first
        }
        url = f"{self._base_url}/search"

        try:
            resp = httpx.get(
                url, params=params, headers=self._headers, timeout=self._timeout
            )
        except httpx.HTTPError as e:
            raise NominatimUnavailable(f"network error: {e}") from e

        if resp.status_code == 429:
            raise NominatimUnavailable("rate-limited (429)")
        if resp.status_code >= 500:
            raise NominatimUnavailable(f"server error {resp.status_code}")
        if resp.status_code != 200:
            raise NominatimUnavailable(f"unexpected status {resp.status_code}")

        try:
            data = resp.json()
        except ValueError as e:
            raise NominatimUnavailable(f"non-JSON response: {e}") from e

        if not isinstance(data, list) or not data:
            return None

        return self._parse_first_hit(data[0])

    @staticmethod
    def _parse_first_hit(hit: dict[str, Any]) -> AddressLookupResult | None:
        try:
            lat = float(hit["lat"])
            lon = float(hit["lon"])
        except (KeyError, TypeError, ValueError):
            return None
        display = str(hit.get("display_name") or "").strip()
        if not display:
            return None
        # Nominatim trả "importance" ∈ [0, ~1.0] — coi như confidence.
        try:
            importance = float(hit.get("importance") or 0.5)
        except (TypeError, ValueError):
            importance = 0.5
        confidence = max(0.0, min(1.0, importance))
        return AddressLookupResult(
            latitude=lat,
            longitude=lon,
            display_name=display,
            provider=GeocodingProvider.NOMINATIM,
            confidence=confidence,
        )
