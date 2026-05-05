"""Coverage domain types.

Không phụ thuộc framework, không I/O. Pure types + invariants.
Theo data-architecture.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import NewType
from uuid import UUID

GatewayId = NewType("GatewayId", UUID)


class CoverageStatus(str, Enum):
    STRONG = "strong"            # RSSI ≥ -100, SNR ≥ 5
    MARGINAL = "marginal"        # RSSI ≥ -115, SNR ≥ -7.5 (SF7)
    WEAK = "weak"                # SNR < -7.5 nhưng > SF12 limit (-20)
    NO_COVERAGE = "no_coverage"  # Không link budget khả thi


class ConfidenceMethod(str, Enum):
    EMPIRICAL = "empirical"      # Stage 1: log-distance
    RESIDUAL = "residual"        # Stage 2: empirical + ML residual
    ENSEMBLE = "ensemble"        # Stage 3: deep ensemble
    BAYESIAN = "bayesian"        # Stage 4: variational (TRIGGERED)


@dataclass(frozen=True, slots=True)
class Confidence:
    """Mọi Prediction PHẢI kèm Confidence (hard invariant)."""

    score: float                  # [0, 1]
    method: ConfidenceMethod

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 1.0:
            raise ValueError(f"Confidence.score must be in [0,1], got {self.score}")


@dataclass(frozen=True, slots=True)
class Target:
    """Điểm cần predict coverage. WGS84."""

    latitude: float
    longitude: float
    spreading_factor: int        # 7..12
    frequency_mhz: float = 868.0

    def __post_init__(self) -> None:
        if not -90.0 <= self.latitude <= 90.0:
            raise ValueError(f"latitude out of range: {self.latitude}")
        if not -180.0 <= self.longitude <= 180.0:
            raise ValueError(f"longitude out of range: {self.longitude}")
        if self.spreading_factor not in (7, 8, 9, 10, 11, 12):
            raise ValueError(f"invalid SF: {self.spreading_factor}")


@dataclass(frozen=True, slots=True)
class Prediction:
    """Kết quả predict coverage tại 1 điểm."""

    rssi_dbm: float
    snr_db: float
    coverage_status: CoverageStatus
    serving_gateway_id: GatewayId | None
    confidence: Confidence
    model_version: str

    def __post_init__(self) -> None:
        # Hard invariant: confidence luôn phải có (đã enforce qua type, nhưng
        # double-check để bắt lỗi runtime nếu có ai bypass type check).
        if self.confidence is None:  # type: ignore[redundant-expr]
            raise ValueError("Prediction.confidence is required")


@dataclass(frozen=True, slots=True)
class Gateway:
    """Gateway entity (read-model cho prediction)."""

    id: GatewayId
    code: str
    name: str
    latitude: float
    longitude: float
    altitude_m: float
    antenna_height_m: float
    antenna_gain_dbi: float
    tx_power_dbm: float
    frequency_mhz: float
