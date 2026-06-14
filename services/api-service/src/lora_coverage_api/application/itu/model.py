"""Stage 1: path-loss qua ITU-R P.1812 + P.2108 (qua backend Protocol).

Class Stage1ItuModel implement `PathLossModel` Protocol. Caller
(CoverageQueryService, Stage 2 orchestrator) chỉ thấy interface chung.

Deep module (Ousterhout Ch 4): interface 1 method `predict(target, gateway)`;
behind có DEM sampling, terrain diffraction, clutter loss, link-budget UL/DL,
SF recommendation, bottleneck resolution. Tất cả ẩn.

Lý do Stage 1 *vẫn* sống ở application layer (không phải infra) dù gọi DEM:
DEM I/O đã ẩn sau `Stage1PhysicsBackend` Protocol — application chỉ thấy
"cho geometry → trả dB". I/O thật nằm trong `infrastructure/itu/`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ...domain.coverage import (
    Confidence,
    ConfidenceMethod,
    Gateway,
    Prediction,
    Target,
    TerminalEnvironment,
)
from ..path_loss import (
    DEFAULT_NOISE_FLOOR_DBM,
    DEVICE_SENSITIVITY_DBM_125KHZ,
    GW_SENSITIVITY_DBM_125KHZ,
    NOISE_FLOOR_DBM_125KHZ,
    SF_SNR_LIMITS_DB,
    SUBURBAN_PROFILE,
    EnvironmentProfile,
    compute_link_budget,
    estimate_ber,
    estimate_jitter_ms,
    estimate_pdr,
    recommend_sf,
    resolve_gateway_rx_gain,
    resolve_sensitivity,
    status_worse_of,
    time_on_air_ms,
)
from .backend import GeoPoint, LinkGeometry, Stage1PhysicsBackend

# Anten device mặc định (m AGL). 1.5 m = device cầm tay / gắn xe / mote
# ground-level — assumption chuẩn của P.2108 (low terminal in clutter).
# Override qua Settings nếu deploy domain khác (vd sensor trên mái).
_DEFAULT_DEVICE_ANTENNA_HEIGHT_M = 1.5

# Mapping environment → ITU-R P.2109 probability percentile (traditional bldg).
# 50% = median "indoor" (sàn 1, có cửa sổ); 90% = "sâu trong nhà" (tầng trong,
# tường gạch dày). Outdoor = 0 BEL → skip P.2109.
_ENV_PROBABILITY_PERCENT: dict[TerminalEnvironment, float] = {
    "outdoor": 0.0,
    "indoor": 50.0,
    "indoor_deep": 90.0,
}


@dataclass(frozen=True, slots=True)
class Stage1ItuModel:
    """Stage 1 path loss qua ITU-R P.1812 + P.2108 (basic transmission loss
    qua backend) cộng link-budget UL/DL bidirectional.

    What:
      - predict(target, gateway) → Prediction (same shape as PathLossModel).
        UL = device→gateway, DL = gateway→device. coverage_status = worst-of.
    Hidden:
      - Backend trả 1 con số PL (đã gộp P.1812 + P.2108 clutter).
      - antenna height device = 1.5 m AGL (config override).
      - sigma cho Confidence.aleatoric lấy từ env_profile.shadow_fading_std_db.
    Failure mode:
      - SF invalid raise tại Target boundary, không lọt vào đây.
      - DEM coverage thiếu → backend raise, bubble lên HTTP 5xx (ops bug).

    Frozen dataclass: model không thay đổi sau construction; share-thread an toàn.
    """

    model_version: str
    backend: Stage1PhysicsBackend
    env_profile: EnvironmentProfile = SUBURBAN_PROFILE
    device_antenna_height_m: float = _DEFAULT_DEVICE_ANTENNA_HEIGHT_M

    def predict(self, target: Target, gateway: Gateway) -> Prediction:
        sf = target.spreading_factor

        link = LinkGeometry(
            tx=GeoPoint(gateway.latitude, gateway.longitude),
            rx=GeoPoint(target.latitude, target.longitude),
            tx_antenna_height_m=gateway.antenna_height_m,
            rx_antenna_height_m=self.device_antenna_height_m,
            freq_mhz=target.frequency_mhz,
        )
        pl_db = self.backend.basic_transmission_loss_db(link)

        # Building entry loss (ITU-R P.2109) — đối xứng 2 chiều, cộng thẳng vào
        # PL. Outdoor → skip; backend không bị gọi nên test FakeBackend không
        # cần stub method này khi env="outdoor".
        prob_pct = _ENV_PROBABILITY_PERCENT[target.environment]
        if prob_pct > 0.0:
            bel_db = self.backend.building_entry_loss_db(target.frequency_mhz, prob_pct)
            pl_db += bel_db

        d_km = _haversine_km(target.latitude, target.longitude, gateway.latitude, gateway.longitude)

        gw_rx_gain = resolve_gateway_rx_gain(gateway)
        gw_sens = resolve_sensitivity(gateway.rx_sensitivity_dbm, GW_SENSITIVITY_DBM_125KHZ, sf)
        dev_sens = resolve_sensitivity(target.rx_sensitivity_dbm, DEVICE_SENSITIVITY_DBM_125KHZ, sf)

        # UL: noise floor per-gateway (interference-dominated). Fallback
        # DEFAULT_NOISE_FLOOR_DBM (~-104) khi gateway chưa calibrate.
        # DL: device-side NF chưa đo, vẫn giữ thermal -117. Khi có DL telemetry
        # ổn định, mới điều chỉnh.
        ul_noise_floor = (
            gateway.noise_floor_dbm
            if gateway.noise_floor_dbm is not None
            else DEFAULT_NOISE_FLOOR_DBM
        )

        ul = compute_link_budget(
            direction="uplink",
            pl_db=pl_db,
            tx_power_dbm=target.tx_power_dbm,
            tx_gain_dbi=target.tx_antenna_gain_dbi,
            rx_gain_dbi=gw_rx_gain,
            rx_sensitivity_dbm=gw_sens,
            sf=sf,
            noise_floor_dbm=ul_noise_floor,
        )
        dl = compute_link_budget(
            direction="downlink",
            pl_db=pl_db,
            tx_power_dbm=gateway.tx_power_dbm,
            tx_gain_dbi=gateway.antenna_gain_dbi,
            rx_gain_dbi=target.rx_antenna_gain_dbi,
            rx_sensitivity_dbm=dev_sens,
            sf=sf,
            noise_floor_dbm=NOISE_FLOOR_DBM_125KHZ,
        )

        coverage_status = status_worse_of(ul.status, dl.status)
        worst_snr = ul.snr_db if ul.margin_db <= dl.margin_db else dl.snr_db

        # Confidence heuristic 1 / (1 + d/30) — distance lớn vẫn giảm confidence
        # nhưng chậm (P.1812 fit terrain, suy biến chậm theo khoảng cách). Tuned
        # lỏng cho v0.
        score = max(0.1, 1.0 / (1.0 + d_km / 30.0))
        sigma = self.env_profile.shadow_fading_std_db

        # Signal-quality (FE "Dự đoán điểm"): margin SNR-only (không gộp sens
        # margin) — PDR/BER là hàm của SNR vs SF demod threshold, không phụ
        # thuộc front-end sensitivity (đã được tách qua status classify).
        sf_limit = SF_SNR_LIMITS_DB[sf]
        worst_snr_margin = min(ul.snr_db - sf_limit, dl.snr_db - sf_limit)
        pdr = estimate_pdr(worst_snr_margin)
        ber = estimate_ber(worst_snr_margin)
        toa_ms = time_on_air_ms(sf, bw_hz=125_000)
        jitter_ms = estimate_jitter_ms(toa_ms)

        return Prediction(
            rssi_dbm=round(dl.rssi_dbm, 2),
            snr_db=round(dl.snr_db, 2),
            coverage_status=coverage_status,
            serving_gateway_id=gateway.id,
            confidence=Confidence(
                score=round(score, 3),
                method=ConfidenceMethod.PHYSICS,
                epistemic_variance_db2=0.0,
                aleatoric_variance_db2=sigma * sigma,
            ),
            model_version=self.model_version,
            recommended_sf=recommend_sf(worst_snr),
            uplink_rssi_dbm=round(ul.rssi_dbm, 2),
            uplink_snr_db=round(ul.snr_db, 2),
            uplink_margin_db=round(ul.margin_db, 2),
            uplink_status=ul.status,
            downlink_rssi_dbm=round(dl.rssi_dbm, 2),
            downlink_snr_db=round(dl.snr_db, 2),
            downlink_margin_db=round(dl.margin_db, 2),
            downlink_status=dl.status,
            path_loss_db=round(pl_db, 2),
            distance_to_serving_gateway_km=round(d_km, 3),
            pdr=round(pdr, 4),
            ber=ber,
            fer=round(1.0 - pdr, 4),
            bandwidth_hz=125_000,
            time_on_air_ms=round(toa_ms, 2),
            jitter_ms=round(jitter_ms, 2),
            shadow_fading_sigma_db=sigma,
            uplink_noise_floor_dbm=ul_noise_floor,
            downlink_noise_floor_dbm=NOISE_FLOOR_DBM_125KHZ,
            environment=target.environment,
            tx_power_dbm=target.tx_power_dbm,
            frequency_mhz=target.frequency_mhz,
            spreading_factor=sf,
        )


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Khoảng cách great-circle (km). Chỉ dùng cho Confidence score, không
    cho path-loss (backend tự lo)."""
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
