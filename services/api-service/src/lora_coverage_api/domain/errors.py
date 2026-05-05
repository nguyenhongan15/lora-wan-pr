"""Domain-level error types (dùng cho Result[T, E])."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PredictionErrorCode(str, Enum):
    NO_GATEWAY_NEARBY = "NO_GATEWAY_NEARBY"
    LINK_BUDGET_INFEASIBLE = "LINK_BUDGET_INFEASIBLE"
    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class PredictionUnavailable:
    code: PredictionErrorCode
    message: str
