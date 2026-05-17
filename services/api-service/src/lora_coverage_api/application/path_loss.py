"""Path-loss model contract + link-budget machinery (Stage 1+).

Stage 1 thực tế sống ở `application/itu/model.py` (ITU-R P.1812 + P.2108);
backend ở `infrastructure/itu/`. File này chỉ giữ:

  - `PathLossModel` Protocol — interface mọi Stage chia sẻ (Stage 1/2/3/4).
  - `EnvironmentProfile` — shadow-fading σ cho Confidence aleatoric.
  - Link-budget helpers (Friis Pr = Pt + Gt + Gr - PL, classify, SF margin,
    bottleneck UL/DL). Stage1ItuModel + future Stage models reuse.

Pure math, không I/O. Khi caller cần PL number, gọi `model.predict(...)`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from ..domain.coverage import (
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

# 3 dB margin trên SF limit để đảm bảo decode tin cậy (LoRa SNR có jitter).
_SF_MARGIN_DB = 3.0

LinkDirection = Literal["uplink", "downlink"]


# ── Environment profile (12F III: config qua env) ────────────────────────
@dataclass(frozen=True, slots=True)
class EnvironmentProfile:
    """Bundle hằng số môi trường (σ shadow fading) cho Confidence aleatoric.

    What: name + shadow_fading_std_db.
    Why bundle: dù v1 chỉ còn 1 field, vẫn giữ dataclass để mở rộng dễ
        (vd thêm building density default, vegetation factor) mà không phá
        signature của Stage1ItuModel.
    """

    name: str
    shadow_fading_std_db: float


URBAN_PROFILE = EnvironmentProfile(name="urban", shadow_fading_std_db=8.0)
SUBURBAN_PROFILE = EnvironmentProfile(name="suburban", shadow_fading_std_db=6.0)
RURAL_PROFILE = EnvironmentProfile(name="rural", shadow_fading_std_db=4.0)

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


@dataclass(frozen=True, slots=True)
class LinkBudget:
    """Kết quả Pr = Pt + Gt + Gr - PL cho 1 chiều (UL hoặc DL)."""

    direction: LinkDirection
    rssi_dbm: float
    snr_db: float
    margin_db: float
    status: CoverageStatus


def compute_link_budget(
    direction: LinkDirection,
    pl_db: float,
    tx_power_dbm: float,
    tx_gain_dbi: float,
    rx_gain_dbi: float,
    rx_sensitivity_dbm: float,
    sf: int,
) -> LinkBudget:
    """Friis: Pr = Pt + Gt + Gr - PL. SNR = Pr - noise_floor.

    Caveat v0: dùng cùng NOISE_FLOOR_DBM_125KHZ cho cả 2 chiều. Thực tế device
    side NF có thể khác (~3 dB) — refine khi có DL telemetry chính xác.
    """
    rssi_dbm = tx_power_dbm + tx_gain_dbi + rx_gain_dbi - pl_db
    snr_db = rssi_dbm - NOISE_FLOOR_DBM_125KHZ
    margin_db = rssi_dbm - rx_sensitivity_dbm
    status = classify(rssi_dbm, snr_db, sf)
    return LinkBudget(
        direction=direction,
        rssi_dbm=rssi_dbm,
        snr_db=snr_db,
        margin_db=margin_db,
        status=status,
    )


def classify(rssi_dbm: float, snr_db: float, sf: int) -> CoverageStatus:
    sf_limit = SF_SNR_LIMITS_DB[sf]
    if rssi_dbm >= -100.0 and snr_db >= 5.0:
        return CoverageStatus.STRONG
    if snr_db >= sf_limit and rssi_dbm >= -120.0:
        return CoverageStatus.MARGINAL if snr_db < 5.0 else CoverageStatus.STRONG
    if snr_db >= SF_SNR_LIMITS_DB[12]:
        return CoverageStatus.WEAK
    return CoverageStatus.NO_COVERAGE


def status_worse_of(a: CoverageStatus, b: CoverageStatus) -> CoverageStatus:
    """Trả status tệ hơn theo _STATUS_RANK (NO_COVERAGE worst, STRONG best)."""
    return a if _STATUS_RANK[a] <= _STATUS_RANK[b] else b


def recommend_sf(snr_db: float) -> int:
    """SF nhỏ nhất vẫn decode được với 3 dB margin.

    Theo business-logic.md §4.2 — trả "recommended_sf" cho engineer biết nên
    cấu hình LoRaWAN MAC. Không default SF=7 khi điều kiện đòi hỏi cao hơn.
    """
    for sf in (7, 8, 9, 10, 11, 12):
        if snr_db >= SF_SNR_LIMITS_DB[sf] + _SF_MARGIN_DB:
            return sf
    return 12  # Beyond SF12 limit — vẫn report SF12, caller xử lý NO_COVERAGE.


def resolve_gateway_rx_gain(gateway: Gateway) -> float:
    """None = duplex symmetric (= antenna_gain_dbi). Resolution tại app layer."""
    return (
        gateway.antenna_gain_dbi
        if gateway.rx_antenna_gain_dbi is None
        else gateway.rx_antenna_gain_dbi
    )


def resolve_sensitivity(
    provided: float | None, defaults_table: dict[int, float], sf: int
) -> float:
    """None → tra SF table. Boundary nhỏ — dataclass-or-default fallback."""
    return defaults_table[sf] if provided is None else provided


def resolve_bottleneck(ul: LinkBudget, dl: LinkBudget) -> LinkBottleneck:
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
