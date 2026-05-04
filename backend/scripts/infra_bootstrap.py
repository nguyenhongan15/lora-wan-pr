"""
scripts/infra_bootstrap.py — Generate infra-derived candidates từ OSM Overpass.

12-Factor F12 admin task. Chạy SAU candidate_bootstrap.py:
  1. candidate_bootstrap.py danang   ← grid (~7000 cells, cost=1.0)
  2. infra_bootstrap.py danang       ← + infra (cost=0.3) + dedup grid

Pipeline:
  a. Load AOI + polygon từ DB
  b. Compute bbox → fetch OSM infra (tower/mast/tall building)
  c. Filter post-fetch theo polygon AOI (loại điểm ngoài, do bbox > polygon)
  d. Compute h3_index per infra → dedup theo priority (tower > mast > building)
  e. Upsert (override grid trong cùng hex)
  f. Dedup grid trong N hex láng giềng (default rings=1 = 6 neighbors)

Idempotent: re-run an toàn — ON CONFLICT chỉ override grid → infra,
infra → infra giữ nguyên.

Usage:
  docker exec lora_api python scripts/infra_bootstrap.py danang
  docker exec lora_api python scripts/infra_bootstrap.py danang --dedup-rings 0   # tắt neighbor dedup
  docker exec lora_api python scripts/infra_bootstrap.py danang --replace-infra   # xóa infra cũ trước
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from shapely.geometry import Point
from shapely.prepared import prep
from shapely.wkt import loads as wkt_loads
from sqlalchemy import text

# Cho phép chạy từ /app trong container
sys.path.insert(0, ".")

from database import AsyncSessionLocal
from services.candidate_repo import (
    count_candidates_by_aoi_slug,
    dedup_grid_near_infra,
    dedup_infra_by_h3,
    delete_candidates_by_aoi,
    upsert_infra_candidates_bulk,
)
from services.overpass_client import (
    OverpassError,
    fetch_infrastructure,
)

logger = logging.getLogger(__name__)


async def run(
    slug: str,
    h3_resolution: int | None,
    dedup_rings: int,
    replace_infra: bool,
    min_levels: int,
    min_height_m: float,
) -> int:
    async with AsyncSessionLocal() as db:
        # ── a. Load AOI ────────────────────────────────────────────────
        row = (await db.execute(text("""
            SELECT id, name, ST_AsText(boundary) AS boundary_wkt
            FROM aoi_polygons
            WHERE slug = :slug AND deleted_at IS NULL
        """), {"slug": slug})).mappings().first()

        if not row:
            logger.error("infra_bootstrap.aoi_not_found", extra={"slug": slug})
            return 1

        aoi_id  = row["id"]
        polygon = wkt_loads(row["boundary_wkt"])

        # Auto-detect h3_resolution từ grid candidates đã có
        if h3_resolution is None:
            res_row = (await db.execute(text("""
                SELECT h3_resolution FROM gateway_candidates
                WHERE aoi_id = CAST(:aoi_id AS uuid) AND source = 'grid'
                LIMIT 1
            """), {"aoi_id": str(aoi_id)})).mappings().first()
            if res_row is None:
                logger.error(
                    "infra_bootstrap.no_grid_candidates",
                    extra={"slug": slug,
                           "hint": "Chạy candidate_bootstrap.py trước"},
                )
                return 1
            h3_resolution = res_row["h3_resolution"]

        if replace_infra:
            deleted = await delete_candidates_by_aoi(db, aoi_id, source="infra")
            logger.info(
                "infra_bootstrap.deleted_old_infra",
                extra={"slug": slug, "count": deleted},
            )

        # ── b. Fetch OSM infra theo bbox ───────────────────────────────
        min_lng, min_lat, max_lng, max_lat = polygon.bounds   # shapely (minx,miny,maxx,maxy)
        try:
            infra_points = await fetch_infrastructure(
                bbox = (min_lat, min_lng, max_lat, max_lng),
                min_building_levels   = min_levels,
                min_building_height_m = min_height_m,
            )
        except OverpassError as e:
            logger.error("infra_bootstrap.fetch_failed", extra={"error": str(e)})
            return 2

        # ── c. Filter post-fetch theo polygon (bbox > polygon) ─────────
        prepared_polygon = prep(polygon)
        infra_in_aoi = [
            p for p in infra_points
            if prepared_polygon.contains(Point(p.lng, p.lat))
        ]
        logger.info(
            "infra_bootstrap.polygon_filtered",
            extra={
                "fetchedCount":  len(infra_points),
                "insideAoi":     len(infra_in_aoi),
            },
        )

        # ── d. Dedup theo h3_index + priority ──────────────────────────
        infra_with_h3 = dedup_infra_by_h3(infra_in_aoi, h3_resolution)
        logger.info(
            "infra_bootstrap.h3_deduped",
            extra={
                "beforeDedup": len(infra_in_aoi),
                "afterDedup":  len(infra_with_h3),
            },
        )

        # ── e. Upsert (ON CONFLICT override grid) ──────────────────────
        affected = await upsert_infra_candidates_bulk(
            db, aoi_id, infra_with_h3, h3_resolution=h3_resolution,
        )
        logger.info(
            "infra_bootstrap.upserted",
            extra={
                "totalProvided":   len(infra_with_h3),
                "insertOrOverride": affected,
            },
        )

        # ── f. Dedup grid trong N hex láng giềng infra ─────────────────
        grid_deleted = 0
        if dedup_rings > 0:
            grid_deleted = await dedup_grid_near_infra(
                db, aoi_id, rings=dedup_rings,
            )

        # ── Final counts ───────────────────────────────────────────────
        total_grid  = await count_candidates_by_aoi_slug(db, slug, source="grid")
        total_infra = await count_candidates_by_aoi_slug(db, slug, source="infra")
        logger.info(
            "infra_bootstrap.done",
            extra={
                "slug":            slug,
                "h3Resolution":    h3_resolution,
                "dedupRings":      dedup_rings,
                "gridDeleted":     grid_deleted,
                "totalGrid":       total_grid,
                "totalInfra":      total_infra,
                "totalCandidates": total_grid + total_infra,
            },
        )
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="infra_bootstrap",
        description="Generate infra-derived candidates từ OSM + dedup grid.",
    )
    p.add_argument("slug", help='AOI slug (vd: "danang")')
    p.add_argument(
        "--h3-resolution", type=int, default=None,
        help="H3 resolution (default: auto-detect từ grid candidates đã có)",
    )
    p.add_argument(
        "--dedup-rings", type=int, default=1,
        help=("Số ring láng giềng để xóa grid quanh infra (default: 1 = 6 hex). "
              "Set 0 để tắt neighbor dedup, chỉ giữ same-hex override."),
    )
    p.add_argument(
        "--replace-infra", action="store_true",
        help="Xóa infra candidates cũ trước khi import (default: skip duplicates)",
    )
    p.add_argument(
        "--min-levels", type=int, default=6,
        help="Ngưỡng building:levels để coi là 'tall' (default: 6)",
    )
    p.add_argument(
        "--min-height-m", type=float, default=18.0,
        help="Ngưỡng height (m) để coi là 'tall' (default: 18.0)",
    )
    return p.parse_args()


def main() -> int:
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
    args = parse_args()
    return asyncio.run(run(
        slug          = args.slug,
        h3_resolution = args.h3_resolution,
        dedup_rings   = args.dedup_rings,
        replace_infra = args.replace_infra,
        min_levels    = args.min_levels,
        min_height_m  = args.min_height_m,
    ))


if __name__ == "__main__":
    sys.exit(main())