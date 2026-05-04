"""
services/aoi_repo.py — Query AOI polygons từ DB (repository pattern).

Phase v3.1 step 2: AOI lookup, GeoJSON serialize, bbox compute,
batch point-in-polygon (cho phase 3 candidate filtering).

SOLID DIP: callers phụ thuộc functions ở đây, không biết SQL/PostGIS.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


# ─────────────────────────────────────────────────────────────────────────────
# Read
# ─────────────────────────────────────────────────────────────────────────────

async def get_aoi_by_slug(db: AsyncSession, slug: str) -> dict | None:
    """Lấy 1 AOI theo slug. Return None nếu không tồn tại / soft-deleted."""
    row = (await db.execute(text("""
        SELECT id, slug, name, admin_level, osm_relation_id,
               ST_AsGeoJSON(boundary)::jsonb AS boundary_geojson,
               properties, fetched_at
        FROM aoi_polygons
        WHERE slug = :slug AND deleted_at IS NULL
    """), {"slug": slug})).mappings().first()
    return dict(row) if row else None


async def get_aoi_geojson_feature(db: AsyncSession, slug: str) -> dict | None:
    """GeoJSON Feature cho frontend overlay / Folium."""
    aoi = await get_aoi_by_slug(db, slug)
    if not aoi:
        return None
    return {
        "type": "Feature",
        "geometry": aoi["boundary_geojson"],
        "properties": {
            "slug":          aoi["slug"],
            "name":          aoi["name"],
            "adminLevel":    aoi["admin_level"],
            "osmRelationId": aoi["osm_relation_id"],
            **(aoi.get("properties") or {}),
        },
    }


async def get_aoi_bbox(
    db: AsyncSession, slug: str,
) -> tuple[float, float, float, float] | None:
    """Bbox (min_lat, max_lat, min_lng, max_lng). None nếu AOI không tồn tại."""
    row = (await db.execute(text("""
        SELECT
            ST_YMin(boundary) AS min_lat,
            ST_YMax(boundary) AS max_lat,
            ST_XMin(boundary) AS min_lng,
            ST_XMax(boundary) AS max_lng
        FROM aoi_polygons
        WHERE slug = :slug AND deleted_at IS NULL
    """), {"slug": slug})).mappings().first()
    if not row:
        return None
    return (row["min_lat"], row["max_lat"], row["min_lng"], row["max_lng"])


async def points_in_aoi(
    db: AsyncSession,
    slug: str,
    lats: list[float],
    lngs: list[float],
) -> list[bool]:
    """
    Batch point-in-polygon check. Trả về list[bool] cùng length input.

    Single SQL query (CTE + unnest + ST_Contains) — nhanh hơn N round-trip.
    Dùng cho Phase 3: filter ~5000 candidate hex grid theo AOI.

    Raises:
        ValueError nếu slug không tồn tại hoặc lats/lngs lệch length.
    """
    if not lats:
        return []
    if len(lats) != len(lngs):
        raise ValueError(
            f"lats và lngs phải cùng length: {len(lats)} vs {len(lngs)}"
        )

    rows = (await db.execute(text("""
        WITH aoi AS (
            SELECT boundary
            FROM aoi_polygons
            WHERE slug = :slug AND deleted_at IS NULL
        ),
        pts AS (
            SELECT idx, ST_SetSRID(ST_MakePoint(lng, lat), 4326) AS geom
            FROM unnest(
                CAST(:lats AS double precision[]),
                CAST(:lngs AS double precision[])
            ) WITH ORDINALITY AS u(lat, lng, idx)
        )
        SELECT pts.idx,
               ST_Contains((SELECT boundary FROM aoi), pts.geom) AS inside
        FROM pts
        ORDER BY pts.idx
    """), {"slug": slug, "lats": lats, "lngs": lngs})).mappings().all()

    if not rows:
        raise ValueError(f"AOI '{slug}' không tồn tại")

    # ST_Contains trả NULL nếu boundary subquery rỗng → coerce False
    return [bool(r["inside"]) if r["inside"] is not None else False for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Write — UPSERT (idempotent cho bootstrap)
# ─────────────────────────────────────────────────────────────────────────────

async def upsert_aoi(
    db: AsyncSession,
    *,
    slug: str,
    name: str,
    admin_level: int,
    osm_relation_id: int | None,
    boundary_wkt: str,           # WKT format: 'MULTIPOLYGON(((...)))'
    properties: dict,
) -> uuid.UUID:
    """
    Insert or update (by slug) AOI. Trả về ID.
    Idempotent — bootstrap chạy lại sẽ refresh data.
    """
    row = (await db.execute(text("""
        INSERT INTO aoi_polygons
            (slug, name, admin_level, osm_relation_id,
             boundary, properties, fetched_at)
        VALUES
            (:slug, :name, :admin_level, :osm_relation_id,
             ST_GeomFromText(:wkt, 4326),
             CAST(:properties AS jsonb),
             :fetched_at)
        ON CONFLICT (slug) DO UPDATE SET
            name            = EXCLUDED.name,
            admin_level     = EXCLUDED.admin_level,
            osm_relation_id = EXCLUDED.osm_relation_id,
            boundary        = EXCLUDED.boundary,
            properties      = EXCLUDED.properties,
            fetched_at      = EXCLUDED.fetched_at,
            updated_at      = NOW(),
            deleted_at      = NULL
        RETURNING id
    """), {
        "slug":            slug,
        "name":            name,
        "admin_level":     admin_level,
        "osm_relation_id": osm_relation_id,
        "wkt":             boundary_wkt,
        "properties":      json.dumps(properties),
        "fetched_at":      datetime.now(timezone.utc),
    })).mappings().first()
    await db.commit()
    return row["id"]