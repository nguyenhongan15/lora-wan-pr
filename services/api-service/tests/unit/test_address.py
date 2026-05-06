"""Domain tests cho Address + AddressLookupResult + normalize_query."""

from __future__ import annotations

import pytest

from lora_coverage_api.domain.address import (
    Address,
    AddressLookupResult,
    GeocodingProvider,
    normalize_query,
)


def test_normalize_strips_diacritics_and_lowercases() -> None:
    assert normalize_query("Đà Nẵng") == "da nang"
    assert normalize_query("Số 1 Lý Thường Kiệt") == "so 1 ly thuong kiet"


def test_normalize_collapses_whitespace() -> None:
    assert normalize_query("  hai\tchâu \n  ") == "hai chau"


def test_address_rejects_empty() -> None:
    with pytest.raises(ValueError):
        Address(raw="")
    with pytest.raises(ValueError):
        Address(raw="   ")


def test_address_rejects_too_long() -> None:
    with pytest.raises(ValueError):
        Address(raw="x" * 501)


def test_address_normalized_property() -> None:
    a = Address(raw="Đà Nẵng")
    assert a.normalized == "da nang"


def test_lookup_result_validates_lat_lon() -> None:
    with pytest.raises(ValueError):
        AddressLookupResult(
            latitude=999,
            longitude=0,
            display_name="x",
            provider=GeocodingProvider.NOMINATIM,
        )


def test_lookup_result_in_vietnam() -> None:
    da_nang = AddressLookupResult(
        latitude=16.05,
        longitude=108.2,
        display_name="Đà Nẵng",
        provider=GeocodingProvider.NOMINATIM,
    )
    assert da_nang.is_in_vietnam

    pacific = AddressLookupResult(
        latitude=0,
        longitude=-150,
        display_name="Pacific",
        provider=GeocodingProvider.NOMINATIM,
    )
    assert not pacific.is_in_vietnam
