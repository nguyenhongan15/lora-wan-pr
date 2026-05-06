"""In-memory fakes cho AddressCache + GeocodingClient (Nominatim/VietMap/Goong)."""

from __future__ import annotations

from collections.abc import Mapping

from lora_coverage_api.application.address_service import (
    GeocodingClient,
    GeocodingProviderUnavailableError,
)
from lora_coverage_api.application.repositories import AddressCache
from lora_coverage_api.domain.address import AddressLookupResult, GeocodingProvider


class FakeAddressCache(AddressCache):
    def __init__(self, seed: Mapping[str, AddressLookupResult] | None = None) -> None:
        self._store: dict[str, AddressLookupResult] = dict(seed or {})
        self.put_calls: list[tuple[str, AddressLookupResult]] = []

    def get(self, normalized_query: str) -> AddressLookupResult | None:
        return self._store.get(normalized_query)

    def put(self, normalized_query: str, hit: AddressLookupResult) -> None:
        self.put_calls.append((normalized_query, hit))
        self._store.setdefault(normalized_query, hit)


class FakeGeocoder(GeocodingClient):
    """Generic fake — dùng được cho mọi tier (Nominatim/VietMap/Goong).

    Set provider để cascade test biết tier nào thực sự trả hit.
    """

    def __init__(
        self,
        result: AddressLookupResult | None = None,
        raise_unavailable: bool = False,
        provider: GeocodingProvider = GeocodingProvider.NOMINATIM,
    ) -> None:
        self._result = result
        self._raise = raise_unavailable
        self.provider = provider
        self.calls: list[str] = []

    def search(self, query: str) -> AddressLookupResult | None:
        self.calls.append(query)
        if self._raise:
            raise GeocodingProviderUnavailableError("simulated unavailability")
        return self._result


# Back-compat alias — test cũ dùng FakeNominatim.
FakeNominatim = FakeGeocoder
