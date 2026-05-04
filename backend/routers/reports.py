"""
routers/reports.py — Persona 3 (manager / decision maker) PDF reports.

GET /reports/{campaign_id}.pdf
  → Báo cáo tổng quan campaign (overview, RSSI stats, coverage, ML, gateways)
"""

from __future__ import annotations

import asyncio
import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import NotFoundError
from database import get_db
from services.report_pdf import generate_campaign_report
from services.scenarios  import _coverage_dist  # reuse pure helper

router = APIRouter(prefix="/reports", tags=["reports"])


def _content_disposition(filename: str) -> str:
    return f"attachment; filename*=UTF-8''{quote(filename)}"


@router.get("/{campaign_id}.pdf")
async def export_pdf(campaign_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    # ── Campaign metadata ───────────────────────────────────────
    campaign_row = (await db.execute(text("""
        SELECT id::text          AS id,
               name,
               environment_type  AS environmentType,
               start_date        AS startDate,
               end_date          AS endDate,
               weather_condition AS weatherCondition
        FROM campaigns
        WHERE id = :cid AND deleted_at IS NULL
    """), {"cid": str(campaign_id)})).mappings().first()

    if not campaign_row:
        raise NotFoundError(f"Campaign {campaign_id} không tồn tại.",
                            code="CAMPAIGN_NOT_FOUND")

    campaign = {
        "id":               campaign_row["id"],
        "name":             campaign_row["name"],
        "environmentType":  campaign_row["environmenttype"],
        "startDate":        campaign_row["startdate"].isoformat()
                            if campaign_row["startdate"] else None,
        "endDate":          campaign_row["enddate"].isoformat()
                            if campaign_row["enddate"] else None,
        "weatherCondition": campaign_row["weathercondition"],
    }

    # ── Stats ───────────────────────────────────────────────────
    stats_row = (await db.execute(text("""
        SELECT COUNT(*)      AS total,
               AVG(rssi_dbm) AS avg_rssi,
               MIN(rssi_dbm) AS min_rssi,
               MAX(rssi_dbm) AS max_rssi,
               AVG(snr_db)   AS avg_snr
        FROM measurements
        WHERE campaign_id = :cid AND deleted_at IS NULL
    """), {"cid": str(campaign_id)})).mappings().one()

    stats = {
        "total":   stats_row["total"],
        "avgRssi": float(stats_row["avg_rssi"]) if stats_row["avg_rssi"] is not None else None,
        "minRssi": float(stats_row["min_rssi"]) if stats_row["min_rssi"] is not None else None,
        "maxRssi": float(stats_row["max_rssi"]) if stats_row["max_rssi"] is not None else None,
        "avgSnr":  float(stats_row["avg_snr"])  if stats_row["avg_snr"]  is not None else None,
    }

    # ── Coverage distribution từ measurements ───────────────────
    rssi_rows = (await db.execute(text("""
        SELECT rssi_dbm FROM measurements
        WHERE campaign_id = :cid AND deleted_at IS NULL
    """), {"cid": str(campaign_id)})).mappings().all()
    coverage = _coverage_dist([r["rssi_dbm"] for r in rssi_rows]) if rssi_rows else None

    # ── ML grid status ──────────────────────────────────────────
    g_row = (await db.execute(text("""
        SELECT COUNT(*)                AS total_points,
               AVG(predicted_rssi_dbm) AS avg_rssi,
               MIN(predicted_rssi_dbm) AS min_rssi,
               MAX(predicted_rssi_dbm) AS max_rssi,
               AVG(uncertainty)        AS avg_uncertainty,
               MAX(created_at)         AS last_generated
        FROM prediction_grids WHERE campaign_id = :cid
    """), {"cid": str(campaign_id)})).mappings().one()

    grid_status = None
    if g_row["total_points"]:
        grid_status = {
            "hasGrid":          True,
            "totalPoints":      g_row["total_points"],
            "avgRssiDbm":       float(g_row["avg_rssi"])        if g_row["avg_rssi"]        else None,
            "minRssiDbm":       float(g_row["min_rssi"])        if g_row["min_rssi"]        else None,
            "maxRssiDbm":       float(g_row["max_rssi"])        if g_row["max_rssi"]        else None,
            "avgUncertaintyDb": float(g_row["avg_uncertainty"]) if g_row["avg_uncertainty"] else None,
            "lastGenerated":    g_row["last_generated"].isoformat()
                                if g_row["last_generated"] else None,
        }

    # ── Gateways thuộc campaign ─────────────────────────────────
    gw_rows = (await db.execute(text("""
        SELECT DISTINCT
            g.name,
            g.gateway_eui              AS "gatewayEui",
            ST_X(g.location::geometry) AS longitude,
            ST_Y(g.location::geometry) AS latitude,
            g.altitude_m               AS "altitudeM"
        FROM gateways g
        JOIN measurements m ON m.gateway_id = g.id
        WHERE m.campaign_id = :cid
          AND g.deleted_at IS NULL
          AND m.deleted_at IS NULL
        ORDER BY g.name NULLS LAST
    """), {"cid": str(campaign_id)})).mappings().all()
    gateways = [dict(r) for r in gw_rows]

    # PDF generation là CPU-bound (reportlab) → thread pool
    loop = asyncio.get_running_loop()
    pdf_bytes = await loop.run_in_executor(
        None,
        lambda: generate_campaign_report(
            campaign=campaign, stats=stats, coverage=coverage,
            grid_status=grid_status, gateways=gateways,
        ),
    )

    safe_name = campaign["name"].replace("/", "-").replace(" ", "_")
    return Response(
        content     = pdf_bytes,
        media_type  = "application/pdf",
        headers     = {"Content-Disposition": _content_disposition(f"report-{safe_name}.pdf")},
    )