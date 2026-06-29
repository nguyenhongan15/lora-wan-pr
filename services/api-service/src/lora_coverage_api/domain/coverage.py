"""Coverage domain types.

Không phụ thuộc framework, không I/O. Pure types + invariants.
Theo data-architecture.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, NewType
from uuid import UUID

GatewayId = NewType("GatewayId", UUID)

# AS923-2/VN: device EIRP cap (LoRaWAN regional params).
AS923_DEVICE_TX_POWER_CAP_DBM = 14.0

# Device antenna defaults (whip TX, PCB integrated RX). Shared giữa Target
# dataclass và precompute script — sửa 1 chỗ duy nhất khi đổi BOM.
DEVICE_DEFAULT_TX_GAIN_DBI = 2.0
DEVICE_DEFAULT_RX_GAIN_DBI = 0.0

# Bottleneck root-cause flags — direction (UL/DL) đã bỏ khỏi response 2026-06-14.
# 5 cause compute được từ Stage 1/Stage 2 output + Target. 4 cause khác
# (multipath fast fading, instant shadowing, frequency offset, polarization
# mismatch) cần telemetry chưa có → parking.
# - path_loss_high: PL_total > 140 dB → suy hao quá lớn cho LoRa link budget.
# - snr_low: min(UL,DL) SNR margin < 3 dB so với SF limit → sát ngưỡng decode.
# - interference: UL noise floor lệch ≥ 7 dB so với thermal -117 → môi trường
#   nhiễu đồng kênh chiếm dominant.
# - tx_power_cap: device TX = 14 dBm (AS923-2 cap) AND UL margin < DL margin
#   (chiều UL là weaker link).
# - sf_mismatch: SF user chọn < recommended_sf → cấu hình thấp hơn cần thiết.
BottleneckCause = Literal[
    "path_loss_high",
    "snr_low",
    "interference",
    "tx_power_cap",
    "sf_mismatch",
]

# Terminal environment — quyết định Stage 1 có cộng building entry loss
# (ITU-R P.2109) hay không. outdoor = không cộng; indoor/indoor_deep map sang
# percentile 50%/90% ở application layer.
TerminalEnvironment = Literal["outdoor", "indoor", "indoor_deep"]


class CoverageStatus(StrEnum):
    STRONG = "strong"  # RSSI ≥ -100, SNR ≥ 5
    MARGINAL = "marginal"  # RSSI ≥ -115, SNR ≥ -7.5 (SF7)
    WEAK = "weak"  # SNR < -7.5 nhưng > SF12 limit (-20)
    NO_COVERAGE = "no_coverage"  # Không link budget khả thi


class ConfidenceMethod(StrEnum):
    PHYSICS = "physics"  # Stage 1: ITU-R P.1812 + P.2108 (first-principles)
    RESIDUAL = "residual"  # Stage 2: Stage1 baseline + Extra Trees end-to-end delta
    ENSEMBLE = "ensemble"  # Stage 3: deep ensemble
    BAYESIAN = "bayesian"  # Stage 4: variational (TRIGGERED)


@dataclass(frozen=True, slots=True)
class Confidence:
    """Mọi Prediction PHẢI kèm Confidence (hard invariant).

    Variance fields default 0.0 — Stage 1 set aleatoric từ shadow fading σ²;
    Stage 2/3 set epistemic từ ensemble/GP. Đơn vị dB² (variance của RSSI dB).
    """

    score: float  # [0, 1]
    method: ConfidenceMethod
    epistemic_variance_db2: float = 0.0
    aleatoric_variance_db2: float = 0.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 1.0:
            raise ValueError(f"Confidence.score must be in [0,1], got {self.score}")
        if self.epistemic_variance_db2 < 0:
            raise ValueError(
                f"Confidence.epistemic_variance_db2 must be >= 0, got {self.epistemic_variance_db2}"
            )
        if self.aleatoric_variance_db2 < 0:
            raise ValueError(
                f"Confidence.aleatoric_variance_db2 must be >= 0, got {self.aleatoric_variance_db2}"
            )


@dataclass(frozen=True, slots=True)
class Target:
    """Điểm cần predict coverage. WGS84.

    Bidirectional link budget fields:
    - tx_power_dbm: device EIRP khi phát uplink. Default 14 dBm (AS923-2 cap).
    - tx_antenna_gain_dbi: gain anten phát của device (Gₜ_dev). Default 2 dBi (whip).
    - rx_antenna_gain_dbi: gain anten thu của device (Gᵣ_dev) khi nhận downlink.
      Default 0 dBi (PCB tích hợp). Mote rời thường 1-3 dBi.
    - rx_sensitivity_dbm: device RX sensitivity. None = derive từ SF table
      ở application layer (Semtech SX1276 datasheet).
    """

    latitude: float
    longitude: float
    spreading_factor: int  # 7..12
    frequency_mhz: float = 923.0
    rx_antenna_gain_dbi: float = DEVICE_DEFAULT_RX_GAIN_DBI
    tx_power_dbm: float = AS923_DEVICE_TX_POWER_CAP_DBM
    tx_antenna_gain_dbi: float = DEVICE_DEFAULT_TX_GAIN_DBI
    rx_sensitivity_dbm: float | None = None
    environment: TerminalEnvironment = "outdoor"

    def __post_init__(self) -> None:
        if not -90.0 <= self.latitude <= 90.0:
            raise ValueError(f"latitude out of range: {self.latitude}")
        if not -180.0 <= self.longitude <= 180.0:
            raise ValueError(f"longitude out of range: {self.longitude}")
        if self.spreading_factor not in (7, 8, 9, 10, 11, 12):
            raise ValueError(f"invalid SF: {self.spreading_factor}")
        if self.tx_power_dbm > AS923_DEVICE_TX_POWER_CAP_DBM:
            raise ValueError(
                f"tx_power_dbm {self.tx_power_dbm} exceeds AS923-2 cap "
                f"{AS923_DEVICE_TX_POWER_CAP_DBM} dBm"
            )
        if self.rx_sensitivity_dbm is not None and not -150.0 <= self.rx_sensitivity_dbm <= -50.0:
            raise ValueError(f"rx_sensitivity_dbm out of range: {self.rx_sensitivity_dbm}")
        if self.environment not in ("outdoor", "indoor", "indoor_deep"):
            raise ValueError(f"invalid environment: {self.environment}")


@dataclass(frozen=True, slots=True)
class Prediction:
    """Kết quả predict coverage tại 1 điểm.

    Bidirectional link budget: tách rõ uplink (device → gateway) và downlink
    (gateway → device). Top-level rssi_dbm/snr_db giữ nghĩa = downlink để
    backward compat với clients hiện hữu (thường vẽ marker từ field này).
    coverage_status = worst-of(uplink_status, downlink_status) để phản ánh
    giới hạn link 2 chiều thực tế.

    Engineer suy chiều yếu (UL vs DL) từ uplink_margin_db vs downlink_margin_db
    trực tiếp; không cần field summary direction riêng.
    """

    rssi_dbm: float  # = downlink_rssi_dbm (semantic backward-compat)
    snr_db: float  # = downlink_snr_db
    coverage_status: CoverageStatus  # worst-of UL & DL
    serving_gateway_id: GatewayId | None
    confidence: Confidence
    model_version: str
    recommended_sf: int  # SF nhỏ nhất vẫn đảm bảo SNR ≥ SF limit + 3dB margin
    uplink_rssi_dbm: float = 0.0
    uplink_snr_db: float = 0.0
    uplink_margin_db: float = 0.0
    uplink_status: CoverageStatus = CoverageStatus.NO_COVERAGE
    downlink_rssi_dbm: float = 0.0
    downlink_snr_db: float = 0.0
    downlink_margin_db: float = 0.0
    downlink_status: CoverageStatus = CoverageStatus.NO_COVERAGE
    # Path loss tổng (basic transmission loss + BEL nếu có) cho UL+DL đối xứng.
    # Engineer debug "RSSI thấp do terrain xa hay building entry loss" — bóc tách
    # giúp họ biết cần đặt thêm GW (PL terrain cao) hay đẩy device ra ngoài
    # (BEL cao). 0.0 default cho Stage 2+ chưa wire.
    path_loss_db: float = 0.0
    # Khoảng cách haversine target → serving gateway. Hữu ích display ở popup.
    # 0.0 = no serving gateway / chưa wire.
    distance_to_serving_gateway_km: float = 0.0
    # ── Signal-quality metrics (FE "Dự đoán điểm" tab) ─────────────────────
    # Stage 1 tính từ SNR margin (= worst-of UL/DL); Stage 2 ET shift SNR
    # đồng đều → orchestrator recompute. Default 0.0 để legacy test/factory
    # không vỡ.
    pdr: float = 0.0  # Packet Delivery Ratio [0,1]
    ber: float = 0.0  # Bit Error Rate (linear, vd 1e-3)
    fer: float = 0.0  # Frame Error Rate = 1 - pdr [0,1]
    # LoRa MAC params (AS923-2 channel 0 default).
    bandwidth_hz: int = 125_000
    time_on_air_ms: float = 0.0
    jitter_ms: float = 0.0
    # σ shadow fading (dB) — trùng √aleatoric_variance_db2; expose riêng để FE
    # khỏi √ và để hiển thị "đa đường + che chắn" rõ ý hơn cho user.
    shadow_fading_sigma_db: float = 0.0
    # Noise floor (dBm): UL = per-gateway calibrated (Gateway.noise_floor_dbm),
    # DL = thermal -117 dBm (chưa có DL telemetry để calibrate).
    uplink_noise_floor_dbm: float = 0.0
    downlink_noise_floor_dbm: float = 0.0
    # Echo env params từ Target (FE hiển thị "Thông số môi trường ảnh hưởng").
    environment: TerminalEnvironment = "outdoor"
    tx_power_dbm: float = 0.0
    frequency_mhz: float = 923.0
    # SF user yêu cầu cho lần predict này (≠ recommended_sf khi mismatch).
    spreading_factor: int = 7
    # Số gateway đủ phủ sóng (status != NO_COVERAGE) trong 30 km radius. Cho
    # biết redundancy: 1 = chỉ 1 GW phục vụ (single point of failure), ≥2 =
    # diversity. 0 = NO_COVERAGE thực sự (không gw nào đủ). Mặc định 0 để
    # backward compat với Stage 2+ factory chưa wire field này.
    covering_gateway_count: int = 0
    # Root-cause flags của bottleneck — orthogonal với direction (uplink/downlink).
    # Tuple để giữ Prediction frozen + hashable. Rỗng = không phát hiện cause
    # nào (link healthy hoặc tất cả threshold chưa chạm).
    bottleneck_causes: tuple[BottleneckCause, ...] = ()

    def __post_init__(self) -> None:
        if self.confidence is None:
            raise ValueError("Prediction.confidence is required")
        if self.recommended_sf not in (7, 8, 9, 10, 11, 12):
            raise ValueError(f"invalid recommended_sf: {self.recommended_sf}")


@dataclass(frozen=True, slots=True)
class Gateway:
    """Gateway entity (read-model cho prediction).

    Semantic mới (sau bidirectional refactor):
    - antenna_gain_dbi: TX antenna gain (Gₜ_gw) khi gateway phát downlink.
      Giữ tên cũ để tránh phá schema/DB.
    - rx_antenna_gain_dbi: RX antenna gain (Gᵣ_gw) khi gateway thu uplink.
      None = giả định duplex antenna đối xứng (= antenna_gain_dbi); resolution
      diễn ra ở application layer (path_loss._resolve_rx_gain).
    - rx_sensitivity_dbm: gateway sensitivity per chain. None = derive từ SF
      table (Semtech SX1302 datasheet) ở application layer.
    - noise_floor_dbm: per-gateway measured noise floor (dBm) tại 125 kHz BW.
      None = fallback DEFAULT_NOISE_FLOOR_DBM (-104) tại application layer.
      Calibrate từ survey (rssi - snr) theo gateway; interference-dominated
      environment ở VN lệch xa giá trị thermal -117.
    """

    id: GatewayId
    code: str
    name: str
    latitude: float
    longitude: float
    altitude_m: float
    antenna_height_m: float
    antenna_gain_dbi: float  # TX gain
    tx_power_dbm: float
    frequency_mhz: float
    rx_antenna_gain_dbi: float | None = None
    rx_sensitivity_dbm: float | None = None
    noise_floor_dbm: float | None = None
    # Per-gateway physics RSSI bias (dB) — cộng vào RSSI dự đoán để hiệu chỉnh
    # sai số hệ thống của Stage 1 cho gateway này (anten/vị trí/môi trường thực
    # khác nominal). None = không hiệu chỉnh. Calibrate từ survey.
    rssi_bias_db: float | None = None
    # is_public=False = admin đã ẩn khỏi bản đồ chung; user vẫn thấy ở map "Của tôi".
    is_public: bool = True
    # Admin "ghim" state thủ công, bỏ qua ChirpStack/DB derive. None = auto.
    manual_state_override: str | None = None

    def __post_init__(self) -> None:
        if self.rx_antenna_gain_dbi is not None and not -10.0 <= self.rx_antenna_gain_dbi <= 30.0:
            raise ValueError(f"rx_antenna_gain_dbi out of range: {self.rx_antenna_gain_dbi}")
        if self.rx_sensitivity_dbm is not None and not -150.0 <= self.rx_sensitivity_dbm <= -50.0:
            raise ValueError(f"rx_sensitivity_dbm out of range: {self.rx_sensitivity_dbm}")
        if self.noise_floor_dbm is not None and not -130.0 <= self.noise_floor_dbm <= -80.0:
            raise ValueError(f"noise_floor_dbm out of range: {self.noise_floor_dbm}")
        if self.rssi_bias_db is not None and not -60.0 <= self.rssi_bias_db <= 60.0:
            raise ValueError(f"rssi_bias_db out of range: {self.rssi_bias_db}")
