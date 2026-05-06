"""HTTP client cho Goong geocoding API.

Tier 4 trong cascade — paid VN-first, alt cho VietMap. Chỉ wire khi
`goong_api_key` được cấu hình.

API doc: https://docs.goong.io/rest/guide/#geocoding
Endpoint: GET https://rsapi.goong.io/Geocode?address=…&api_key=…
Response shape:
    {
        "status": "OK",
        "results": [{
            "formatted_address": "...",
            "geometry": {"location": {"lat": …, "lng": …}},
            "place_id": "...",
        }]
    }

Khác VietMap: 1-step (lat/lng có sẵn trong /Geocode response).

Theo rule-design-security.md: timeout cứng, KHÔNG log api_key.
"""

from __future__ import annotations

import httpx

from ..application.address_service import GeocodingProviderUnavailableError
from ..domain.address import AddressLookupResult, GeocodingProvider

_DEFAULT_BASE_URL = "https://rsapi.goong.io"


class GoongHttpClient:
    provider = GeocodingProvider.GOONG

    def __init__(
        self,
        api_key: str,
        base_url: str = _DEFAULT_BASE_URL,
        timeout_seconds: float = 5.0,
    ) -> None:
        if not api_key:
            raise ValueError("GoongHttpClient: api_key required")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    def search(self, query: str) -> AddressLookupResult | None:
        url = f"{self._base_url}/Geocode"
        params = {"api_key": self._api_key, "address": query}
        try:
            resp = httpx.get(url, params=params, timeout=self._timeout)
        except httpx.HTTPError as e:
            raise GeocodingProviderUnavailableError(f"goong network: {e}") from e

        if resp.status_code == 429:
            raise GeocodingProviderUnavailableError("goong rate-limited (429)")
        if resp.status_code in (401, 403):
            raise GeocodingProviderUnavailableError(f"goong auth failed ({resp.status_code})")
        if resp.status_code >= 500:
            raise GeocodingProviderUnavailableError(f"goong 5xx: {resp.status_code}")
        if resp.status_code != 200:
            raise GeocodingProviderUnavailableError(f"goong unexpected status {resp.status_code}")

        try:
            data = resp.json()
        except ValueError as e:
            raise GeocodingProviderUnavailableError(f"goong non-json: {e}") from e

        if not isinstance(data, dict):
            return None

        # Goong dùng convention "status" giống Google. Status không OK = no hit.
        status = data.get("status")
        results = data.get("results")
        if status not in ("OK", None) or not isinstance(results, list) or not results:
            return None

        first = results[0]
        if not isinstance(first, dict):
            return None
        try:
            geom = first["geometry"]["location"]
            lat = float(geom["lat"])
            lng = float(geom["lng"])
        except (KeyError, TypeError, ValueError):
            return None

        display = str(first.get("formatted_address") or "").strip()
        if not display:
            display = f"{lat:.5f}, {lng:.5f}"

        return AddressLookupResult(
            latitude=lat,
            longitude=lng,
            display_name=display,
            provider=GeocodingProvider.GOONG,
            # Goong không trả confidence trực tiếp — đặt 0.85 (thấp hơn VietMap
            # do dataset thường thưa hơn ngoài đô thị lớn).
            confidence=0.85,
        )
