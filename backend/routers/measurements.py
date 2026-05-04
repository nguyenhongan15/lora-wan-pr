"""
routers/measurements.py — Query measurements + stats + coverage grid (GeoJSON).

GET /measurements                   → phân trang chuẩn page/limit
GET /measurements/stats             → thống kê campaign
GET /measurements/coverage-grid/{campaign_id} → GeoJSON cho Mapbox
"""

from typing import Optional
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.responses import ok
from database import get_db

router = APIRouter(prefix="/measurements", tags=["measurements"])


@router.get("/")
async def list_measurements(
    campaign_id: Optional[uuid.UUID] = Query(None,  alias="campaignId"),
    gateway_id:  Optional[uuid.UUID] = Query(None,  alias="gatewayId"),
    min_rssi:    Optional[float]     = Query(None,  alias="minRssi"),
    page:        int                 = Query(1,  ge=1),
    limit:       int                 = Query(50, ge=1, le=500),
    db:          AsyncSession        = Depends(get_db),
):
    """
    GeoJSON FeatureCollection với pagination chuẩn (page, limit).
    """
    filters = ["m.location IS NOT NULL", "m.deleted_at IS NULL"]
    params: dict = {"limit": limit, "offset": (page - 1) * limit}

    if campaign_id:
        filters.append("m.campaign_id = :campaign_id")
        params["campaign_id"] = str(campaign_id)
    if gateway_id:
        filters.append("m.gateway_id = :gateway_id")
        params["gateway_id"] = str(gateway_id)
    if min_rssi is not None:
        filters.append("m.rssi_dbm >= :min_rssi")
        params["min_rssi"] = min_rssi

    where = " AND ".join(filters)

    # Count trước cho meta.total (dùng index → nhanh)
    total_row = await db.execute(
        text(f"SELECT COUNT(*) AS c FROM measurements m WHERE {where}"), params,
    )
    total = total_row.scalar_one()

    rows = (await db.execute(text(f"""
        SELECT
            m.id::text, m.rssi_dbm, m.snr_db, m.spreading_factor,
            m.measured_at, m.gateway_id::text,
            ST_X(m.location::geometry) AS lon,
            ST_Y(m.location::geometry) AS lat
        FROM measurements m
        WHERE {where}
        ORDER BY m.measured_at DESC
        LIMIT :limit OFFSET :offset
    """), params)).mappings().all()

    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
            "properties": {
                "id":              r["id"],
                "rssiDbm":         r["rssi_dbm"],
                "snrDb":           r["snr_db"],
                "spreadingFactor": r["spreading_factor"],
                "measuredAt":      r["measured_at"].isoformat(),
                "gatewayId":       r["gateway_id"],
            },
        }
        for r in rows
    ]

    # GeoJSON là standard quốc tế, không thể bọc wrapper
    # → trả format lai: features ở data, meta.total để client phân trang
    return ok(
        {"type": "FeatureCollection", "features": features},
        meta={"page": page, "limit": limit, "total": total},
    )


@router.get("/stats")
async def measurement_stats(
    campaign_id: Optional[uuid.UUID] = Query(None, alias="campaignId"),
    db:          AsyncSession        = Depends(get_db),
):
    """Thống kê RSSI/SNR của campaign."""
    params = {}
    where  = "deleted_at IS NULL"
    if campaign_id:
        where = "campaign_id = :campaign_id AND deleted_at IS NULL"
        params["campaign_id"] = str(campaign_id)

    result = await db.execute(text(f"""
        SELECT
            COUNT(*)      AS total,
            AVG(rssi_dbm) AS avg_rssi,
            MIN(rssi_dbm) AS min_rssi,
            MAX(rssi_dbm) AS max_rssi,
            AVG(snr_db)   AS avg_snr
        FROM measurements WHERE {where}
    """), params)
    row = result.mappings().one()

    return ok({
        "total":   row["total"],
        "avgRssi": float(row["avg_rssi"]) if row["avg_rssi"] is not None else None,
        "minRssi": float(row["min_rssi"]) if row["min_rssi"] is not None else None,
        "maxRssi": float(row["max_rssi"]) if row["max_rssi"] is not None else None,
        "avgSnr":  float(row["avg_snr"])  if row["avg_snr"]  is not None else None,
    })


@router.get("/coverage-grid/{campaign_id}")
async def coverage_grid(campaign_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """GeoJSON prediction_grid cho Mapbox."""
    rows = (await db.execute(text("""
        SELECT
            pg.id::text,
            pg.predicted_rssi_dbm,
            pg.uncertainty,
            pg.grid_resolution_m,
            ST_X(pg.location::geometry) AS lon,
            ST_Y(pg.location::geometry) AS lat
        FROM prediction_grids pg
        WHERE pg.campaign_id = :campaign_id
        ORDER BY pg.predicted_rssi_dbm DESC
    """), {"campaign_id": str(campaign_id)})).mappings().all()

    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
            "properties": {
                "id":               r["id"],
                "predictedRssiDbm": r["predicted_rssi_dbm"],
                "uncertainty":      r["uncertainty"],
                "gridResolutionM":  r["grid_resolution_m"],
            },
        }
        for r in rows
    ]
    return {"type": "FeatureCollection", "features": features}
