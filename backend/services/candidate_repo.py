"""
services/candidate_repo.py — Persist + query gateway candidates.

Source 'grid':  H3 polyfill toàn AOI, cost mặc định 1.0 (build new tower).
Source 'infra': từ OSM (tower, mast, tall building), cost mặc định 0.3 (rent).

Dedup:
  - Tầng 1 (tự động qua ON CONFLICT): infra cùng hex grid → infra override
    (location + cost + properties cập nhật theo infra thực tế).
  - Tầng 2 (`dedup_grid_near_infra`): xóa grid trong N hex láng giềng
    của infra (mặc định N=1 ⇒ 6 láng giềng đầu tiên).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable

import h3
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.grid import H3Candidate
from services.overpass_client import InfraPoint


# ─────────────────────────────────────────────────────────────────────────────
# Write — Grid candidates
# ─────────────────────────────────────────────────────────────────────────────

async def upsert_candidates_bulk(
    db: AsyncSession,
    aoi_id: uuid.UUID,
    candidates: Iterable[H3Candidate],
    *,
    cost: float = 1.0,
    source: str = "grid",
) -> int:
    """
    Bulk insert grid candidates qua UNNEST.

    Returns: số rows mới insert (đếm qua RETURNING).
    """
    candidates_list = list(candidates)
    if not candidates_list:
        return 0

    h3_resolution = candidates_list[0].h3_resolution
    h3_indices = [c.h3_index for c in candidates_list]
    lats       = [c.lat      for c in candidates_list]
    lngs       = [c.lng      for c in candidates_list]

    result = await db.execute(text("""
        INSERT INTO gateway_candidates
            (aoi_id, h3_index, h3_resolution, location, cost, source)
        SELECT
            CAST(:aoi_id AS uuid),
            u.h3_idx,
            CAST(:h3_resolution AS smallint),
            ST_SetSRID(ST_MakePoint(u.lng, u.lat), 4326),
            CAST(:cost AS numeric),
            :source
        FROM unnest(
            CAST(:h3_indices AS text[]),
            CAST(:lats AS double precision[]),
            CAST(:lngs AS double precision[])
        ) AS u(h3_idx, lat, lng)
        ON CONFLICT (aoi_id, h3_index) DO NOTHING
        RETURNING 1
    """), {
        "aoi_id":        str(aoi_id),
        "h3_resolution": h3_resolution,
        "h3_indices":    h3_indices,
        "lats":          lats,
        "lngs":          lngs,
        "cost":          cost,
        "source":        source,
    })
    inserted = len(result.fetchall())
    await db.commit()
    return inserted


# ─────────────────────────────────────────────────────────────────────────────
# Write — Infra candidates (Phase v3.1 step 4)
# ─────────────────────────────────────────────────────────────────────────────

# Priority khi nhiều infra cùng h3 cell: tower > mast > building
_INFRA_PRIORITY = {"comm_tower": 0, "comm_mast": 1, "tall_building": 2}


def dedup_infra_by_h3(
    infra_points: list[InfraPoint],
    h3_resolution: int,
) -> list[tuple[str, InfraPoint]]:
    """
    Dedup InfraPoints theo h3_index. Mỗi hex giữ infra type ưu tiên cao nhất.
    
    Returns: list of (h3_index, infra_point).
    """
    by_h3: dict[str, InfraPoint] = {}
    for p in infra_points:
        h3_idx   = h3.latlng_to_cell(p.lat, p.lng, h3_resolution)
        existing = by_h3.get(h3_idx)
        if (existing is None
                or _INFRA_PRIORITY[p.infra_type] < _INFRA_PRIORITY[existing.infra_type]):
            by_h3[h3_idx] = p
    return list(by_h3.items())


async def upsert_infra_candidates_bulk(
    db: AsyncSession,
    aoi_id: uuid.UUID,
    infra_with_h3: list[tuple[str, InfraPoint]],   # output của dedup_infra_by_h3
    *,
    h3_resolution: int,
    cost: float = 0.3,
) -> int:
    """
    Bulk insert/override candidates source='infra'.

    ON CONFLICT (aoi_id, h3_index): nếu hex đã có grid candidate → override
    thành infra (cập nhật cost + location chính xác + properties).
    Nếu hex đã có infra → skip (giữ infra hiện tại).

    Returns: số rows được insert hoặc update.
    """
    if not infra_with_h3:
        return 0

    h3_indices = [h3_idx for h3_idx, _ in infra_with_h3]
    lats       = [p.lat  for _, p in infra_with_h3]
    lngs       = [p.lng  for _, p in infra_with_h3]
    properties = [
        json.dumps({
            "osmType":   p.osm_type,
            "osmId":     p.osm_id,
            "infraType": p.infra_type,
            "tags":      p.tags,
        })
        for _, p in infra_with_h3
    ]

    result = await db.execute(text("""
        INSERT INTO gateway_candidates
            (aoi_id, h3_index, h3_resolution, location, cost, source, properties)
        SELECT
            CAST(:aoi_id AS uuid),
            u.h3_idx,
            CAST(:h3_resolution AS smallint),
            ST_SetSRID(ST_MakePoint(u.lng, u.lat), 4326),
            CAST(:cost AS numeric),
            'infra',
            CAST(u.props AS jsonb)
        FROM unnest(
            CAST(:h3_indices AS text[]),
            CAST(:lats AS double precision[]),
            CAST(:lngs AS double precision[]),
            CAST(:properties AS text[])
        ) AS u(h3_idx, lat, lng, props)
        ON CONFLICT (aoi_id, h3_index) DO UPDATE SET
            source     = EXCLUDED.source,
            cost       = EXCLUDED.cost,
            location   = EXCLUDED.location,
            properties = EXCLUDED.properties
        WHERE gateway_candidates.source = 'grid'
        RETURNING 1
    """), {
        "aoi_id":        str(aoi_id),
        "h3_resolution": h3_resolution,
        "h3_indices":    h3_indices,
        "lats":          lats,
        "lngs":          lngs,
        "properties":    properties,
        "cost":          cost,
    })
    affected = len(result.fetchall())
    await db.commit()
    return affected


async def dedup_grid_near_infra(
    db: AsyncSession,
    aoi_id: uuid.UUID,
    *,
    rings: int = 1,
) -> int:
    """
    Xóa grid candidates trong N hex láng giềng của mọi infra candidate.

    Args:
        rings: số ring quanh mỗi infra (1 = 6 láng giềng trực tiếp,
               2 = 18 cells, v.v.). Mặc định 1.

    Returns: số grid candidates bị xóa.
    """
    if rings < 1:
        return 0

    # Fetch tất cả infra h3_indices của AOI
    infra_rows = (await db.execute(text("""
        SELECT h3_index
        FROM gateway_candidates
        WHERE aoi_id = CAST(:aoi_id AS uuid) AND source = 'infra'
    """), {"aoi_id": str(aoi_id)})).all()

    infra_h3s = {r.h3_index for r in infra_rows}
    if not infra_h3s:
        return 0

    # Tính tập hex láng giềng (loại trừ chính các hex infra)
    neighbor_h3s: set[str] = set()
    for h3_idx in infra_h3s:
        neighbor_h3s.update(h3.grid_disk(h3_idx, rings))
    neighbor_h3s -= infra_h3s

    if not neighbor_h3s:
        return 0

    result = await db.execute(text("""
        DELETE FROM gateway_candidates
        WHERE aoi_id = CAST(:aoi_id AS uuid)
          AND source = 'grid'
          AND h3_index = ANY(CAST(:h3_list AS text[]))
    """), {"aoi_id": str(aoi_id), "h3_list": list(neighbor_h3s)})
    await db.commit()
    return result.rowcount


async def delete_candidates_by_aoi(
    db: AsyncSession,
    aoi_id: uuid.UUID,
    *,
    source: str | None = None,
) -> int:
    """
    Xóa candidates của 1 AOI.

    Args:
        source: nếu None → xóa hết. Nếu 'grid'/'infra' → xóa chỉ source đó.
    """
    if source is None:
        result = await db.execute(text("""
            DELETE FROM gateway_candidates WHERE aoi_id = CAST(:aoi_id AS uuid)
        """), {"aoi_id": str(aoi_id)})
    else:
        result = await db.execute(text("""
            DELETE FROM gateway_candidates
            WHERE aoi_id = CAST(:aoi_id AS uuid) AND source = :source
        """), {"aoi_id": str(aoi_id), "source": source})
    await db.commit()
    return result.rowcount


# ─────────────────────────────────────────────────────────────────────────────
# Read
# ─────────────────────────────────────────────────────────────────────────────

async def count_candidates_by_aoi_slug(
    db: AsyncSession,
    aoi_slug: str,
    *,
    source: str | None = None,
) -> int:
    """Count candidates của AOI. Optional filter theo source."""
    sql = """
        SELECT COUNT(*) AS n
        FROM gateway_candidates c
        JOIN aoi_polygons a ON a.id = c.aoi_id
        WHERE a.slug = :slug AND a.deleted_at IS NULL
    """
    params: dict = {"slug": aoi_slug}
    if source is not None:
        sql += " AND c.source = :source"
        params["source"] = source
    row = (await db.execute(text(sql), params)).mappings().first()
    return int(row["n"]) if row else 0


async def list_candidates_by_aoi_slug(
    db: AsyncSession,
    aoi_slug: str,
) -> list[dict]:
    """
    Lấy candidates dạng list[dict] cho optimizer / API output.
    Mỗi dict: {id, h3Index, h3Resolution, lat, lng, cost, source}.
    """
    rows = (await db.execute(text("""
        SELECT
            c.id,
            c.h3_index,
            c.h3_resolution,
            ST_Y(c.location::geometry) AS lat,
            ST_X(c.location::geometry) AS lng,
            c.cost,
            c.source
        FROM gateway_candidates c
        JOIN aoi_polygons a ON a.id = c.aoi_id
        WHERE a.slug = :slug AND a.deleted_at IS NULL
        ORDER BY c.h3_index
    """), {"slug": aoi_slug})).mappings().all()
    return [
        {
            "id":            str(r["id"]),
            "h3Index":       r["h3_index"],
            "h3Resolution":  r["h3_resolution"],
            "lat":           r["lat"],
            "lng":           r["lng"],
            "cost":          float(r["cost"]),
            "source":        r["source"],
        }
        for r in rows
    ]