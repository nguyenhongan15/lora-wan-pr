"""
routers/dem_router.py — API endpoints liên quan đến DEM.

GET /dem/elevation?lat=...&lng=...         → độ cao tại điểm
GET /dem/hillshade-bounds                  → Mapbox bounds + coordinates
GET /dem/hillshade.png                     → serve ảnh
GET /dem/elevation-grid/{campaign_id}     → grid (BATCH, fix N+1)
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import NotFoundError
from core.responses import ok
from database import get_db
from ml.dem import get_dem

router = APIRouter(prefix="/dem", tags=["dem"])

STATIC_DIR = Path(__file__).parent.parent / "static"


@router.get("/elevation")
async def get_elevation(
    lat: float = Query(..., description="Vĩ độ"),
    lng: float = Query(..., description="Kinh độ"),
):
    """Độ cao (m) tại một điểm."""
    dem  = get_dem()
    loop = asyncio.get_running_loop()
    elev = await loop.run_in_executor(None, dem.get_elevation, lat, lng)
    return ok({"lat": lat, "lng": lng, "elevationM": round(elev, 1)})


@router.get("/hillshade-bounds")
async def hillshade_bounds():
    """Bounds cho Mapbox ImageSource."""
    bounds_file = STATIC_DIR / "hillshade_bounds.json"
    if not bounds_file.exists():
        raise NotFoundError(
            "Hillshade chưa được tạo. Chạy: docker exec lora_api python ml/generate_hillshade.py",
            code="HILLSHADE_NOT_GENERATED",
        )
    with open(bounds_file) as f:
        return ok(json.load(f))


@router.get("/hillshade.png")
async def serve_hillshade():
    """Serve hillshade PNG cho Mapbox."""
    path = STATIC_DIR / "hillshade.png"
    if not path.exists():
        raise NotFoundError(
            "Chưa tạo hillshade.",
            code="HILLSHADE_NOT_GENERATED",
        )
    # Cache 1 giờ (hillshade chỉ đổi khi ta generate lại)
    return FileResponse(
        str(path),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/elevation-grid/{campaign_id}")
async def elevation_grid(
    campaign_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Lấy độ cao cho tất cả điểm đo của campaign.
    FIX N+1: dùng get_elevations_batch thay vì loop từng row.
    """
    rows = (await db.execute(text("""
        SELECT
            ST_Y(location::geometry) AS lat,
            ST_X(location::geometry) AS lng,
            rssi_dbm,
            altitude_m
        FROM measurements
        WHERE campaign_id = :cid
          AND deleted_at IS NULL
          AND location IS NOT NULL
    """), {"cid": str(campaign_id)})).mappings().all()

    if not rows:
        raise NotFoundError("Không có dữ liệu.", code="NO_MEASUREMENTS")

    lats = [r["lat"] for r in rows]
    lngs = [r["lng"] for r in rows]

    dem  = get_dem()
    loop = asyncio.get_running_loop()
    # Gọi 1 lần batch, không loop
    elevs = await loop.run_in_executor(None, dem.get_elevations_batch, lats, lngs)

    result = [
        {
            "lat":              r["lat"],
            "lng":              r["lng"],
            "rssiDbm":          r["rssi_dbm"],
            "elevationM":       round(float(elevs[i]), 1),
            "deviceAltitudeM":  r["altitude_m"],
        }
        for i, r in enumerate(rows)
    ]

    return ok(
        {"campaignId": str(campaign_id), "points": result},
        meta={"total": len(result)},
    )
