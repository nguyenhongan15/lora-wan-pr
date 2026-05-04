"""
routers/sandbox.py — Persona 6 (custom env experiment).

POST /sandbox/predict-point     → 1 điểm RX với env params custom
POST /sandbox/radial-profile    → curve RSSI vs distance theo bearing
"""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import Field

from core.rate_limit import rate_limit_default
from core.responses import CamelModel, ok
from services.sandbox import predict_point, predict_radial_profile

router = APIRouter(prefix="/sandbox", tags=["sandbox"])


class PredictPointRequest(CamelModel):
    tx_lat: float = Field(..., ge=-90,  le=90)
    tx_lng: float = Field(..., ge=-180, le=180)
    rx_lat: float = Field(..., ge=-90,  le=90)
    rx_lng: float = Field(..., ge=-180, le=180)
    tx_power_dbm:     float = Field(14.0, ge=0,  le=30)
    antenna_gain_dbi: float = Field( 8.0, ge=0,  le=20)
    environment: Literal["urban", "suburban", "rural", "forest", "coastal", "mountain"] = "urban"
    path_loss_exponent_override: float | None = Field(None, ge=1.5, le=6.0)
    spreading_factor: int = Field(9, ge=7, le=12)


class RadialProfileRequest(CamelModel):
    tx_lat: float = Field(..., ge=-90,  le=90)
    tx_lng: float = Field(..., ge=-180, le=180)
    bearing_deg:    float = Field(90.0, ge=0,  le=360)
    max_distance_m: int   = Field(5_000, ge=100, le=30_000)
    n_samples:      int   = Field(50, ge=10, le=200)
    tx_power_dbm:     float = Field(14.0, ge=0,  le=30)
    antenna_gain_dbi: float = Field( 8.0, ge=0,  le=20)
    environment: Literal["urban", "suburban", "rural", "forest", "coastal", "mountain"] = "urban"
    path_loss_exponent_override: float | None = Field(None, ge=1.5, le=6.0)


@router.post("/predict-point")
async def sandbox_predict_point(body: PredictPointRequest, request: Request):
    rate_limit_default(request)
    # Pure CPU — đủ nhanh để chạy trực tiếp, không cần thread pool
    result = predict_point(**body.model_dump())
    return ok(result)


@router.post("/radial-profile")
async def sandbox_radial(body: RadialProfileRequest, request: Request):
    rate_limit_default(request)

    loop = asyncio.get_running_loop()
    profile = await loop.run_in_executor(
        None,
        lambda: predict_radial_profile(**body.model_dump()),
    )
    return ok({"points": profile})