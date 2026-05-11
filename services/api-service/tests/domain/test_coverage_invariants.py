"""Domain invariants cho coverage types.

Theo unit-test-guide.md §3 Tactic 4 — invariants ép qua __post_init__
là loại "hard error" → đúng dùng pytest.raises.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from lora_coverage_api.domain.coverage import (
    AS923_DEVICE_TX_POWER_CAP_DBM,
    Confidence,
    ConfidenceMethod,
    Gateway,
    GatewayId,
    Prediction,
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
    with pytest.raises(ValueError, match=r"Confidence\.score"):
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


# ── Target.tx_power_dbm AS923-2 cap ─────────────────────────────────────


def test_target_accepts_tx_power_at_as923_cap():
    t = Target(
        latitude=16.05,
        longitude=108.2,
        spreading_factor=7,
        tx_power_dbm=AS923_DEVICE_TX_POWER_CAP_DBM,
    )

    assert t.tx_power_dbm == AS923_DEVICE_TX_POWER_CAP_DBM


@pytest.mark.parametrize("over_cap", [14.01, 17.0, 20.0, 27.0])
def test_target_rejects_tx_power_when_above_as923_cap(over_cap: float):
    with pytest.raises(ValueError, match="AS923"):
        Target(latitude=16.05, longitude=108.2, spreading_factor=7, tx_power_dbm=over_cap)


# ── Target.rx_sensitivity_dbm range ─────────────────────────────────────


def test_target_accepts_rx_sensitivity_when_none():
    t = Target(latitude=16.05, longitude=108.2, spreading_factor=7, rx_sensitivity_dbm=None)

    assert t.rx_sensitivity_dbm is None


@pytest.mark.parametrize("bad_sens", [-150.01, -49.99, 0.0, -200.0])
def test_target_rejects_rx_sensitivity_when_outside_minus150_to_minus50(bad_sens: float):
    with pytest.raises(ValueError, match="rx_sensitivity_dbm"):
        Target(
            latitude=16.05,
            longitude=108.2,
            spreading_factor=7,
            rx_sensitivity_dbm=bad_sens,
        )


# ── Gateway.rx_antenna_gain_dbi / rx_sensitivity_dbm ────────────────────


def _gw(**overrides) -> Gateway:
    base = {
        "id": GatewayId(uuid4()),
        "code": "TST",
        "name": "t",
        "latitude": 16.05,
        "longitude": 108.2,
        "altitude_m": 10.0,
        "antenna_height_m": 10.0,
        "antenna_gain_dbi": 2.0,
        "tx_power_dbm": 14.0,
        "frequency_mhz": 923.0,
    }
    base.update(overrides)
    return Gateway(**base)


def test_gateway_accepts_rx_antenna_gain_when_none():
    g = _gw(rx_antenna_gain_dbi=None)

    assert g.rx_antenna_gain_dbi is None


@pytest.mark.parametrize("bad_gain", [-10.01, 30.01, -50.0, 100.0])
def test_gateway_rejects_rx_antenna_gain_when_outside_minus10_to_30(bad_gain: float):
    with pytest.raises(ValueError, match="rx_antenna_gain_dbi"):
        _gw(rx_antenna_gain_dbi=bad_gain)


@pytest.mark.parametrize("bad_sens", [-150.01, -49.99, 0.0, -200.0])
def test_gateway_rejects_rx_sensitivity_when_outside_minus150_to_minus50(bad_sens: float):
    with pytest.raises(ValueError, match="rx_sensitivity_dbm"):
        _gw(rx_sensitivity_dbm=bad_sens)


# ── Prediction.bottleneck enum ──────────────────────────────────────────


def _pred(**overrides) -> Prediction:
    # Real CoverageStatus import inline to keep helper local.
    from lora_coverage_api.domain.coverage import CoverageStatus

    base = {
        "rssi_dbm": -90.0,
        "snr_db": 10.0,
        "coverage_status": CoverageStatus.STRONG,
        "serving_gateway_id": None,
        "confidence": Confidence(score=0.5, method=ConfidenceMethod.EMPIRICAL),
        "model_version": "t",
        "recommended_sf": 7,
    }
    base.update(overrides)
    return Prediction(**base)


@pytest.mark.parametrize("bad_bottleneck", ["both", "ul", "dl", "", "UPLINK"])
def test_prediction_rejects_invalid_bottleneck(bad_bottleneck: str):
    with pytest.raises(ValueError, match="bottleneck"):
        _pred(bottleneck=bad_bottleneck)


@pytest.mark.parametrize("ok_bottleneck", ["uplink", "downlink", "both_ok"])
def test_prediction_accepts_valid_bottleneck_literals(ok_bottleneck: str):
    p = _pred(bottleneck=ok_bottleneck)

    assert p.bottleneck == ok_bottleneck
