"""Cascade tests cho AddressResolutionService."""

from __future__ import annotations

from lora_coverage_api.application.address_service import AddressResolutionService
from lora_coverage_api.domain.address import (
    Address,
    AddressLookupResult,
    GeocodingProvider,
)
from lora_coverage_api.domain.errors import AddressLookupErrorCode

from ..fakes.address import FakeAddressCache, FakeGeocoder, FakeNominatim  # noqa: F401

_DA_NANG_HIT = AddressLookupResult(
    latitude=16.0544,
    longitude=108.2022,
    display_name="Đà Nẵng, Việt Nam",
    provider=GeocodingProvider.NOMINATIM,
    confidence=0.8,
)


def test_cache_hit_skips_nominatim() -> None:
    cache = FakeAddressCache(seed={"da nang": _DA_NANG_HIT})
    nom = FakeNominatim()
    svc = AddressResolutionService(cache, nom)

    r = svc.lookup(Address(raw="Đà Nẵng"))
    assert r.is_ok
    assert r.value.display_name == "Đà Nẵng, Việt Nam"
    # Nominatim KHÔNG được gọi khi cache hit.
    assert nom.calls == []


def test_cache_miss_calls_nominatim_and_promotes() -> None:
    cache = FakeAddressCache()
    nom = FakeNominatim(result=_DA_NANG_HIT)
    svc = AddressResolutionService(cache, nom)

    r = svc.lookup(Address(raw="Đà Nẵng"))
    assert r.is_ok
    # Ghi đúng key normalized vào cache.
    assert any(k == "da nang" for k, _ in cache.put_calls)


def test_nominatim_not_found_returns_err() -> None:
    cache = FakeAddressCache()
    nom = FakeNominatim(result=None)
    svc = AddressResolutionService(cache, nom)

    r = svc.lookup(Address(raw="abcdefg-xyz-ne-pas-trouver"))
    assert r.is_err
    assert r.error.code == AddressLookupErrorCode.NOT_FOUND


def test_out_of_region_returns_err_and_does_not_cache() -> None:
    pacific_hit = AddressLookupResult(
        latitude=0,
        longitude=-150,
        display_name="Pacific Ocean",
        provider=GeocodingProvider.NOMINATIM,
    )
    cache = FakeAddressCache()
    nom = FakeNominatim(result=pacific_hit)
    svc = AddressResolutionService(cache, nom)

    r = svc.lookup(Address(raw="middle of pacific"))
    assert r.is_err
    assert r.error.code == AddressLookupErrorCode.OUT_OF_REGION
    # Quan trọng: KHÔNG cache miss-positive.
    assert cache.put_calls == []


def test_provider_unavailable_returns_err() -> None:
    cache = FakeAddressCache()
    nom = FakeNominatim(raise_unavailable=True)
    svc = AddressResolutionService(cache, nom)

    r = svc.lookup(Address(raw="any"))
    assert r.is_err
    assert r.error.code == AddressLookupErrorCode.PROVIDER_UNAVAILABLE


# ── Cascade VietMap/Goong tests ─────────────────────────────────────────


_VIETMAP_HIT = AddressLookupResult(
    latitude=16.0544,
    longitude=108.2022,
    display_name="Đà Nẵng (VietMap)",
    provider=GeocodingProvider.VIETMAP,
    confidence=0.9,
)
_GOONG_HIT = AddressLookupResult(
    latitude=16.0600,
    longitude=108.2100,
    display_name="Đà Nẵng (Goong)",
    provider=GeocodingProvider.GOONG,
    confidence=0.85,
)


def test_nominatim_unavailable_falls_back_to_vietmap() -> None:
    cache = FakeAddressCache()
    nom = FakeNominatim(raise_unavailable=True)
    vm = FakeNominatim(result=_VIETMAP_HIT, provider=GeocodingProvider.VIETMAP)
    svc = AddressResolutionService(cache, nom, fallbacks=(vm,))

    r = svc.lookup(Address(raw="Đà Nẵng"))
    assert r.is_ok
    assert r.value.provider == GeocodingProvider.VIETMAP
    # VietMap hit → cache promoted với provider gốc.
    assert any(hit.provider == GeocodingProvider.VIETMAP for _, hit in cache.put_calls)


def test_nominatim_not_found_falls_through_to_goong() -> None:
    cache = FakeAddressCache()
    nom = FakeNominatim(result=None)  # tier 2 không có data
    vm = FakeNominatim(result=None, provider=GeocodingProvider.VIETMAP)  # tier 3 cũng không
    goong = FakeNominatim(result=_GOONG_HIT, provider=GeocodingProvider.GOONG)
    svc = AddressResolutionService(cache, nom, fallbacks=(vm, goong))

    r = svc.lookup(Address(raw="ngõ hẻm xa xôi"))
    assert r.is_ok
    assert r.value.provider == GeocodingProvider.GOONG
    # Mọi tier đều được thử trước khi return.
    assert nom.calls and vm.calls and goong.calls


def test_all_unavailable_returns_provider_unavailable() -> None:
    cache = FakeAddressCache()
    nom = FakeNominatim(raise_unavailable=True)
    vm = FakeNominatim(raise_unavailable=True, provider=GeocodingProvider.VIETMAP)
    goong = FakeNominatim(raise_unavailable=True, provider=GeocodingProvider.GOONG)
    svc = AddressResolutionService(cache, nom, fallbacks=(vm, goong))

    r = svc.lookup(Address(raw="any"))
    assert r.is_err
    # Tất cả tier raise → PROVIDER_UNAVAILABLE, không phải NOT_FOUND.
    assert r.error.code == AddressLookupErrorCode.PROVIDER_UNAVAILABLE


def test_some_unavailable_some_no_data_returns_not_found() -> None:
    cache = FakeAddressCache()
    nom = FakeNominatim(raise_unavailable=True)  # tier 2 down
    vm = FakeNominatim(result=None, provider=GeocodingProvider.VIETMAP)  # tier 3 không data
    svc = AddressResolutionService(cache, nom, fallbacks=(vm,))

    r = svc.lookup(Address(raw="something nonexistent"))
    assert r.is_err
    # Có ít nhất 1 tier thực sự trả "không có data" → NOT_FOUND đúng nghĩa.
    assert r.error.code == AddressLookupErrorCode.NOT_FOUND


def test_out_of_region_in_fallback_does_not_cache() -> None:
    pacific_via_goong = AddressLookupResult(
        latitude=0,
        longitude=-150,
        display_name="Pacific",
        provider=GeocodingProvider.GOONG,
    )
    cache = FakeAddressCache()
    nom = FakeNominatim(result=None)
    goong = FakeNominatim(result=pacific_via_goong, provider=GeocodingProvider.GOONG)
    svc = AddressResolutionService(cache, nom, fallbacks=(goong,))

    r = svc.lookup(Address(raw="middle of pacific"))
    assert r.is_err
    assert r.error.code == AddressLookupErrorCode.OUT_OF_REGION
    assert cache.put_calls == []
