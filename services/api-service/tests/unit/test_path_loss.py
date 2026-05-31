"""Unit tests cho Stage1ItuModel — dùng FakeBackend, không cần DEM/crc-covlib.

Stage1ItuModel = link-budget + bidirectional logic + Confidence wiring; backend
trả PL number. Test này verify link-budget contracts (reciprocity, bottleneck,
sensitivity overrides). Test backend thật (crc-covlib) là smoke test riêng,
chạy với DEM data — không thuộc unit scope.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from uuid import uuid4

import pytest

from lora_coverage_api.application.itu.backend import LinkGeometry
from lora_coverage_api.application.itu.model import Stage1ItuModel
from lora_coverage_api.domain.coverage import (
    ConfidenceMethod,
    CoverageStatus,
    Gateway,
    GatewayId,
    Target,
)


@dataclass(frozen=True, slots=True)
class _FakeBackend:
    """Deterministic PL = free-space + n · 10·log10(d/d0) excess.

    Đủ realism cho test link-budget (PL monotone tăng theo distance) mà không
    cần DEM. n=3 ~ suburban; trả 1 con số tương đương ITU stack output.
    """

    model_version: str = "fake-physics-v0"
    n: float = 3.0

    def basic_transmission_loss_db(self, link: LinkGeometry) -> float:
        d_km = _haversine_km(
            link.tx.latitude, link.tx.longitude, link.rx.latitude, link.rx.longitude
        )
        d = max(d_km, 0.001)
        free_space = 32.45 + 20 * math.log10(d) + 20 * math.log10(link.freq_mhz)
        excess = 10 * (self.n - 2) * math.log10(d / 0.1) if d > 0.1 else 0.0
        return free_space + excess

    def building_entry_loss_db(self, freq_mhz: float, probability_percent: float) -> float:
        """Simplified BEL: traditional bldg ~14 dB @ 50%, ~25 dB @ 90%.

        Linear interp đủ cho test contract (indoor adds loss, indoor_deep >>
        indoor); contract test thật của P.2109 chạy với crc-covlib backend.
        """
        return 14.0 + (probability_percent - 50.0) * (25.0 - 14.0) / (90.0 - 50.0)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _model(version: str = "stage1-test") -> Stage1ItuModel:
    return Stage1ItuModel(model_version=version, backend=_FakeBackend())


def _gateway(
    lat: float = 16.05,
    lon: float = 108.20,
    *,
    antenna_gain_dbi: float = 2.0,
    tx_power_dbm: float = 14.0,
    rx_antenna_gain_dbi: float | None = None,
    rx_sensitivity_dbm: float | None = None,
    noise_floor_dbm: float | None = None,
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
        noise_floor_dbm=noise_floor_dbm,
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
    m = _model()
    p = m.predict(_target(16.0501, 108.2001), _gateway())
    assert p.coverage_status in (CoverageStatus.STRONG, CoverageStatus.MARGINAL)
    assert p.rssi_dbm > -100
    assert p.confidence.method is ConfidenceMethod.PHYSICS
    assert 0.0 <= p.confidence.score <= 1.0


def test_predict_at_far_range_degrades() -> None:
    m = _model()
    p = m.predict(_target(16.5, 108.7), _gateway())  # ~50+ km
    assert p.rssi_dbm < -100
    assert p.confidence.score < 0.7  # Confidence decay theo distance


def test_predict_serving_gateway_id_is_gateway_id() -> None:
    m = _model()
    gw = _gateway()
    p = m.predict(_target(16.05, 108.20), gw)
    assert p.serving_gateway_id == gw.id


def test_predict_includes_model_version() -> None:
    m = _model("stage1-itu-p1812-v0.1.0")
    p = m.predict(_target(16.05, 108.20), _gateway())
    assert p.model_version == "stage1-itu-p1812-v0.1.0"


def test_predict_confidence_aleatoric_variance_from_env_profile() -> None:
    """Sigma từ env_profile → variance_db2 = σ²."""
    from lora_coverage_api.application.path_loss import SUBURBAN_PROFILE

    m = _model()
    p = m.predict(_target(16.05, 108.20), _gateway())
    expected = SUBURBAN_PROFILE.shadow_fading_std_db**2
    assert p.confidence.aleatoric_variance_db2 == pytest.approx(expected, abs=0.01)


def test_target_validates_latitude_range() -> None:
    with pytest.raises(ValueError, match="latitude"):
        Target(latitude=91.0, longitude=0.0, spreading_factor=7)


def test_target_validates_spreading_factor() -> None:
    with pytest.raises(ValueError, match="SF"):
        Target(latitude=0.0, longitude=0.0, spreading_factor=6)


# ── Bidirectional link budget ─────────────────────────────────────────────


def test_predict_top_level_rssi_equals_downlink_rssi_for_backward_compat() -> None:
    """Top-level rssi/snr giữ nghĩa = DL để client cũ không vỡ."""
    m = _model()
    p = m.predict(_target(16.06, 108.21), _gateway())

    assert p.rssi_dbm == p.downlink_rssi_dbm
    assert p.snr_db == p.downlink_snr_db


def test_predict_uplink_stronger_when_gateway_tx_lower_than_device() -> None:
    """Gateway TX yếu (10 dBm) + device TX max (14 dBm) → DL yếu hơn UL → bottleneck=downlink.

    noise_floor_dbm=-117 (= DL thermal) để UL và DL chia sẻ NF — chỉ còn TX
    asymmetry tạo chênh margin. Default NF=-104 cho UL sẽ làm SNR-bound siết
    UL trước, lẫn lộn 2 nguyên nhân (TX vs NF asymmetry).
    """
    m = _model()
    gw = _gateway(tx_power_dbm=10.0, antenna_gain_dbi=2.0, noise_floor_dbm=-117.0)
    tgt = _target(16.06, 108.21, sf=7, tx_power_dbm=14.0, tx_antenna_gain_dbi=2.0)

    p = m.predict(tgt, gw)

    assert p.uplink_margin_db > p.downlink_margin_db
    assert p.bottleneck == "downlink"


def test_predict_uplink_weaker_when_device_tx_lower_than_gateway() -> None:
    """Gateway TX cao (27 dBm) + device 14 dBm → UL yếu hơn → bottleneck=uplink."""
    m = _model()
    gw = _gateway(tx_power_dbm=27.0, antenna_gain_dbi=6.0)
    tgt = _target(16.10, 108.25, sf=10, tx_power_dbm=14.0, tx_antenna_gain_dbi=0.0)

    p = m.predict(tgt, gw)

    assert p.uplink_margin_db < p.downlink_margin_db
    assert p.bottleneck == "uplink"


def test_predict_bottleneck_both_ok_when_balanced_and_strong() -> None:
    """Cự ly gần + Pt/Gt/Gr/sens/NF đối xứng hai chiều → UL≈DL margin & STRONG → both_ok.

    noise_floor_dbm=-117 để UL share NF với DL (thermal). Mặc định UL fallback
    -104 sẽ làm UL margin (SNR-bound) thấp hơn DL → flip thành "uplink".
    """
    m = _model()
    gw = _gateway(tx_power_dbm=14.0, antenna_gain_dbi=2.0, noise_floor_dbm=-117.0)
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
    m = _model()
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
    assert p.uplink_status != p.downlink_status


def test_predict_path_loss_is_reciprocal_so_pl_components_match_both_directions() -> None:
    """Reciprocity: rssi_ul - (Pt_dev + Gt_dev + Gr_gw) == rssi_dl - (Pt_gw + Gt_gw + Gr_dev) == -PL."""
    m = _model()
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
    m = _model()
    gw_none = _gateway(antenna_gain_dbi=8.0, rx_antenna_gain_dbi=None)
    gw_explicit = _gateway(antenna_gain_dbi=8.0, rx_antenna_gain_dbi=8.0)
    tgt = _target(16.10, 108.25, sf=8)

    p_none = m.predict(tgt, gw_none)
    p_explicit = m.predict(tgt, gw_explicit)

    assert p_none.uplink_rssi_dbm == pytest.approx(p_explicit.uplink_rssi_dbm, abs=0.01)
    assert p_none.uplink_margin_db == pytest.approx(p_explicit.uplink_margin_db, abs=0.01)


def test_predict_uses_target_rx_sensitivity_override_for_downlink_margin() -> None:
    """Target.rx_sensitivity_dbm explicit shift DL margin tương ứng so với SF-table fallback.

    DL NF hardcoded -117 (thermal) trong Stage1ItuModel → SF7 effective floor =
    NF + SF_limit = -124.5. Override -124 (4 dB tốt hơn fallback -120) vẫn nằm
    trong sens-bound regime → margin tăng đúng +4 dB. Ngoài giới hạn này
    (vd -130) sẽ bị SNR clip — đó là physical realism, không phải bug wiring.
    """
    m = _model()
    tgt_default = _target(16.10, 108.25, sf=7)  # device sens fallback = -120 dBm
    tgt_better = Target(
        latitude=16.10,
        longitude=108.25,
        spreading_factor=7,
        frequency_mhz=923.0,
        tx_power_dbm=14.0,
        tx_antenna_gain_dbi=2.0,
        rx_antenna_gain_dbi=0.0,
        rx_sensitivity_dbm=-124.0,  # 4 dB tốt hơn fallback, vẫn sens-bound
    )
    gw = _gateway()

    p_default = m.predict(tgt_default, gw)
    p_better = m.predict(tgt_better, gw)

    assert p_better.downlink_margin_db == pytest.approx(
        p_default.downlink_margin_db + 4.0, abs=0.05
    )
    assert p_better.uplink_margin_db == pytest.approx(p_default.uplink_margin_db, abs=0.01)


# ── Indoor / building entry loss (ITU-R P.2109) ───────────────────────────


def test_predict_indoor_reduces_rssi_compared_to_outdoor() -> None:
    """environment=indoor cộng BEL P.2109 → cả UL và DL RSSI giảm so với outdoor."""
    m = _model()
    gw = _gateway()
    tgt_out = _target(16.06, 108.21, sf=7)
    tgt_in = Target(
        latitude=16.06,
        longitude=108.21,
        spreading_factor=7,
        frequency_mhz=923.0,
        tx_power_dbm=14.0,
        tx_antenna_gain_dbi=2.0,
        rx_antenna_gain_dbi=0.0,
        environment="indoor",
    )

    p_out = m.predict(tgt_out, gw)
    p_in = m.predict(tgt_in, gw)

    # FakeBackend trả BEL=14 dB @ 50% → cả 2 chiều giảm ~14 dB.
    assert p_in.downlink_rssi_dbm == pytest.approx(p_out.downlink_rssi_dbm - 14.0, abs=0.05)
    assert p_in.uplink_rssi_dbm == pytest.approx(p_out.uplink_rssi_dbm - 14.0, abs=0.05)


def test_predict_indoor_deep_loses_more_than_indoor() -> None:
    """indoor_deep = 90% percentile P.2109 > indoor (50%) → RSSI thấp hơn nhiều."""
    m = _model()
    gw = _gateway()
    common = {
        "latitude": 16.06,
        "longitude": 108.21,
        "spreading_factor": 7,
        "frequency_mhz": 923.0,
        "tx_power_dbm": 14.0,
        "tx_antenna_gain_dbi": 2.0,
        "rx_antenna_gain_dbi": 0.0,
    }
    p_indoor = m.predict(Target(**common, environment="indoor"), gw)
    p_deep = m.predict(Target(**common, environment="indoor_deep"), gw)

    assert p_deep.downlink_rssi_dbm < p_indoor.downlink_rssi_dbm
    # 90% (25 dB) - 50% (14 dB) = 11 dB diff theo FakeBackend.
    assert p_indoor.downlink_rssi_dbm - p_deep.downlink_rssi_dbm == pytest.approx(11.0, abs=0.05)


def test_predict_outdoor_does_not_call_bel() -> None:
    """environment=outdoor → backend.building_entry_loss_db không được gọi.

    Mock counting để verify; outdoor flow phải skip BEL call để tránh cost của
    P.2109 lookup khi không cần.
    """
    calls = {"bel": 0}

    @dataclass(frozen=True, slots=True)
    class _CountingBackend:
        model_version: str = "counting"

        def basic_transmission_loss_db(self, link: LinkGeometry) -> float:
            return 100.0

        def building_entry_loss_db(self, freq_mhz: float, probability_percent: float) -> float:
            # Mutate enclosed dict (frozen dataclass cấm setattr nhưng dict OK).
            calls["bel"] += 1
            return 14.0

    m = Stage1ItuModel(model_version="test", backend=_CountingBackend())
    m.predict(_target(16.06, 108.21), _gateway())
    assert calls["bel"] == 0


def test_predict_uses_gateway_rx_sensitivity_override_for_uplink_margin() -> None:
    """Gateway.rx_sensitivity_dbm explicit shift UL margin tương ứng.

    noise_floor_dbm=-130 (quietest allowed bởi domain CHECK [-130, -80]) để
    SF7 effective floor = NF + SF_limit = -137.5. Override -137 (14 dB tốt
    hơn fallback -123) vẫn nằm trong sens-bound regime, diff = +14 dB chứng
    minh wiring đi đúng. Với NF default -104 (urban interference-dominated),
    datasheet sens đã snr-bound → override không tạo margin gain — đó là
    physical realism, integration test sẽ phủ.
    """
    m = _model()
    gw_default = _gateway(noise_floor_dbm=-130.0)
    gw_better = _gateway(noise_floor_dbm=-130.0, rx_sensitivity_dbm=-137.0)
    tgt = _target(16.10, 108.25, sf=7)

    p_default = m.predict(tgt, gw_default)
    p_better = m.predict(tgt, gw_better)

    assert p_better.uplink_margin_db - p_default.uplink_margin_db == pytest.approx(14.0, abs=0.05)
    assert p_better.downlink_margin_db == pytest.approx(p_default.downlink_margin_db, abs=0.01)
