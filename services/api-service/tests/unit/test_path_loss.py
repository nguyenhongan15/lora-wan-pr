"""Unit tests cho Stage1LogDistanceModel — pure-math, không cần DB."""

from __future__ import annotations

from uuid import uuid4

import pytest

from lora_coverage_api.application.path_loss import Stage1LogDistanceModel
from lora_coverage_api.domain.coverage import (
    ConfidenceMethod,
    CoverageStatus,
    Gateway,
    GatewayId,
    Target,
)


def _gateway(lat: float = 16.05, lon: float = 108.20) -> Gateway:
    return Gateway(
        id=GatewayId(uuid4()),
        code="TST",
        name="test",
        latitude=lat,
        longitude=lon,
        altitude_m=10,
        antenna_height_m=10,
        antenna_gain_dbi=2.0,
        tx_power_dbm=14.0,
        frequency_mhz=923.0,
    )


def _target(lat: float, lon: float, sf: int = 7) -> Target:
    return Target(latitude=lat, longitude=lon, spreading_factor=sf, frequency_mhz=923.0)


def test_predict_at_close_range_is_strong() -> None:
    m = Stage1LogDistanceModel("stage1-test")
    p = m.predict(_target(16.0501, 108.2001), _gateway())
    assert p.coverage_status in (CoverageStatus.STRONG, CoverageStatus.MARGINAL)
    assert p.rssi_dbm > -100
    assert p.confidence.method is ConfidenceMethod.EMPIRICAL
    assert 0.0 <= p.confidence.score <= 1.0


def test_predict_at_far_range_degrades() -> None:
    m = Stage1LogDistanceModel("stage1-test")
    p = m.predict(_target(16.5, 108.7), _gateway())  # ~50+ km
    assert p.rssi_dbm < -100
    assert p.confidence.score < 0.5


def test_predict_serving_gateway_id_is_gateway_id() -> None:
    m = Stage1LogDistanceModel("stage1-test")
    gw = _gateway()
    p = m.predict(_target(16.05, 108.20), gw)
    assert p.serving_gateway_id == gw.id


def test_predict_includes_model_version() -> None:
    m = Stage1LogDistanceModel("stage1-loglike-v0.1.0")
    p = m.predict(_target(16.05, 108.20), _gateway())
    assert p.model_version == "stage1-loglike-v0.1.0"


def test_target_validates_latitude_range() -> None:
    with pytest.raises(ValueError, match="latitude"):
        Target(latitude=91.0, longitude=0.0, spreading_factor=7)


def test_target_validates_spreading_factor() -> None:
    with pytest.raises(ValueError, match="SF"):
        Target(latitude=0.0, longitude=0.0, spreading_factor=6)
