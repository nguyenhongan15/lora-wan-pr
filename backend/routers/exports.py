"""
routers/exports.py — Export campaign sang file:
  GET /exports/{campaign_id}/measurements.geojson
  GET /exports/{campaign_id}/measurements.kml
  GET /exports/{campaign_id}/boq.xlsx
"""

from __future__ import annotations

import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import NotFoundError, ValidationError
from database import get_db
from services.exporters import (
    gateways_to_boq_xlsx,
    measurements_to_geojson,
    measurements_to_kml,
)
from services.heatmap_png import render_heatmap_png

router = APIRouter(prefix="/exports", tags=["exports"])


async def _fetch_measurements(db: AsyncSession, campaign_id: uuid.UUID) -> list[dict]:
    rows = (await db.execute(text("""
        SELECT
            ST_X(location::geometry) AS lng,
            ST_Y(location::geometry) AS lat,
            rssi_dbm, snr_db, spreading_factor, measured_at
        FROM measurements
        WHERE campaign_id = :cid
          AND deleted_at IS NULL
          AND location IS NOT NULL
        ORDER BY measured_at DESC
    """), {"cid": str(campaign_id)})).mappings().all()
    return [dict(r) for r in rows]


async def _fetch_campaign_name(db: AsyncSession, campaign_id: uuid.UUID) -> str:
    row = (await db.execute(
        text("SELECT name FROM campaigns WHERE id = :cid AND deleted_at IS NULL"),
        {"cid": str(campaign_id)},
    )).mappings().first()
    if not row:
        raise NotFoundError(f"Campaign {campaign_id} không tồn tại.", code="CAMPAIGN_NOT_FOUND")
    return row["name"]


def _content_disposition(filename: str) -> str:
    """RFC 6266 — hỗ trợ tên file Unicode."""
    return f"attachment; filename*=UTF-8''{quote(filename)}"


@router.get("/{campaign_id}/measurements.geojson")
async def export_geojson(campaign_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    name = await _fetch_campaign_name(db, campaign_id)
    rows = await _fetch_measurements(db, campaign_id)
    if not rows:
        raise NotFoundError("Không có điểm đo cho campaign này.", code="NO_MEASUREMENTS")

    import json
    body = json.dumps(measurements_to_geojson(rows), ensure_ascii=False)
    return Response(
        content     = body,
        media_type  = "application/geo+json",
        headers     = {"Content-Disposition": _content_disposition(f"{name}.geojson")},
    )


@router.get("/{campaign_id}/measurements.kml")
async def export_kml(campaign_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    name = await _fetch_campaign_name(db, campaign_id)
    rows = await _fetch_measurements(db, campaign_id)
    if not rows:
        raise NotFoundError("Không có điểm đo cho campaign này.", code="NO_MEASUREMENTS")

    return Response(
        content     = measurements_to_kml(rows, name),
        media_type  = "application/vnd.google-earth.kml+xml",
        headers     = {"Content-Disposition": _content_disposition(f"{name}.kml")},
    )


@router.get("/{campaign_id}/boq.xlsx")
async def export_boq(campaign_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """BoQ chứa danh sách gateway xuất hiện trong campaign này (qua measurements)."""
    name = await _fetch_campaign_name(db, campaign_id)
    rows = (await db.execute(text("""
        SELECT DISTINCT
            g.id::text                       AS id,
            g.name,
            g.gateway_eui                    AS "gatewayEui",
            ST_X(g.location::geometry)       AS longitude,
            ST_Y(g.location::geometry)       AS latitude,
            g.altitude_m                     AS "altitudeM",
            g.antenna_height_m               AS "antennaHeightM",
            g.tx_power_dbm                   AS "txPowerDbm"
        FROM gateways g
        JOIN measurements m ON m.gateway_id = g.id
        WHERE m.campaign_id = :cid
          AND g.deleted_at IS NULL
          AND m.deleted_at IS NULL
        ORDER BY g.name NULLS LAST
    """), {"cid": str(campaign_id)})).mappings().all()

    if not rows:
        raise NotFoundError("Không có gateway nào trong campaign.", code="NO_GATEWAYS")

    xlsx_bytes = gateways_to_boq_xlsx([dict(r) for r in rows], name)
    return Response(
        content     = xlsx_bytes,
        media_type  = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers     = {"Content-Disposition": _content_disposition(f"BoQ-{name}.xlsx")},
    )


@router.get("/{campaign_id}/heatmap.png")
async def export_heatmap_png(
    campaign_id: uuid.UUID,
    metric:       str   = Query("rssi", pattern="^(rssi|snr)$"),
    method:       str   = Query("rbf",  pattern="^(rbf|idw|kriging|delaunay)$"),
    resolution_m: int   = Query(100,    ge=20,  le=2000),
    contours:     int   = Query(5,      ge=0,   le=20),
    show_points:  bool  = Query(True),
    colormap:     str   = Query("RdYlBu_r"),
    alpha:        float = Query(0.6,    ge=0.0, le=1.0),
    dpi:          int   = Query(200,    ge=72,  le=600),
    download:     bool  = Query(False, description="True = attachment, False = inline (preview)"),
    db: AsyncSession    = Depends(get_db),
):
    """
    Heatmap RSSI/SNR static dạng PNG — dùng cho báo cáo, in ấn.

    Pipeline tái sử dụng RBF + corner-anchoring có sẵn ở
    services.interpolation, render qua matplotlib (port từ
    LoRa-survey-heatmap::HeatMapGenerator._plot).
    """
    name = await _fetch_campaign_name(db, campaign_id)
    rows = await _fetch_measurements(db, campaign_id)
    if not rows:
        raise NotFoundError("Không có điểm đo cho campaign này.", code="NO_MEASUREMENTS")

    try:
        png = render_heatmap_png(
            rows,
            metric        = metric,         # type: ignore[arg-type]
            method        = method,
            resolution_m  = resolution_m,
            colormap      = colormap,
            contours      = contours or None,
            show_points   = show_points,
            alpha         = alpha,
            dpi           = dpi,
            title_suffix  = name,
        )
    except ValueError as e:
        raise ValidationError(str(e), code="HEATMAP_INSUFFICIENT_DATA") from e

    disposition_type = "attachment" if download else "inline"
    filename = f"{name}-{metric}-heatmap.png"
    return Response(
        content    = png,
        media_type = "image/png",
        headers    = {
            "Content-Disposition": f"{disposition_type}; filename*=UTF-8''{quote(filename)}",
            "Cache-Control":       "private, max-age=300",
        },
    )