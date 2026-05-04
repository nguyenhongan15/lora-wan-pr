"""
scripts/aoi_bootstrap.py — Admin task fetch AOI từ OSM Overpass → DB.

12-Factor F12: chạy trong cùng container với same codebase + config.
Idempotent: re-run → UPSERT theo slug.

Usage (mặc định Đà Nẵng):
  docker exec lora_api python scripts/aoi_bootstrap.py danang

  docker exec lora_api python scripts/aoi_bootstrap.py danang \\
      --name "Đà Nẵng" --admin-level 4 --osm-relation-id 2095400

  docker exec lora_api python scripts/aoi_bootstrap.py haichau \\
      --name "Hải Châu" --admin-level 6
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from shapely.wkt import dumps as wkt_dumps

# Cho phép chạy `python scripts/aoi_bootstrap.py` từ /app trong container
sys.path.insert(0, ".")

from database import AsyncSessionLocal
from services.aoi_repo import upsert_aoi
from services.overpass_client import OverpassError, fetch_admin_polygon

logger = logging.getLogger(__name__)


# Defaults: Đà Nẵng (admin_level=4 = TP TW, OSM relation 2095400)
DEFAULT_NAME            = "Đà Nẵng"
DEFAULT_ADMIN_LEVEL     = 4
DEFAULT_OSM_RELATION_ID = 1891418


async def run(
    slug: str,
    name: str,
    admin_level: int,
    osm_relation_id: int | None,
) -> int:
    try:
        polygon, metadata = await fetch_admin_polygon(
            name, admin_level, osm_relation_id=osm_relation_id,
        )
    except OverpassError as e:
        logger.error("aoi_bootstrap.fetch_failed", extra={"error": str(e)})
        return 1

    wkt = wkt_dumps(polygon)

    async with AsyncSessionLocal() as db:
        aoi_id = await upsert_aoi(
            db,
            slug             = slug,
            name             = name,
            admin_level      = admin_level,
            osm_relation_id  = metadata.get("osmRelationId") or osm_relation_id,
            boundary_wkt     = wkt,
            properties       = metadata.get("tags", {}),
        )

    # Diện tích ước lượng (degree² × 111km/° squared at Đà Nẵng latitude ~16°)
    # — chỉ để log sanity check, không phải tính toán chính xác.
    area_km2 = polygon.area * (111.0 ** 2)

    logger.info(
        "aoi_bootstrap.done",
        extra={
            "slug":          slug,
            "aoiId":         str(aoi_id),
            "polygonCount":  len(polygon.geoms),
            "approxAreaKm2": round(area_km2, 1),
        },
    )
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="aoi_bootstrap",
        description="Bootstrap AOI polygon từ OSM Overpass vào DB.",
    )
    p.add_argument("slug", help='Slug để lookup (vd: "danang", "haichau")')
    p.add_argument(
        "--name", default=DEFAULT_NAME,
        help=f'OSM "name" tag (default: "{DEFAULT_NAME}")',
    )
    p.add_argument(
        "--admin-level", type=int, default=DEFAULT_ADMIN_LEVEL,
        help=f"OSM admin_level (default: {DEFAULT_ADMIN_LEVEL} = tỉnh/TP TW)",
    )
    p.add_argument(
        "--osm-relation-id", type=int, default=DEFAULT_OSM_RELATION_ID,
        help=(f"OSM relation ID (default: {DEFAULT_OSM_RELATION_ID} = Đà Nẵng); "
              "ưu tiên hơn --name khi cả hai cùng có"),
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
        slug            = args.slug,
        name            = args.name,
        admin_level     = args.admin_level,
        osm_relation_id = args.osm_relation_id,
    ))


if __name__ == "__main__":
    sys.exit(main())