"""
scripts/candidate_bootstrap.py — Admin task generate H3 hex candidates cho AOI.

12-Factor F12: chạy trong cùng container.
Idempotent (default): ON CONFLICT skip duplicates.
Replace mode: --replace để xóa hết rồi regenerate.

Usage:
  docker exec lora_api python scripts/candidate_bootstrap.py danang
  docker exec lora_api python scripts/candidate_bootstrap.py danang --h3-resolution 7
  docker exec lora_api python scripts/candidate_bootstrap.py danang --replace
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from shapely.wkt import loads as wkt_loads
from sqlalchemy import text

# Cho phép chạy từ /app trong container
sys.path.insert(0, ".")

from database import AsyncSessionLocal
from services.candidate_repo import (
    count_candidates_by_aoi_slug,
    delete_candidates_by_aoi,
    upsert_candidates_bulk,
)
from services.grid import H3_DEFAULT_RESOLUTION, make_h3_candidates

logger = logging.getLogger(__name__)


async def run(slug: str, h3_resolution: int, replace: bool) -> int:
    async with AsyncSessionLocal() as db:
        # Load AOI by slug — dùng WKT để dễ parse hơn EWKB
        row = (await db.execute(text("""
            SELECT id, name, ST_AsText(boundary) AS boundary_wkt
            FROM aoi_polygons
            WHERE slug = :slug AND deleted_at IS NULL
        """), {"slug": slug})).mappings().first()

        if not row:
            logger.error(
                "candidate_bootstrap.aoi_not_found", extra={"slug": slug},
            )
            return 1

        aoi_id  = row["id"]
        polygon = wkt_loads(row["boundary_wkt"])

        if replace:
            deleted = await delete_candidates_by_aoi(db, aoi_id)
            logger.info(
                "candidate_bootstrap.deleted_old",
                extra={"slug": slug, "count": deleted},
            )

        candidates = make_h3_candidates(polygon, h3_resolution)
        logger.info(
            "candidate_bootstrap.generated",
            extra={
                "slug":          slug,
                "h3Resolution":  h3_resolution,
                "totalCells":    len(candidates),
            },
        )

        inserted = await upsert_candidates_bulk(db, aoi_id, candidates)
        total    = await count_candidates_by_aoi_slug(db, slug)

        logger.info(
            "candidate_bootstrap.done",
            extra={
                "slug":      slug,
                "inserted":  inserted,
                "skipped":   len(candidates) - inserted,
                "totalInDb": total,
            },
        )
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="candidate_bootstrap",
        description="Generate H3 hex candidates cho 1 AOI.",
    )
    p.add_argument("slug", help='AOI slug (vd: "danang")')
    p.add_argument(
        "--h3-resolution", type=int, default=H3_DEFAULT_RESOLUTION,
        help=(f"H3 resolution 0-15 (default: {H3_DEFAULT_RESOLUTION} = ~1.2km cạnh). "
              "5=9km, 6=3.2km, 7=1.2km, 8=460m, 9=170m"),
    )
    p.add_argument(
        "--replace", action="store_true",
        help="Xóa candidates cũ trước khi generate (default: chỉ skip duplicates)",
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
        replace       = args.replace,
    ))


if __name__ == "__main__":
    sys.exit(main())