"""
routers/simulator.py — What-if coverage simulation cho gateway giả định.

POST /simulator/coverage
  body: { transmitters:[{lat,lng,txPowerDbm?,antennaGainDbi?,antennaHeightM?}],
          bbox?, gridResolutionM, environment, model?, useCalibration? }
  → GeoJSON FeatureCollection (predicted RSSI per grid cell)

Phase v3.2 step 2: delegate prediction sang services.rf_predictor (single source
of truth). Thêm flag `useCalibration` — bật → dùng active calibration trong DB
(model="calibrated"); không bật → dùng path-loss model thường.

bbox optional: nếu null/missing → tự tính từ link budget (LoRaWAN SF12 floor).
model optional: "log-distance" (default) hoặc "hata" hoặc "longley-rice".
"""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import AppError
from core.rate_limit import rate_limit_default
from core.responses import CamelModel
from database import get_db
from services.grid import make_grid
from services.path_loss import (
    DEFAULT_FREQ_MHZ,
    DEFAULT_TX_HEIGHT_M,
    auto_select_model,
    compute_auto_bbox,
)
from services.path_loss import Transmitter as _LegacyTransmitter
from services.rf_predictor import (
    RFConfig,
    RxParams,
    TxParams,
    predict_combined_rssi,
    resolve_calibration,
)

router = APIRouter(prefix="/simulator", tags=["simulator"])

# Guard chống quá tải: 50k điểm ≈ vài MB JSON, CPU < 1s.
MAX_GRID_POINTS = 50_000

PathLossModelName = Literal["log-distance", "hata", "longley-rice", "itm-p2p"]


class TransmitterIn(CamelModel):
    lat:              float
    lng:              float
    tx_power_dbm:     float = Field(14.0, ge=0, le=16)   # AS923 VN max conducted
    antenna_gain_dbi: float = Field( 8.0, ge=0, le=20)
    antenna_height_m: float = Field(DEFAULT_TX_HEIGHT_M, ge=5, le=200)


class BBoxIn(CamelModel):
    min_lat: float
    max_lat: float
    min_lng: float
    max_lng: float

    @field_validator("max_lat")
    @classmethod
    def _lat_order(cls, v, info):
        if info.data.get("min_lat") is not None and v <= info.data["min_lat"]:
            raise ValueError("maxLat phải lớn hơn minLat")
        return v

    @field_validator("max_lng")
    @classmethod
    def _lng_order(cls, v, info):
        if info.data.get("min_lng") is not None and v <= info.data["min_lng"]:
            raise ValueError("maxLng phải lớn hơn minLng")
        return v


class SimulateRequest(CamelModel):
    transmitters: list[TransmitterIn] = Field(..., min_length=1, max_length=50)
    bbox: BBoxIn | None = None
    grid_resolution_m: int = Field(50, ge=20, le=200, multiple_of=10)
    environment: Literal["urban", "suburban", "rural", "forest", "coastal", "mountain"] = "urban"
    # model = None → backend auto-pick theo environment + tx_height (xem
    # services.path_loss.auto_select_model). Truyền tay chỉ dành cho power-user
    # gọi API trực tiếp hoặc benchmark so sánh model.
    model: PathLossModelName | None = None
    frequency_mhz: float = Field(DEFAULT_FREQ_MHZ, ge=150.0, le=1500.0)
    spreading_factor: int = Field(9, ge=7, le=12)
    # Phase v3.2: bật → simulator dùng calibration thực từ DB. Default off để
    # không break existing tests + cho user fallback nhanh khi DB chưa có
    # calibration cho env_type yêu cầu.
    use_calibration: bool = False


@router.post("/coverage")
async def simulate_coverage(
    body:    SimulateRequest,
    request: Request,
    db:      AsyncSession = Depends(get_db),
):
    """
    Simulate phủ sóng cho danh sách gateway giả định.
    Trả về GeoJSON thuần (không wrapper) — Mapbox đọc trực tiếp.
    """
    rate_limit_default(request)

    # rf_predictor TxParams — internal type
    transmitters = [
        TxParams(
            lat              = t.lat,
            lng              = t.lng,
            tx_power_dbm     = t.tx_power_dbm,
            antenna_gain_dbi = t.antenna_gain_dbi,
            antenna_height_m = t.antenna_height_m,
        )
        for t in body.transmitters
    ]

    # Auto-pick model nếu client không truyền (UI bỏ dropdown từ phase v3.3).
    # Calibration vẫn ưu tiên cao nhất khi user opt-in.
    if body.use_calibration:
        resolved_model = "calibrated"
    elif body.model is not None:
        resolved_model = body.model
    else:
        max_tx_h = max(t.antenna_height_m for t in transmitters)
        resolved_model = auto_select_model(body.environment, max_tx_h)

    config = RFConfig(
        environment      = body.environment,
        frequency_mhz    = body.frequency_mhz,
        spreading_factor = body.spreading_factor,
        model            = resolved_model,
    )
    config = await resolve_calibration(db, config)

    # compute_auto_bbox vẫn nhận legacy Transmitter (path_loss.py).
    # Mapping: TxParams → Transmitter (đồng nhất fields).
    if body.bbox is None:
        legacy_txs = [
            _LegacyTransmitter(
                lat=t.lat, lng=t.lng,
                tx_power_dbm=t.tx_power_dbm,
                antenna_gain_dbi=t.antenna_gain_dbi,
                antenna_height_m=t.antenna_height_m,
            ) for t in transmitters
        ]
        # compute_auto_bbox chưa hỗ trợ "calibrated"/"itm-p2p" — fallback
        # log-distance cho bbox estimation (chỉ ảnh hưởng vùng tính, không
        # output RSSI).
        bbox_model = (
            "log-distance"
            if config.model in ("calibrated", "itm-p2p")
            else config.model
        )
        min_lat, max_lat, min_lng, max_lng = compute_auto_bbox(
            legacy_txs, body.environment,
            model=bbox_model, freq_mhz=body.frequency_mhz,
        )
    else:
        min_lat, max_lat = body.bbox.min_lat, body.bbox.max_lat
        min_lng, max_lng = body.bbox.min_lng, body.bbox.max_lng

    grid_lats, grid_lngs = make_grid(
        min_lat, max_lat, min_lng, max_lng,
        body.grid_resolution_m,
    )

    n_points = len(grid_lats)
    if n_points > MAX_GRID_POINTS:
        raise AppError(
            code="GRID_TOO_LARGE",
            message=(
                f"Lưới mô phỏng quá lớn ({n_points:,} điểm, "
                f"giới hạn {MAX_GRID_POINTS:,}). "
                f"Hãy tăng resolution hoặc thu nhỏ vùng chọn."
            ),
            http_status=400,
        )

    loop = asyncio.get_running_loop()
    rssi = await loop.run_in_executor(
        None,
        lambda: predict_combined_rssi(
            transmitters = transmitters,
            rx_lats      = grid_lats,
            rx_lngs      = grid_lngs,
            rx           = RxParams(),
            config       = config,
        ),
    )

    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(grid_lngs[i]), float(grid_lats[i])]},
            "properties": {
                "rssi":      round(float(rssi[i]), 2),
                "intensity": max(0.0, min(1.0, (float(rssi[i]) + 137) / 80)),
            },
        }
        for i in range(n_points)
    ]
    response = {"type": "FeatureCollection", "features": features}
    if config.calibration_id:
        response["calibrationId"] = config.calibration_id
    return response
