"""HTTP client cho VietMap geocoding API.

Tier 3 trong cascade — paid VN-first. Chỉ dùng khi `vietmap_api_key` được
cấu hình; không cấu hình → không wire (xem deps.py).

API doc: https://maps.vietmap.vn/docs/map-api/geocoding/
Lưu ý: VietMap geocoding là 2-step:
    1. /api/search/v3?text=… → list of {ref_id, address, ...}
    2. /api/place/v3?refid=…  → {lat, lng, name, ...}

Step 1 không trả lat/lng trực tiếp (chỉ ranking). Phải call step 2 cho
top-1 hit. Nếu step 2 fail/timeout → coi như Unavailable, service cascade
xuống Goong.

Theo rule-design-security.md: timeout cứng, KHÔNG log api_key.
"""

from __future__ import annotations

import httpx

from ..application.address_service import GeocodingProviderUnavailableError
from ..domain.address import AddressLookupResult, GeocodingProvider

_DEFAULT_BASE_URL = "https://maps.vietmap.vn"


class VietmapHttpClient:
    provider = GeocodingProvider.VIETMAP

    def __init__(
        self,
        api_key: str,
        base_url: str = _DEFAULT_BASE_URL,
        timeout_seconds: float = 5.0,
    ) -> None:
        if not api_key:
            raise ValueError("VietmapHttpClient: api_key required")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    def search(self, query: str) -> AddressLookupResult | None:
        # Step 1 — autocomplete để lấy ref_id top-1.
        ref_id = self._search_ref_id(query)
        if ref_id is None:
            return None

        # Step 2 — resolve ref_id → lat/lng + display_name canonical.
        return self._fetch_place(ref_id)

    # ── internals ────────────────────────────────────────────────────────
    def _search_ref_id(self, query: str) -> str | None:
        url = f"{self._base_url}/api/search/v3"
        params = {"apikey": self._api_key, "text": query}
        try:
            resp = httpx.get(url, params=params, timeout=self._timeout)
        except httpx.HTTPError as e:
            raise GeocodingProviderUnavailableError(f"vietmap network: {e}") from e

        if resp.status_code == 429:
            raise GeocodingProviderUnavailableError("vietmap rate-limited (429)")
        if resp.status_code >= 500:
            raise GeocodingProviderUnavailableError(f"vietmap 5xx: {resp.status_code}")
        if resp.status_code == 401 or resp.status_code == 403:
            # Sai key → coi là Unavailable cho service biết rớt sang tier kế.
            # Không trả NOT_FOUND vì sẽ làm hỏng cascade khi VietMap mất key.
            raise GeocodingProviderUnavailableError(f"vietmap auth failed ({resp.status_code})")
        if resp.status_code != 200:
            raise GeocodingProviderUnavailableError(f"vietmap unexpected status {resp.status_code}")

        try:
            data = resp.json()
        except ValueError as e:
            raise GeocodingProviderUnavailableError(f"vietmap non-json: {e}") from e

        if not isinstance(data, list) or not data:
            return None

        first = data[0]
        if not isinstance(first, dict):
            return None
        ref_id = first.get("ref_id")
        if not isinstance(ref_id, str) or not ref_id:
            return None
        return ref_id

    def _fetch_place(self, ref_id: str) -> AddressLookupResult | None:
        url = f"{self._base_url}/api/place/v3"
        params = {"apikey": self._api_key, "refid": ref_id}
        try:
            resp = httpx.get(url, params=params, timeout=self._timeout)
        except httpx.HTTPError as e:
            raise GeocodingProviderUnavailableError(f"vietmap place network: {e}") from e

        if resp.status_code != 200:
            raise GeocodingProviderUnavailableError(f"vietmap place status {resp.status_code}")

        try:
            data = resp.json()
        except ValueError as e:
            raise GeocodingProviderUnavailableError(f"vietmap place non-json: {e}") from e

        if not isinstance(data, dict):
            return None
        try:
            lat = float(data["lat"])
            lng = float(data["lng"])
        except (KeyError, TypeError, ValueError):
            return None
        display = str(data.get("display") or data.get("name") or "").strip()
        if not display:
            display = f"{lat:.5f}, {lng:.5f}"

        return AddressLookupResult(
            latitude=lat,
            longitude=lng,
            display_name=display,
            provider=GeocodingProvider.VIETMAP,
            # VietMap không expose confidence — đặt heuristic 0.9 (cao hơn
            # Nominatim trung bình do chuyên dữ liệu VN).
            confidence=0.9,
        )
