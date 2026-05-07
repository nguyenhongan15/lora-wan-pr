"""Pydantic v2 request/response schemas.

KHÔNG expose ORM models. Schema riêng cho edge layer (theo
rule-design-restfulapi.md §6).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ── Coverage prediction ───────────────────────────────────────────────────


class PredictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    latitude: float = Field(..., ge=-90, le=90, examples=[16.0544])
    longitude: float = Field(..., ge=-180, le=180, examples=[108.2022])
    spreading_factor: int = Field(..., ge=7, le=12, examples=[7])
    frequency_mhz: float = Field(default=868.0, examples=[868.0])


class ConfidenceResponse(BaseModel):
    score: float = Field(..., ge=0, le=1)
    method: Literal["empirical", "residual", "ensemble", "bayesian"]


class PredictionResponse(BaseModel):
    rssi_dbm: float
    snr_db: float
    coverage_status: Literal["strong", "marginal", "weak", "no_coverage"]
    serving_gateway_id: UUID | None
    confidence: ConfidenceResponse
    model_version: str
    recommended_sf: int = Field(..., ge=7, le=12)


# ── Health ────────────────────────────────────────────────────────────────


class HealthStatus(BaseModel):
    status: Literal["ok", "degraded"]
    version: str


# ── Problem details (RFC 7807) ────────────────────────────────────────────


class ProblemDetails(BaseModel):
    """RFC 7807 Problem Details."""

    model_config = ConfigDict(populate_by_name=True)

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    code: str | None = None
    trace_id: str | None = Field(default=None, alias="traceId")


# ── Gateway directory ─────────────────────────────────────────────────────


class GatewayResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    code: str
    name: str
    latitude: float
    longitude: float
    altitude_m: float
    antenna_height_m: float
    antenna_gain_dbi: float
    tx_power_dbm: float
    frequency_mhz: float


class GatewayListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[GatewayResponse]
    total: int


class GatewayCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    code: str = Field(..., min_length=3, max_length=64, examples=["DAD-012"])
    name: str = Field(..., min_length=1, max_length=255)
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    altitude_m: float = Field(default=0.0)
    antenna_height_m: float = Field(default=10.0, ge=0)
    antenna_gain_dbi: float = Field(default=2.0)
    tx_power_dbm: float = Field(default=14.0, ge=-10, le=30)
    # mypy: Python's Literal[...] không chính thức hỗ trợ float, nhưng
    # Pydantic v2 validate đúng runtime + sinh OpenAPI enum đúng.
    # Tham khảo: https://docs.pydantic.dev/latest/concepts/types/#literal
    frequency_mhz: Literal[433.0, 868.0, 915.0, 923.0] = 868.0  # type: ignore[valid-type]


class GatewayPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    altitude_m: float | None = None
    antenna_height_m: float | None = Field(default=None, ge=0)
    antenna_gain_dbi: float | None = None
    tx_power_dbm: float | None = Field(default=None, ge=-10, le=30)
    is_public: bool | None = None


# ── Survey training (read-only) ───────────────────────────────────────────


class SurveyTrainingPointResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latitude: float
    longitude: float
    rssi_dbm: float
    snr_db: float
    spreading_factor: int
    serving_gateway_id: UUID | None


class SurveyTrainingListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[SurveyTrainingPointResponse]
    total: int


# ── ChirpStack webhook ────────────────────────────────────────────────────


class WebhookIngestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted_count: int = Field(..., ge=0)
    inserted_count: int = Field(..., ge=0)
    rejected_count: int = Field(..., ge=0)
    rejected_reasons: list[str] = Field(default_factory=list)


# ── Address lookup (F2 funnel) ────────────────────────────────────────────


class AddressLookupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    address: str = Field(
        ...,
        min_length=1,
        max_length=500,
        examples=[
            "Số 1 Lý Thường Kiệt, Hải Châu, Đà Nẵng",
        ],
    )
    spreading_factor: int = Field(default=7, ge=7, le=12)
    frequency_mhz: Literal[433.0, 868.0, 915.0, 923.0] = 868.0  # type: ignore[valid-type]


class ResolvedAddressResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latitude: float
    longitude: float
    display_name: str
    provider: Literal["cache", "nominatim", "vietmap", "goong", "google"]
    confidence: float = Field(..., ge=0, le=1)


class CoverageLookupResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    address: ResolvedAddressResponse
    prediction: PredictionResponse


# ── Coverage batch (bulk lookup, F3 § /coverage/batch) ────────────────────


class CoverageBatchItem(BaseModel):
    """Mỗi phần tử là một input đơn — có thể là address text hoặc tọa độ."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    label: str | None = Field(default=None, max_length=200)
    address: str | None = Field(default=None, min_length=1, max_length=500)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class CoverageBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[CoverageBatchItem] = Field(..., min_length=1, max_length=500)
    spreading_factor: int = Field(default=7, ge=7, le=12)
    frequency_mhz: Literal[433.0, 868.0, 915.0, 923.0] = 868.0  # type: ignore[valid-type]


class CoverageBatchItemResult(BaseModel):
    """Per-item kết quả. status="ok" → có prediction; "error" → có error."""

    model_config = ConfigDict(extra="forbid")

    label: str | None
    status: Literal["ok", "error"]
    address: ResolvedAddressResponse | None = None
    prediction: PredictionResponse | None = None
    error_code: str | None = None
    error_message: str | None = None


class CoverageBatchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[CoverageBatchItemResult]
    ok_count: int
    error_count: int


# ── Auth (plan-auth-v1 §3.1) ──────────────────────────────────────────────
# Email regex chỉ check shape tối thiểu (có '@', có TLD). Validation thật
# nằm ở DB unique constraint + (v2) email verification flow.

_EMAIL_PATTERN = r"^[^\s@]+@[^\s@]+\.[^\s@]+$"


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: str = Field(..., min_length=3, max_length=320, pattern=_EMAIL_PATTERN)
    password: str = Field(..., min_length=8, max_length=128)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=1, max_length=128)


class UserResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    email: str
    is_admin: bool
    created_at: datetime


class TokenResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access_token: str
    token_type: Literal["bearer"]
    expires_at: datetime
