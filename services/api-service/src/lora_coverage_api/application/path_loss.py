"""Path-loss model contract + link-budget machinery (Stage 1+).

Stage 1 thực tế sống ở `application/itu/model.py` (ITU-R P.1812 + P.2108);
backend ở `infrastructure/itu/`. File này chỉ giữ:

  - `PathLossModel` Protocol — interface mọi Stage chia sẻ (Stage 1/2/3/4).
  - `EnvironmentProfile` — shadow-fading σ cho Confidence aleatoric.
  - Link-budget helpers (Friis Pr = Pt + Gt + Gr - PL, classify, SF margin).
    Stage1ItuModel + future Stage models reuse.
  - Signal-quality estimators (PDR, BER, Time-on-Air) cho UI dự đoán chi tiết.

Pure math, không I/O. Khi caller cần PL number, gọi `model.predict(...)`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Protocol

from ..domain.coverage import (
    AS923_DEVICE_TX_POWER_CAP_DBM,
    BottleneckCause,
    CoverageStatus,
    Gateway,
    Prediction,
    Target,
)

# ── Constants (LoRa AS923-2 conservative defaults) ─────────────────────────
# Lý thuyết thermal: -174 + 10·log10(125e3) + NF(6dB) = -117 dBm. Đây là sàn
# lý tưởng cho gateway lab; thực địa interference-dominated cao hơn ~13 dB.
NOISE_FLOOR_DBM_125KHZ = -117.0
# Empirical mean NF từ Đà Nẵng Nov-Dec 2025 survey (8 gateway, n≥20/gw):
# mean -103.8 dBm, range [-110.6, -98.9]. Dùng làm fallback cho gateway chưa
# calibrate riêng (Gateway.noise_floor_dbm IS NULL).
DEFAULT_NOISE_FLOOR_DBM = -104.0
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
    noise_floor_dbm: float = NOISE_FLOOR_DBM_125KHZ,
) -> LinkBudget:
    """Friis: Pr = Pt + Gt + Gr - PL. SNR = Pr - noise_floor.

    noise_floor_dbm: caller cấp NF thực tế (per-gateway cho UL, hằng số cho
    DL). Default giữ -117 thermal cho callers cũ không pass.

    margin_db = min(rssi - sensitivity, snr - SF_limit) — link margin thực,
    "có thể mất bao nhiêu dB nữa thì fail". Lý do dùng min: link pass cần CẢ
    rssi ≥ sens (silicon front-end) VÀ snr ≥ SF_limit (decode). Khi NF thực
    >> NF datasheet (interference-dominated UL), giới hạn SNR bị siết trước
    → margin_sens over-optimistic. Pre-2026-05-31 chỉ dùng rssi-sens → bottleneck
    label đảo chiều cho 100% holdout SF12.
    """
    rssi_dbm = tx_power_dbm + tx_gain_dbi + rx_gain_dbi - pl_db
    snr_db = rssi_dbm - noise_floor_dbm
    sens_margin = rssi_dbm - rx_sensitivity_dbm
    snr_margin = snr_db - SF_SNR_LIMITS_DB[sf]
    margin_db = min(sens_margin, snr_margin)
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


def resolve_sensitivity(provided: float | None, defaults_table: dict[int, float], sf: int) -> float:
    """None → tra SF table. Boundary nhỏ — dataclass-or-default fallback."""
    return defaults_table[sf] if provided is None else provided


# ── Signal-quality estimators (UI dự đoán chi tiết) ──────────────────────
# Worst-SNR-margin = min(UL, DL) (SNR − SF_limit). Stage 1 tính từ link budget;
# orchestrator recompute sau Stage 2 ML residual shift SNR đồng đều.


def estimate_pdr(worst_snr_margin_db: float) -> float:
    """Sigmoid xấp xỉ PDR theo SNR margin trên ngưỡng SF.

    Calibration qualitative theo LoRa CSS waterfall curve:
      margin = +6 dB → ~99% (link ổn định)
      margin =  0 dB → ~62% (sát mép decode)
      margin = -6 dB → ~3%  (gần như mất gói)
    Slope 0.5 cover dải practical [-10, +10] dB.
    """
    return 1.0 / (1.0 + math.exp(-(worst_snr_margin_db - 1.0) * 0.5))


def estimate_ber(worst_snr_margin_db: float) -> float:
    """Xấp xỉ BER theo SNR margin (LoRa CSS waterfall).

    Piecewise — class-based đủ cho UI hiển thị "10⁻³ / 10⁻⁴" thay vì float chính
    xác (LoRa CSS BER exact đòi mô hình kênh chi tiết).
    """
    if worst_snr_margin_db >= 6:
        return 1e-6
    if worst_snr_margin_db >= 3:
        return 1e-4
    if worst_snr_margin_db >= 0:
        return 1e-3
    if worst_snr_margin_db >= -3:
        return 1e-2
    return 1e-1


def time_on_air_ms(
    sf: int,
    *,
    payload_bytes: int = 20,
    bw_hz: int = 125_000,
    cr_index: int = 1,
    explicit_header: bool = True,
) -> float:
    """LoRa Time-on-Air (ms) — Semtech AN1200.13 §4.

    Default: 20 B payload (LoRaWAN MAC + 10 B user), BW 125 kHz, CR 4/5,
    explicit header, low-data-rate optimize auto-on cho SF ≥ 11.
    """
    low_dr_opt = sf >= 11
    de = 1 if low_dr_opt else 0
    h_bit = 0 if explicit_header else 1  # 0 = explicit (no implicit header bit)
    crc = 1
    t_sym_s = (2**sf) / bw_hz
    n_preamble = 8
    numerator = 8 * payload_bytes - 4 * sf + 28 + 16 * crc - 20 * h_bit
    denom = 4 * (sf - 2 * de)
    payload_symb = 8 + max(math.ceil(numerator / denom) * (cr_index + 4), 0)
    toa_s = (n_preamble + 4.25) * t_sym_s + payload_symb * t_sym_s
    return float(toa_s * 1000.0)


# ── Bottleneck root-cause detection ──────────────────────────────────────
# Threshold đặt conservative để giảm false-positive: chỉ flag khi tín hiệu
# rõ ràng (vd PL > 140 dB là thực sự lớn cho LoRa 923 MHz; NF lệch ≥ 7 dB
# so thermal là interference-dominated thật).
_PATH_LOSS_HIGH_THRESHOLD_DB = 140.0
_SNR_LOW_MARGIN_THRESHOLD_DB = 3.0
_INTERFERENCE_NF_DELTA_THRESHOLD_DB = 7.0


def detect_bottleneck_causes(prediction: Prediction, target: Target) -> tuple[BottleneckCause, ...]:
    """Phát hiện root cause của bottleneck từ Prediction + Target.

    Trả tuple để giữ Prediction frozen + hashable. Rỗng = không cause nào
    chạm threshold (link healthy hoặc các yếu tố cân bằng).

    5 cause:
      - path_loss_high: PL > 140 dB.
      - snr_low: min(UL,DL) SNR margin trên SF limit < 3 dB.
      - interference: UL noise floor cao hơn thermal -117 ≥ 7 dB.
      - tx_power_cap: TX = AS923-2 cap (14 dBm) AND UL margin ≤ DL margin
        (UL là chiều yếu hơn → không nâng được TX nữa).
      - sf_mismatch: SF user dùng < recommended_sf.

    FE hiển thị dưới dạng "Bottleneck có thể xảy ra ở …" — danh sách khả năng,
    không khẳng định nguyên nhân duy nhất.
    """
    causes: list[BottleneckCause] = []

    if prediction.path_loss_db > _PATH_LOSS_HIGH_THRESHOLD_DB:
        causes.append("path_loss_high")

    sf_limit = SF_SNR_LIMITS_DB[target.spreading_factor]
    worst_snr_margin = min(
        prediction.uplink_snr_db - sf_limit,
        prediction.downlink_snr_db - sf_limit,
    )
    if worst_snr_margin < _SNR_LOW_MARGIN_THRESHOLD_DB:
        causes.append("snr_low")

    nf_delta = prediction.uplink_noise_floor_dbm - NOISE_FLOOR_DBM_125KHZ
    if nf_delta >= _INTERFERENCE_NF_DELTA_THRESHOLD_DB:
        causes.append("interference")

    if (
        target.tx_power_dbm >= AS923_DEVICE_TX_POWER_CAP_DBM
        and prediction.uplink_margin_db <= prediction.downlink_margin_db
    ):
        causes.append("tx_power_cap")

    if target.spreading_factor < prediction.recommended_sf:
        causes.append("sf_mismatch")

    return tuple(causes)


def estimate_jitter_ms(toa_ms: float) -> float:
    """Jitter ước lượng ≈ 5% ToA — LoRaWAN MAC random backoff sau collision.

    Conservative; thực tế jitter còn phụ thuộc duty-cycle wait (~1% region).
    """
    return toa_ms * 0.05


class PathLossModel(Protocol):
    """Tất cả model qua các Stage chia sẻ interface này."""

    @property
    def model_version(self) -> str: ...

    def predict(self, target: Target, gateway: Gateway) -> Prediction: ...
