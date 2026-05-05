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
    frequency_mhz: Literal[433.0, 868.0, 915.0, 923.0] = 868.0


class GatewayPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    altitude_m: float | None = None
    antenna_height_m: float | None = Field(default=None, ge=0)
    antenna_gain_dbi: float | None = None
    tx_power_dbm: float | None = Field(default=None, ge=-10, le=30)
    is_public: bool | None = None


# ── Survey upload ─────────────────────────────────────────────────────────


class SurveyRecordIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    rssi_dbm: float = Field(..., ge=-150, le=-30)
    snr_db: float = Field(..., ge=-30, le=30)
    spreading_factor: int = Field(..., ge=7, le=12)
    frequency_mhz: float = Field(default=868.0)
    device_id: str | None = Field(default=None, max_length=128)
    serving_gateway_id: UUID | None = None


class SurveyUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uploader_id: UUID
    records: list[SurveyRecordIn] = Field(..., min_length=1, max_length=10_000)


class SurveyUploadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: UUID
    status: Literal["quarantined", "rejected"]
    accepted_count: int
    rejected_count: int
    estimated_review_hours: int


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
