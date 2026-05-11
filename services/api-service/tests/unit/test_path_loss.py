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


def _gateway(
    lat: float = 16.05,
    lon: float = 108.20,
    *,
    antenna_gain_dbi: float = 2.0,
    tx_power_dbm: float = 14.0,
    rx_antenna_gain_dbi: float | None = None,
    rx_sensitivity_dbm: float | None = None,
) -> Gateway:
    return Gateway(
        id=GatewayId(uuid4()),
        code="TST",
        name="test",
        latitude=lat,
        longitude=lon,
        altitude_m=10,
        antenna_height_m=10,
        antenna_gain_dbi=antenna_gain_dbi,
        tx_power_dbm=tx_power_dbm,
        frequency_mhz=923.0,
        rx_antenna_gain_dbi=rx_antenna_gain_dbi,
        rx_sensitivity_dbm=rx_sensitivity_dbm,
    )


def _target(
    lat: float,
    lon: float,
    sf: int = 7,
    *,
    tx_power_dbm: float = 14.0,
    tx_antenna_gain_dbi: float = 2.0,
    rx_antenna_gain_dbi: float = 0.0,
) -> Target:
    return Target(
        latitude=lat,
        longitude=lon,
        spreading_factor=sf,
        frequency_mhz=923.0,
        tx_power_dbm=tx_power_dbm,
        tx_antenna_gain_dbi=tx_antenna_gain_dbi,
        rx_antenna_gain_dbi=rx_antenna_gain_dbi,
    )


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


# ── Bidirectional link budget ─────────────────────────────────────────────


def test_predict_top_level_rssi_equals_downlink_rssi_for_backward_compat() -> None:
    """Top-level rssi/snr giữ nghĩa = DL để client cũ không vỡ."""
    m = Stage1LogDistanceModel("stage1-test")
    p = m.predict(_target(16.06, 108.21), _gateway())

    assert p.rssi_dbm == p.downlink_rssi_dbm
    assert p.snr_db == p.downlink_snr_db


def test_predict_uplink_stronger_when_gateway_tx_lower_than_device() -> None:
    """Gateway TX yếu (10 dBm) + device TX max (14 dBm) → DL yếu hơn UL → bottleneck=downlink."""
    m = Stage1LogDistanceModel("stage1-test")
    gw = _gateway(tx_power_dbm=10.0, antenna_gain_dbi=2.0)
    tgt = _target(16.06, 108.21, sf=7, tx_power_dbm=14.0, tx_antenna_gain_dbi=2.0)

    p = m.predict(tgt, gw)

    assert p.uplink_margin_db > p.downlink_margin_db
    assert p.bottleneck == "downlink"


def test_predict_uplink_weaker_when_device_tx_lower_than_gateway() -> None:
    """Gateway TX cao (27 dBm) + device 14 dBm → UL yếu hơn → bottleneck=uplink."""
    m = Stage1LogDistanceModel("stage1-test")
    gw = _gateway(tx_power_dbm=27.0, antenna_gain_dbi=6.0)
    tgt = _target(16.10, 108.25, sf=10, tx_power_dbm=14.0, tx_antenna_gain_dbi=0.0)

    p = m.predict(tgt, gw)

    assert p.uplink_margin_db < p.downlink_margin_db
    assert p.bottleneck == "uplink"


def test_predict_bottleneck_both_ok_when_balanced_and_strong() -> None:
    """Cự ly gần + Pt/Gt/Gr/sens đối xứng hai chiều → UL≈DL margin & STRONG → both_ok.

    Lưu ý: gateway SF7 sens (-123) tốt hơn device sens (-120) 3 dB; device Gr
    default 0 dBi < gateway Gr 2 dBi. Phải override 2 field này để khử bias 5 dB
    inherent giữa 2 chiều, mới chạm threshold 1 dB.
    """
    m = Stage1LogDistanceModel("stage1-test")
    gw = _gateway(tx_power_dbm=14.0, antenna_gain_dbi=2.0)
    tgt = Target(
        latitude=16.0501,
        longitude=108.2001,
        spreading_factor=7,
        frequency_mhz=923.0,
        tx_power_dbm=14.0,
        tx_antenna_gain_dbi=2.0,
        rx_antenna_gain_dbi=2.0,  # khử asymmetry Gr
        rx_sensitivity_dbm=-123.0,  # match gateway SF7 sens
    )

    p = m.predict(tgt, gw)

    assert p.uplink_status == CoverageStatus.STRONG
    assert p.downlink_status == CoverageStatus.STRONG
    assert p.bottleneck == "both_ok"


def test_predict_coverage_status_takes_worst_of_uplink_and_downlink() -> None:
    """Cự ly xa + device TX rất thấp → UL kém hơn DL nhiều → coverage_status = uplink_status."""
    m = Stage1LogDistanceModel("stage1-test")
    gw = _gateway(tx_power_dbm=27.0, antenna_gain_dbi=8.0)
    tgt = _target(16.20, 108.40, sf=12, tx_power_dbm=-10.0)

    p = m.predict(tgt, gw)

    rank = {
        CoverageStatus.NO_COVERAGE: 0,
        CoverageStatus.WEAK: 1,
        CoverageStatus.MARGINAL: 2,
        CoverageStatus.STRONG: 3,
    }
    assert rank[p.coverage_status] == min(rank[p.uplink_status], rank[p.downlink_status])
    assert p.uplink_status != p.downlink_status  # setup này phải tạo asymmetry rõ ràng


def test_predict_path_loss_is_reciprocal_so_pl_components_match_both_directions() -> None:
    """Reciprocity: rssi_ul - (Pt_dev + Gt_dev + Gr_gw) == rssi_dl - (Pt_gw + Gt_gw + Gr_dev) == -PL."""
    m = Stage1LogDistanceModel("stage1-test")
    gw = _gateway(tx_power_dbm=20.0, antenna_gain_dbi=6.0, rx_antenna_gain_dbi=4.0)
    tgt = _target(
        16.10, 108.25, sf=9, tx_power_dbm=14.0, tx_antenna_gain_dbi=2.0, rx_antenna_gain_dbi=1.0
    )

    p = m.predict(tgt, gw)

    pl_from_ul = (tgt.tx_power_dbm + tgt.tx_antenna_gain_dbi + 4.0) - p.uplink_rssi_dbm
    pl_from_dl = (
        gw.tx_power_dbm + gw.antenna_gain_dbi + tgt.rx_antenna_gain_dbi
    ) - p.downlink_rssi_dbm

    assert pl_from_ul == pytest.approx(pl_from_dl, abs=0.05)


def test_predict_falls_back_gateway_rx_gain_to_tx_gain_when_none() -> None:
    """Gateway.rx_antenna_gain_dbi None → coi như duplex symmetric (= antenna_gain_dbi)."""
    m = Stage1LogDistanceModel("stage1-test")
    gw_none = _gateway(antenna_gain_dbi=8.0, rx_antenna_gain_dbi=None)
    gw_explicit = _gateway(antenna_gain_dbi=8.0, rx_antenna_gain_dbi=8.0)
    tgt = _target(16.10, 108.25, sf=8)

    p_none = m.predict(tgt, gw_none)
    p_explicit = m.predict(tgt, gw_explicit)

    assert p_none.uplink_rssi_dbm == pytest.approx(p_explicit.uplink_rssi_dbm, abs=0.01)
    assert p_none.uplink_margin_db == pytest.approx(p_explicit.uplink_margin_db, abs=0.01)


def test_predict_uses_target_rx_sensitivity_override_for_downlink_margin() -> None:
    """Target.rx_sensitivity_dbm explicit shift DL margin tương ứng so với SF-table fallback."""
    m = Stage1LogDistanceModel("stage1-test")
    tgt_default = _target(16.10, 108.25, sf=7)  # device sens fallback = -120 dBm
    tgt_better = Target(
        latitude=16.10,
        longitude=108.25,
        spreading_factor=7,
        frequency_mhz=923.0,
        tx_power_dbm=14.0,
        tx_antenna_gain_dbi=2.0,
        rx_antenna_gain_dbi=0.0,
        rx_sensitivity_dbm=-130.0,  # 10 dB tốt hơn fallback
    )
    gw = _gateway()

    p_default = m.predict(tgt_default, gw)
    p_better = m.predict(tgt_better, gw)

    # DL margin = rssi - sens; sens tốt hơn 10 dB → margin tốt hơn 10 dB.
    assert p_better.downlink_margin_db == pytest.approx(
        p_default.downlink_margin_db + 10.0, abs=0.05
    )
    # UL không bị ảnh hưởng (chỉ DL tra device sens).
    assert p_better.uplink_margin_db == pytest.approx(p_default.uplink_margin_db, abs=0.01)


def test_predict_uses_gateway_rx_sensitivity_override_for_uplink_margin() -> None:
    """Gateway.rx_sensitivity_dbm explicit shift UL margin tương ứng."""
    m = Stage1LogDistanceModel("stage1-test")
    gw_default = _gateway()  # SX1302 fallback
    gw_better = _gateway(rx_sensitivity_dbm=-140.0)  # tốt hơn ~17 dB so với SF7 default -123
    tgt = _target(16.10, 108.25, sf=7)

    p_default = m.predict(tgt, gw_default)
    p_better = m.predict(tgt, gw_better)

    # margin = rssi - sens; sens tốt hơn 17 dB (-140 vs -123) → UL margin tốt hơn 17 dB.
    assert p_better.uplink_margin_db - p_default.uplink_margin_db == pytest.approx(17.0, abs=0.05)
    # DL margin không đổi (gateway sens chỉ ảnh hưởng UL).
    assert p_better.downlink_margin_db == pytest.approx(p_default.downlink_margin_db, abs=0.01)
