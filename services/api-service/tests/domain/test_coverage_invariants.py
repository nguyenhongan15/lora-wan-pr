"""Domain invariants cho coverage types.

Theo unit-test-guide.md §3 Tactic 4 — invariants ép qua __post_init__
là loại "hard error" → đúng dùng pytest.raises.
"""

from __future__ import annotations

import pytest

from lora_coverage_api.domain.coverage import (
    Confidence,
    ConfidenceMethod,
    Target,
)


# ── Confidence.score ─────────────────────────────────────────────────────


def test_confidence_accepts_score_at_zero():
    c = Confidence(score=0.0, method=ConfidenceMethod.EMPIRICAL)

    assert c.score == 0.0


def test_confidence_accepts_score_at_one():
    c = Confidence(score=1.0, method=ConfidenceMethod.EMPIRICAL)

    assert c.score == 1.0


@pytest.mark.parametrize("invalid_score", [-0.01, 1.01, -1.0, 2.0])
def test_confidence_rejects_score_outside_unit_interval_when_out_of_range(
    invalid_score: float,
):
    with pytest.raises(ValueError, match="Confidence.score"):
        Confidence(score=invalid_score, method=ConfidenceMethod.EMPIRICAL)


# ── Target.latitude / longitude / spreading_factor ───────────────────────


def test_target_accepts_valid_da_nang_coordinates():
    t = Target(latitude=16.05, longitude=108.2, spreading_factor=7)

    assert t.spreading_factor == 7


@pytest.mark.parametrize("bad_lat", [-90.1, 90.1, -180.0, 180.0])
def test_target_rejects_latitude_when_outside_minus90_to_90(bad_lat: float):
    with pytest.raises(ValueError, match="latitude"):
        Target(latitude=bad_lat, longitude=108.2, spreading_factor=7)


@pytest.mark.parametrize("bad_lng", [-180.01, 180.01, -360.0, 360.0])
def test_target_rejects_longitude_when_outside_minus180_to_180(bad_lng: float):
    with pytest.raises(ValueError, match="longitude"):
        Target(latitude=16.05, longitude=bad_lng, spreading_factor=7)


@pytest.mark.parametrize("bad_sf", [0, 6, 13, 20, -1])
def test_target_rejects_spreading_factor_when_not_in_7_to_12(bad_sf: int):
    with pytest.raises(ValueError, match="SF"):
        Target(latitude=16.05, longitude=108.2, spreading_factor=bad_sf)


@pytest.mark.parametrize("valid_sf", [7, 8, 9, 10, 11, 12])
def test_target_accepts_spreading_factor_when_in_lora_range(valid_sf: int):
    t = Target(latitude=16.05, longitude=108.2, spreading_factor=valid_sf)

    assert t.spreading_factor == valid_sf
