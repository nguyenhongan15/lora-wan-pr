"""
routers/aoi.py — AOI list/detail/candidates endpoints.

Dùng:
  - core.responses.ok / SuccessResponse
  - core.exceptions.NotFoundError
  - request.state.request_id (set bởi CorrelationIdMiddleware)
"""

from __future__ import annotations

import json
import logging
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import NotFoundError
from core.responses import ok
from database import AsyncSessionLocal
from schemas import AOIDetail, AOISummary, CandidateSummary
from services import candidate_repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/aois", tags=["aois"])


# ─── DB dependency ───────────────────────────────────────────────────────────

async def get_db() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session


# ─── Helpers (inline SQL chỉ dùng ở router này) ──────────────────────────────

async def _list_aois_summary(db: AsyncSession) -> list[dict]:
    rows = (await db.execute(text("""
        SELECT
            id::text                                                  AS id,
            slug,
            name,
            admin_level,
            osm_relation_id,
            ROUND(CAST(ST_Area(boundary::geography) / 1e6 AS NUMERIC)) AS area_km2,
            ST_NumGeometries(boundary)                                AS polygon_count
        FROM aoi_polygons
        WHERE deleted_at IS NULL
        ORDER BY created_at ASC
    """))).mappings().all()
    return [dict(r) for r in rows]


async def _get_aoi_full(db: AsyncSession, slug: str) -> dict | None:
    row = (await db.execute(text("""
        SELECT
            id::text                                                  AS id,
            slug,
            name,
            admin_level,
            osm_relation_id,
            ROUND(CAST(ST_Area(boundary::geography) / 1e6 AS NUMERIC)) AS area_km2,
            ST_NumGeometries(boundary)                                AS polygon_count,
            ST_AsGeoJSON(boundary)                                    AS boundary_geojson,
            ST_XMin(boundary::geometry)                               AS min_lng,
            ST_YMin(boundary::geometry)                               AS min_lat,
            ST_XMax(boundary::geometry)                               AS max_lng,
            ST_YMax(boundary::geometry)                               AS max_lat
        FROM aoi_polygons
        WHERE slug = :slug AND deleted_at IS NULL
    """), {"slug": slug})).mappings().first()
    return dict(row) if row else None


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.get("")
async def list_aois(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """List all AOIs (summary). POC số lượng nhỏ → không paginate."""
    rows = await _list_aois_summary(db)
    aois = [
        AOISummary(
            id              = r["id"],
            slug            = r["slug"],
            name            = r["name"],
            admin_level     = r["admin_level"],
            osm_relation_id = r["osm_relation_id"],
            area_km2        = float(r["area_km2"]) if r["area_km2"] is not None else None,
            polygon_count   = r["polygon_count"],
        )
        for r in rows
    ]
    return ok(data=[a.model_dump(by_alias=True) for a in aois])


@router.get("/{slug}")
async def get_aoi(
    slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """AOI detail kèm boundary GeoJSON + bbox cho map render."""
    row = await _get_aoi_full(db, slug)
    if row is None:
        raise NotFoundError(
            f"Không tìm thấy AOI với slug '{slug}'",
            code="AOI_NOT_FOUND",
        )

    boundary = json.loads(row["boundary_geojson"]) if row["boundary_geojson"] else {}
    bbox = [
        float(row["min_lng"]), float(row["min_lat"]),
        float(row["max_lng"]), float(row["max_lat"]),
    ]
    detail = AOIDetail(
        id              = row["id"],
        slug            = row["slug"],
        name            = row["name"],
        admin_level     = row["admin_level"],
        osm_relation_id = row["osm_relation_id"],
        area_km2        = float(row["area_km2"]) if row["area_km2"] is not None else None,
        polygon_count   = row["polygon_count"],
        boundary        = boundary,
        bbox            = bbox,
    )
    return ok(data=detail.model_dump(by_alias=True))


@router.get("/{slug}/candidates")
async def list_candidates(
    slug: str,
    request: Request,
    source: Optional[str] = Query(
        None, pattern="^(grid|infra)$",
        description="'grid' | 'infra' | bỏ trống = cả 2",
    ),
    db: AsyncSession = Depends(get_db),
):
    """List candidates của AOI. Trả tất cả (POC ~2700 ≈ 300KB OK)."""
    cands = await candidate_repo.list_candidates_by_aoi_slug(db, slug)
    if not cands:
        # Phân biệt AOI không tồn tại vs AOI có 0 candidates
        aoi = await _get_aoi_full(db, slug)
        if aoi is None:
            raise NotFoundError(
                f"Không tìm thấy AOI với slug '{slug}'",
                code="AOI_NOT_FOUND",
            )
        return ok(data=[])

    if source:
        cands = [c for c in cands if c["source"] == source]

    summaries = [
        CandidateSummary(
            id       = c["id"],
            h3_index = c["h3_index"],
            lat      = float(c["lat"]),
            lng      = float(c["lng"]),
            cost     = float(c["cost"]),
            source   = c["source"],
        )
        for c in cands
    ]
    return ok(data=[s.model_dump(by_alias=True) for s in summaries])