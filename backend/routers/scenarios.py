"""
routers/scenarios.py — Persona 4 (RnD / consultant) A/B compare.

POST /scenarios/compare
  body: { campaignIdA, campaignIdB }
  → Khớp 2 prediction_grid theo (lat, lng) → diff per cell
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import UUID4
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import NotFoundError
from core.rate_limit import rate_limit_default
from core.responses import CamelModel, ok
from database import get_db
from services.scenarios import compare_grids

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


class CompareRequest(CamelModel):
    campaign_id_a: UUID4
    campaign_id_b: UUID4


async def _fetch_grid(db: AsyncSession, campaign_id: uuid.UUID) -> list[dict]:
    rows = (await db.execute(text("""
        SELECT
            ST_Y(location::geometry) AS lat,
            ST_X(location::geometry) AS lng,
            predicted_rssi_dbm       AS rssi
        FROM prediction_grids
        WHERE campaign_id = :cid
    """), {"cid": str(campaign_id)})).mappings().all()
    return [dict(r) for r in rows]


@router.post("/compare")
async def compare(
    body: CompareRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    rate_limit_default(request)

    grid_a = await _fetch_grid(db, body.campaign_id_a)
    grid_b = await _fetch_grid(db, body.campaign_id_b)

    if not grid_a:
        raise NotFoundError(
            f"Campaign A {body.campaign_id_a} chưa có prediction grid. "
            f"Hãy chạy /predict/run trước.",
            code="GRID_A_NOT_FOUND",
        )
    if not grid_b:
        raise NotFoundError(
            f"Campaign B {body.campaign_id_b} chưa có prediction grid.",
            code="GRID_B_NOT_FOUND",
        )

    result = compare_grids(grid_a, grid_b)
    return ok({
        "campaignIdA": str(body.campaign_id_a),
        "campaignIdB": str(body.campaign_id_b),
        **result,
    })