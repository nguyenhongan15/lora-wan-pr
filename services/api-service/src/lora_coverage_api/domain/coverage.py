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

# Bottleneck direction trong bidirectional link budget.
LinkBottleneck = Literal["uplink", "downlink", "both_ok"]

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
    RESIDUAL = "residual"  # Stage 2: Stage1 + ML residual
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

    Bottleneck:
    - "uplink": UL margin nhỏ hơn DL margin > 1 dB → device TX là điểm yếu.
    - "downlink": DL margin nhỏ hơn UL margin > 1 dB → device RX là điểm yếu.
    - "both_ok": chênh lệch ≤ 1 dB và cả 2 status STRONG.
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
    bottleneck: LinkBottleneck = "both_ok"
    # Path loss tổng (basic transmission loss + BEL nếu có) cho UL+DL đối xứng.
    # Engineer debug "RSSI thấp do terrain xa hay building entry loss" — bóc tách
    # giúp họ biết cần đặt thêm GW (PL terrain cao) hay đẩy device ra ngoài
    # (BEL cao). 0.0 default cho Stage 2+ chưa wire.
    path_loss_db: float = 0.0
    # Khoảng cách haversine target → serving gateway. Hữu ích display ở popup.
    # 0.0 = no serving gateway / chưa wire.
    distance_to_serving_gateway_km: float = 0.0

    def __post_init__(self) -> None:
        if self.confidence is None:
            raise ValueError("Prediction.confidence is required")
        if self.recommended_sf not in (7, 8, 9, 10, 11, 12):
            raise ValueError(f"invalid recommended_sf: {self.recommended_sf}")
        if self.bottleneck not in ("uplink", "downlink", "both_ok"):
            raise ValueError(f"invalid bottleneck: {self.bottleneck}")


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

    def __post_init__(self) -> None:
        if self.rx_antenna_gain_dbi is not None and not -10.0 <= self.rx_antenna_gain_dbi <= 30.0:
            raise ValueError(f"rx_antenna_gain_dbi out of range: {self.rx_antenna_gain_dbi}")
        if self.rx_sensitivity_dbm is not None and not -150.0 <= self.rx_sensitivity_dbm <= -50.0:
            raise ValueError(f"rx_sensitivity_dbm out of range: {self.rx_sensitivity_dbm}")
        if self.noise_floor_dbm is not None and not -130.0 <= self.noise_floor_dbm <= -80.0:
            raise ValueError(f"noise_floor_dbm out of range: {self.noise_floor_dbm}")
