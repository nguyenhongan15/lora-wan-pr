"""
routers/health.py — Persona 2 (Telco) operations dashboard.

GET /gateway-health   → mỗi gateway: lastSeenAt, hoursSinceLastSeen, uptime, status

Phase 5 thêm:
  - Filter theo X-Project-Id header (multi-tenant)
  - Fire outbound event "gateway.offline" cho các gateway mới chuyển trạng thái
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.responses import ok
from core.tenant import current_project_id
from database import get_db
from services.webhook_dispatcher import fire_event

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/gateway-health", tags=["health"])


# Status thresholds (giờ kể từ uplink cuối)
STATUS_ONLINE_HOURS   = 1     # < 1h → online
STATUS_DEGRADED_HOURS = 6     # 1-6h → degraded; > 6h → offline


def _classify(hours_since_last: float | None) -> str:
    if hours_since_last is None:                  return "offline"
    if hours_since_last < STATUS_ONLINE_HOURS:    return "online"
    if hours_since_last < STATUS_DEGRADED_HOURS:  return "degraded"
    return "offline"


@router.get("/")
async def list_gateway_health(
    project_id_q:  str | None         = Query(None, alias="projectId"),
    project_id_h:  uuid.UUID | None   = Depends(current_project_id),
    notify:        bool               = Query(False, description="Fire 'gateway.offline' webhook"),
    db: AsyncSession = Depends(get_db),
):
    """
    Header X-Project-Id ưu tiên hơn query param ?projectId.
    Nếu không cung cấp project nào → liệt kê tất cả (admin view).

    notify=true: với gateway status='offline' fire event ra subscribers.
    """
    project_id = project_id_h or (uuid.UUID(project_id_q) if project_id_q else None)

    params: dict = {}
    project_filter = ""
    if project_id:
        project_filter = "AND g.project_id = :pid"
        params["pid"] = str(project_id)

    rows = (await db.execute(text(f"""
        WITH last_seen AS (
            SELECT m.gateway_id,
                   MAX(m.measured_at) AS last_at,
                   COUNT(*) AS uplink_count_24h
            FROM measurements m
            WHERE m.deleted_at IS NULL
              AND m.measured_at >= NOW() - INTERVAL '24 hours'
            GROUP BY m.gateway_id
        ),
        uptime_24h AS (
            SELECT m.gateway_id,
                   COUNT(DISTINCT date_trunc('hour', m.measured_at)) AS active_hours
            FROM measurements m
            WHERE m.deleted_at IS NULL
              AND m.measured_at >= NOW() - INTERVAL '24 hours'
            GROUP BY m.gateway_id
        )
        SELECT
            g.id::text                               AS id,
            g.project_id::text                       AS project_id,
            g.name,
            g.gateway_eui,
            ST_X(g.location::geometry)               AS lng,
            ST_Y(g.location::geometry)               AS lat,
            ls.last_at                               AS last_seen_at,
            ls.uplink_count_24h,
            COALESCE(u.active_hours, 0)              AS active_hours_24h,
            EXTRACT(EPOCH FROM (NOW() - ls.last_at)) / 3600.0
                                                     AS hours_since_last
        FROM gateways g
        LEFT JOIN last_seen  ls ON ls.gateway_id = g.id
        LEFT JOIN uptime_24h u  ON u.gateway_id  = g.id
        WHERE g.deleted_at IS NULL
          {project_filter}
        ORDER BY ls.last_at DESC NULLS LAST
    """), params)).mappings().all()

    items = []
    for r in rows:
        hsl    = r["hours_since_last"]
        status = _classify(float(hsl) if hsl is not None else None)

        items.append({
            "id":                  r["id"],
            "projectId":           r["project_id"],
            "name":                r["name"],
            "gatewayEui":          r["gateway_eui"],
            "longitude":           r["lng"],
            "latitude":            r["lat"],
            "lastSeenAt":          r["last_seen_at"].isoformat()
                                   if r["last_seen_at"] else None,
            "hoursSinceLastSeen":  round(float(hsl), 2) if hsl is not None else None,
            "uplinkCount24h":      r["uplink_count_24h"] or 0,
            "uptimePercent24h":    round(float(r["active_hours_24h"]) / 24.0 * 100, 1),
            "status":              status,
        })

    summary = {
        "online":   sum(1 for x in items if x["status"] == "online"),
        "degraded": sum(1 for x in items if x["status"] == "degraded"),
        "offline":  sum(1 for x in items if x["status"] == "offline"),
        "total":    len(items),
    }

    # Outbound notification (chỉ fire khi có project_id)
    if notify and project_id:
        offline_gw = [x for x in items if x["status"] == "offline"]
        if offline_gw:
            try:
                await fire_event(
                    db,
                    project_id=project_id,
                    event_type="gateway.offline",
                    payload={"gateways": offline_gw, "count": len(offline_gw)},
                )
            except Exception as e:
                # Không làm fail request chính nếu webhook lỗi
                logger.warning("webhook_fire_failed", extra={"reason": str(e)})

    return ok(items, meta={"summary": summary})