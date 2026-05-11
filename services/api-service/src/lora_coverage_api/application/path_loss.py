"""Path loss models (Stage 1 in v0).

Pure math — không I/O, không infra. Sống ở application layer vì là business logic.

Stage 1: log-distance / Friis hybrid.
  PL(d) = Friis(d) + 10·(n-2)·log10(d/d0)  với d > d0
        = Friis(d)                          với d ≤ d0
  d0 = 100 m (outdoor micro-cell convention, IEEE 802.16).
  Friis(d) = 32.45 + 20·log10(d_km) + 20·log10(f_MHz).
  Exponent n theo EnvironmentProfile (urban/suburban/rural).

Bidirectional link budget:
  PL(d) tính 1 lần (radio reciprocity). Áp Friis cả 2 chiều:
    UL: RSSI_gw  = P_dev_tx + G_dev_tx + G_gw_rx - PL  (so với gateway sensitivity)
    DL: RSSI_dev = P_gw_tx  + G_gw_tx  + G_dev_rx - PL (so với device sensitivity)
  Top-level rssi_dbm/snr_db = downlink (backward compat). coverage_status =
  worst-of(UL, DL). Bottleneck = direction có margin nhỏ hơn (thresh 1 dB).

Khi Stage 2+ ra đời, model sẽ chuyển sang ml-service riêng. Interface giữ nguyên.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Protocol

from ..domain.coverage import (
    Confidence,
    ConfidenceMethod,
    CoverageStatus,
    Gateway,
    LinkBottleneck,
    Prediction,
    Target,
)

# ── Constants (LoRa AS923-2 conservative defaults) ─────────────────────────
NOISE_FLOOR_DBM_125KHZ = -117.0  # -174 + 10·log10(125e3) + NF(6dB)
SF_SNR_LIMITS_DB: dict[int, float] = {
    7: -7.5,
    8: -10.0,
    9: -12.5,
    10: -15.0,
    11: -17.5,
    12: -20.0,
}
PATH_LOSS_EXPONENT_SUBURBAN = 3.0
SHADOW_FADING_STD_DB = 6.0  # σ log-normal shadow fading (suburban baseline)

# Gateway RX sensitivity per SF @ 125 kHz BW (Semtech SX1302 datasheet).
# Dùng cho UL link budget khi Gateway.rx_sensitivity_dbm is None.
GW_SENSITIVITY_DBM_125KHZ: dict[int, float] = {
    7: -123.0,
    8: -126.0,
    9: -129.0,
    10: -132.0,
    11: -134.5,
    12: -137.0,
}

# Device RX sensitivity per SF @ 125 kHz BW (Semtech SX1276 datasheet).
# Frontend RF tệ hơn GW ~3 dB do BOM rẻ. Dùng cho DL khi Target.rx_sensitivity_dbm is None.
DEVICE_SENSITIVITY_DBM_125KHZ: dict[int, float] = {
    7: -120.0,
    8: -123.0,
    9: -126.0,
    10: -129.0,
    11: -131.5,
    12: -134.0,
}

# Status ordering theo "tốt → xấu" (cao = tốt). StrEnum dùng so sánh string
# alphabetic → SAI (marginal < no_coverage). Bảng explicit này là source of truth.
_STATUS_RANK: dict[CoverageStatus, int] = {
    CoverageStatus.NO_COVERAGE: 0,
    CoverageStatus.WEAK: 1,
    CoverageStatus.MARGINAL: 2,
    CoverageStatus.STRONG: 3,
}

# Ngưỡng dB chênh margin để coi là "cân bằng" giữa UL và DL.
_BOTTLENECK_TIE_THRESHOLD_DB = 1.0

LinkDirection = Literal["uplink", "downlink"]


# ── Environment profile (12F III: config qua env) ────────────────────────
@dataclass(frozen=True, slots=True)
class EnvironmentProfile:
    """Bundle 2 hằng vật lý đi cùng nhau theo môi trường.

    What: name + path_loss_exponent + shadow_fading_std_db cho 1 môi trường.
    Why bundle: exponent và σ luôn được chọn cùng nhau cho 1 environment;
        tách rời = 2 env var dễ lệch (urban exponent + rural σ → vô nghĩa).
    """

    name: str
    path_loss_exponent: float
    shadow_fading_std_db: float


URBAN_PROFILE = EnvironmentProfile(name="urban", path_loss_exponent=3.5, shadow_fading_std_db=8.0)
SUBURBAN_PROFILE = EnvironmentProfile(
    name="suburban",
    path_loss_exponent=PATH_LOSS_EXPONENT_SUBURBAN,
    shadow_fading_std_db=SHADOW_FADING_STD_DB,
)
RURAL_PROFILE = EnvironmentProfile(name="rural", path_loss_exponent=2.5, shadow_fading_std_db=4.0)

_PROFILES: dict[str, EnvironmentProfile] = {
    p.name: p for p in (URBAN_PROFILE, SUBURBAN_PROFILE, RURAL_PROFILE)
}


def resolve_environment_profile(name: str) -> EnvironmentProfile:
    """Map env string → EnvironmentProfile. Allowlist; raise nếu không khớp.

    Boundary input → fail-fast là đúng (rule-security: allowlist validation).
    """
    try:
        return _PROFILES[name.lower()]
    except KeyError:
        raise ValueError(
            f"unknown environment profile: {name!r}; expected one of {sorted(_PROFILES)}"
        ) from None


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Khoảng cách great-circle (km). Dùng được cho mọi phép tính trên Trái Đất."""
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _free_space_pl_db(distance_km: float, freq_mhz: float) -> float:
    """Friis free-space path loss. d_km, f_MHz."""
    if distance_km <= 0:
        return 0.0
    # PL = 32.45 + 20·log10(d_km) + 20·log10(f_MHz)
    return 32.45 + 20.0 * math.log10(distance_km) + 20.0 * math.log10(freq_mhz)


def _classify(rssi_dbm: float, snr_db: float, sf: int) -> CoverageStatus:
    sf_limit = SF_SNR_LIMITS_DB[sf]
    if rssi_dbm >= -100.0 and snr_db >= 5.0:
        return CoverageStatus.STRONG
    if snr_db >= sf_limit and rssi_dbm >= -120.0:
        return CoverageStatus.MARGINAL if snr_db < 5.0 else CoverageStatus.STRONG
    if snr_db >= SF_SNR_LIMITS_DB[12]:
        return CoverageStatus.WEAK
    return CoverageStatus.NO_COVERAGE


def _status_worse_of(a: CoverageStatus, b: CoverageStatus) -> CoverageStatus:
    """Trả status tệ hơn theo _STATUS_RANK (NO_COVERAGE worst, STRONG best)."""
    return a if _STATUS_RANK[a] <= _STATUS_RANK[b] else b


# 3 dB margin trên SF limit để đảm bảo decode tin cậy (LoRa SNR có jitter).
_SF_MARGIN_DB = 3.0


def _recommend_sf(snr_db: float) -> int:
    """SF nhỏ nhất vẫn decode được với 3 dB margin.

    Theo business-logic.md §4.2 — Layer 2 trả "recommended_sf" cho engineer
    biết nên cấu hình LoRaWAN MAC như thế nào. Không trả SF=7 mặc định khi
    điều kiện thực tế đòi hỏi SF cao hơn — đó là điểm cốt lõi của khuyến nghị.
    """
    for sf in (7, 8, 9, 10, 11, 12):
        if snr_db >= SF_SNR_LIMITS_DB[sf] + _SF_MARGIN_DB:
            return sf
    return 12  # Beyond SF12 limit — vẫn report SF12 (caller xử lý NO_COVERAGE).


def _compute_path_loss(
    target: Target, gateway: Gateway, env_profile: EnvironmentProfile
) -> tuple[float, float]:
    """PL_db + d_km. Pure math, reciprocal — dùng chung cho UL và DL."""
    d_km = _haversine_km(target.latitude, target.longitude, gateway.latitude, gateway.longitude)
    d_km_eff = max(d_km, 0.001)
    pl_fs_db = _free_space_pl_db(d_km_eff, target.frequency_mhz)
    d0_km = 0.1
    exponent = env_profile.path_loss_exponent
    excess = 10.0 * (exponent - 2.0) * math.log10(d_km_eff / d0_km) if d_km_eff > d0_km else 0.0
    return pl_fs_db + excess, d_km


def _resolve_gateway_rx_gain(gateway: Gateway) -> float:
    """None = duplex symmetric (= antenna_gain_dbi). Resolution tại app layer."""
    return (
        gateway.antenna_gain_dbi
        if gateway.rx_antenna_gain_dbi is None
        else gateway.rx_antenna_gain_dbi
    )


def _resolve_sensitivity(
    provided: float | None, defaults_table: dict[int, float], sf: int
) -> float:
    """None → tra SF table. Boundary nhỏ — dataclass-or-default fallback."""
    return defaults_table[sf] if provided is None else provided


@dataclass(frozen=True, slots=True)
class _LinkBudget:
    direction: LinkDirection
    rssi_dbm: float
    snr_db: float
    margin_db: float
    status: CoverageStatus


def _compute_link_budget(
    direction: LinkDirection,
    pl_db: float,
    tx_power_dbm: float,
    tx_gain_dbi: float,
    rx_gain_dbi: float,
    rx_sensitivity_dbm: float,
    sf: int,
) -> _LinkBudget:
    """Friis: Pr = Pt + Gt + Gr - PL. SNR = Pr - noise_floor.

    Caveat v0: dùng cùng NOISE_FLOOR_DBM_125KHZ cho cả 2 chiều. Thực tế device
    side NF có thể khác (~3 dB) — Stage 2 sẽ refine khi có DL telemetry.
    """
    rssi_dbm = tx_power_dbm + tx_gain_dbi + rx_gain_dbi - pl_db
    snr_db = rssi_dbm - NOISE_FLOOR_DBM_125KHZ
    margin_db = rssi_dbm - rx_sensitivity_dbm
    status = _classify(rssi_dbm, snr_db, sf)
    return _LinkBudget(
        direction=direction,
        rssi_dbm=rssi_dbm,
        snr_db=snr_db,
        margin_db=margin_db,
        status=status,
    )


def _resolve_bottleneck(ul: _LinkBudget, dl: _LinkBudget) -> LinkBottleneck:
    """Bottleneck = chiều có margin nhỏ hơn. "both_ok" khi cân bằng và đều STRONG."""
    if (
        abs(ul.margin_db - dl.margin_db) <= _BOTTLENECK_TIE_THRESHOLD_DB
        and ul.status == CoverageStatus.STRONG
        and dl.status == CoverageStatus.STRONG
    ):
        return "both_ok"
    return "uplink" if ul.margin_db <= dl.margin_db else "downlink"


class PathLossModel(Protocol):
    """Tất cả model qua các Stage chia sẻ interface này."""

    model_version: str

    def predict(self, target: Target, gateway: Gateway) -> Prediction: ...


class Stage1LogDistanceModel:
    """Empirical log-distance — không cần training data.

    What: predict(target, gateway) → Prediction theo Friis + log-distance excess
        cho cả UL và DL. coverage_status = worst-of(UL, DL). Top-level
        rssi_dbm/snr_db = DL (backward compat).
    Hidden: công thức Friis, exponent theo profile, shadow fading σ², SF margin,
        sensitivity SF table fallback, bottleneck resolution.
    Failure mode: không có — pure math; SF không hợp lệ raise tại Target boundary.
    """

    def __init__(
        self,
        model_version: str,
        env_profile: EnvironmentProfile = SUBURBAN_PROFILE,
    ) -> None:
        self.model_version = model_version
        self._env_profile = env_profile

    def predict(self, target: Target, gateway: Gateway) -> Prediction:
        sf = target.spreading_factor
        pl_db, d_km = _compute_path_loss(target, gateway, self._env_profile)

        gw_rx_gain = _resolve_gateway_rx_gain(gateway)
        gw_sens = _resolve_sensitivity(gateway.rx_sensitivity_dbm, GW_SENSITIVITY_DBM_125KHZ, sf)
        dev_sens = _resolve_sensitivity(
            target.rx_sensitivity_dbm, DEVICE_SENSITIVITY_DBM_125KHZ, sf
        )

        ul = _compute_link_budget(
            direction="uplink",
            pl_db=pl_db,
            tx_power_dbm=target.tx_power_dbm,
            tx_gain_dbi=target.tx_antenna_gain_dbi,
            rx_gain_dbi=gw_rx_gain,
            rx_sensitivity_dbm=gw_sens,
            sf=sf,
        )
        dl = _compute_link_budget(
            direction="downlink",
            pl_db=pl_db,
            tx_power_dbm=gateway.tx_power_dbm,
            tx_gain_dbi=gateway.antenna_gain_dbi,
            rx_gain_dbi=target.rx_antenna_gain_dbi,
            rx_sensitivity_dbm=dev_sens,
            sf=sf,
        )

        coverage_status = _status_worse_of(ul.status, dl.status)
        bottleneck = _resolve_bottleneck(ul, dl)
        # recommended_sf bám SNR chiều worst (chiều quyết định decode-ability).
        worst_snr = ul.snr_db if ul.margin_db <= dl.margin_db else dl.snr_db

        # Confidence giảm khi distance lớn (uncertainty từ shadow fading).
        # Heuristic: score = exp(-d_km / 20). Tuned lỏng cho v0.
        score = max(0.05, math.exp(-d_km / 20.0))
        sigma = self._env_profile.shadow_fading_std_db

        return Prediction(
            rssi_dbm=round(dl.rssi_dbm, 2),
            snr_db=round(dl.snr_db, 2),
            coverage_status=coverage_status,
            serving_gateway_id=gateway.id,
            confidence=Confidence(
                score=round(score, 3),
                method=ConfidenceMethod.EMPIRICAL,
                epistemic_variance_db2=0.0,
                aleatoric_variance_db2=sigma * sigma,
            ),
            model_version=self.model_version,
            recommended_sf=_recommend_sf(worst_snr),
            uplink_rssi_dbm=round(ul.rssi_dbm, 2),
            uplink_snr_db=round(ul.snr_db, 2),
            uplink_margin_db=round(ul.margin_db, 2),
            uplink_status=ul.status,
            downlink_rssi_dbm=round(dl.rssi_dbm, 2),
            downlink_snr_db=round(dl.snr_db, 2),
            downlink_margin_db=round(dl.margin_db, 2),
            downlink_status=dl.status,
            bottleneck=bottleneck,
        )
