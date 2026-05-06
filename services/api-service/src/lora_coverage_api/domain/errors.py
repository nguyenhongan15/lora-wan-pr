"""Domain-level error types (dùng cho Result[T, E])."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PredictionErrorCode(StrEnum):
    NO_GATEWAY_NEARBY = "NO_GATEWAY_NEARBY"
    LINK_BUDGET_INFEASIBLE = "LINK_BUDGET_INFEASIBLE"
    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class PredictionUnavailable:
    code: PredictionErrorCode
    message: str


class AddressLookupErrorCode(StrEnum):
    NOT_FOUND = "ADDRESS_NOT_FOUND"
    OUT_OF_REGION = "ADDRESS_OUT_OF_REGION"
    PROVIDER_UNAVAILABLE = "GEOCODING_PROVIDER_UNAVAILABLE"
    RATE_LIMITED = "GEOCODING_RATE_LIMITED"


@dataclass(frozen=True, slots=True)
class AddressLookupError:
    code: AddressLookupErrorCode
    message: str
