"""
scripts/urban_aoi_bootstrap.py — Bootstrap urban AOI = union các phường (admin_level=8).

Bối cảnh: sau hợp nhất 1/7/2025, "Đà Nẵng cũ" không tồn tại như entity OSM
riêng. Urban được approximate = union of admin_level=8 polygons matching name
prefix "Phường " bên trong AOI cha.

Sử dụng làm urban polygon cho adaptive demand grid (200m urban + 1km rural).

Idempotent: re-run UPSERT theo target slug.

Usage:
  # Default — phường admin_level=8
  docker exec lora_api python scripts/urban_aoi_bootstrap.py

  # Debug — list tất cả admin_level=N có trong parent (không persist)
  docker exec lora_api python scripts/urban_aoi_bootstrap.py --list-names
  docker exec lora_api python scripts/urban_aoi_bootstrap.py --list-names --admin-level 6

  # Custom prefix / level
  docker exec lora_api python scripts/urban_aoi_bootstrap.py --admin-level 6 --name-prefix "Quận "

  # No filter (lấy tất cả ở admin_level chỉ định) — nargs='?' cho phép standalone
  docker exec lora_api python scripts/urban_aoi_bootstrap.py --name-prefix
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union
from shapely.wkt import dumps as wkt_dumps

# Cho phép chạy từ /app trong container
sys.path.insert(0, ".")

from database import AsyncSessionLocal
from services.aoi_repo import get_aoi_by_slug, upsert_aoi
from services.overpass_client import (
    OverpassError,
    fetch_sub_admin_polygons,
)

logger = logging.getLogger(__name__)

DEFAULT_PARENT_SLUG = "danang"
DEFAULT_TARGET_SLUG = "danang_urban"
DEFAULT_TARGET_NAME = "Đà Nẵng đô thị"
DEFAULT_NAME_PREFIX = "Phường "
DEFAULT_ADMIN_LEVEL = 6


async def _resolve_parent(db, parent_slug: str) -> dict | None:
    parent = await get_aoi_by_slug(db, parent_slug)
    if not parent:
        logger.error(
            "urban_bootstrap.parent_not_found",
            extra={"parentSlug": parent_slug,
                   "hint": "Chạy aoi_bootstrap.py trước"},
        )
        return None
    if parent["osm_relation_id"] is None:
        logger.error(
            "urban_bootstrap.parent_no_relation_id",
            extra={"parentSlug": parent_slug},
        )
        return None
    return parent


async def run_list_names(parent_slug: str, admin_level: int) -> int:
    """Debug mode: in tất cả admin_level=N relations, không persist."""
    async with AsyncSessionLocal() as db:
        parent = await _resolve_parent(db, parent_slug)
        if parent is None:
            return 1

        try:
            sub_polys = await fetch_sub_admin_polygons(
                parent_relation_id = parent["osm_relation_id"],
                admin_level        = admin_level,
                name_prefix        = "",   # không filter
            )
        except OverpassError as e:
            logger.error("urban_bootstrap.fetch_failed", extra={"error": str(e)})
            return 2

        # In sorted by name để dễ scan
        for sp in sorted(sub_polys, key=lambda x: x.name):
            print(f"  admin_level={admin_level}  osm_id={sp.osm_relation_id}  name={sp.name!r}")
        print(f"\nTotal: {len(sub_polys)} relations ở admin_level={admin_level}")
    return 0


async def run(
    parent_slug:  str,
    target_slug:  str,
    target_name:  str,
    name_prefix:  str,
    admin_level:  int,
) -> int:
    async with AsyncSessionLocal() as db:
        parent = await _resolve_parent(db, parent_slug)
        if parent is None:
            return 1

        # Fetch sub-polygons
        try:
            sub_polys = await fetch_sub_admin_polygons(
                parent_relation_id = parent["osm_relation_id"],
                admin_level        = admin_level,
                name_prefix        = name_prefix,
            )
        except OverpassError as e:
            logger.error("urban_bootstrap.fetch_failed", extra={"error": str(e)})
            return 2

        if not sub_polys:
            logger.error(
                "urban_bootstrap.no_polygons_matched",
                extra={
                    "parentSlug":  parent_slug,
                    "adminLevel":  admin_level,
                    "namePrefix":  name_prefix,
                    "hint": ('Chạy --list-names --admin-level <N> '
                             'để xem OSM có gì'),
                },
            )
            return 3

        # Union all polygons
        polygons = [sp.polygon for sp in sub_polys]
        union = unary_union(polygons)

        if isinstance(union, Polygon):
            union = MultiPolygon([union])
        elif not isinstance(union, MultiPolygon):
            logger.error(
                "urban_bootstrap.unexpected_union_type",
                extra={"type": type(union).__name__},
            )
            return 4

        wkt = wkt_dumps(union)

        # Upsert
        component_names = sorted(sp.name for sp in sub_polys)
        properties = {
            "synthetic":           True,
            "compositionMethod":   "unary_union_of_admin_level",
            "parentSlug":          parent_slug,
            "parentRelationId":    parent["osm_relation_id"],
            "componentAdminLevel": admin_level,
            "componentNamePrefix": name_prefix,
            "componentCount":      len(sub_polys),
            "componentNames":      component_names,
        }

        aoi_id = await upsert_aoi(
            db,
            slug             = target_slug,
            name             = target_name,
            admin_level      = admin_level,
            osm_relation_id  = None,
            boundary_wkt     = wkt,
            properties       = properties,
        )

        area_km2 = union.area * (111.0 ** 2)

        logger.info(
            "urban_bootstrap.done",
            extra={
                "targetSlug":      target_slug,
                "aoiId":           str(aoi_id),
                "componentCount":  len(sub_polys),
                "polygonCount":    len(union.geoms),
                "approxAreaKm2":   round(area_km2, 1),
            },
        )
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="urban_aoi_bootstrap",
        description="Bootstrap urban AOI = union các polygon admin_level=N inside parent.",
    )
    p.add_argument(
        "--parent-slug", default=DEFAULT_PARENT_SLUG,
        help=f'Slug của AOI cha (default: "{DEFAULT_PARENT_SLUG}")',
    )
    p.add_argument(
        "--target-slug", default=DEFAULT_TARGET_SLUG,
        help=f'Slug của urban AOI (default: "{DEFAULT_TARGET_SLUG}")',
    )
    p.add_argument(
        "--target-name", default=DEFAULT_TARGET_NAME,
        help=f'Hiển thị name (default: "{DEFAULT_TARGET_NAME}")',
    )
    # nargs='?' const="" cho phép `--name-prefix` standalone (no value) → ""
    # Tránh lỗi PowerShell không pass empty string được
    p.add_argument(
        "--name-prefix", default=DEFAULT_NAME_PREFIX,
        nargs="?", const="",
        help=(f'Filter name prefix (default: "{DEFAULT_NAME_PREFIX}"). '
              'Pass --name-prefix (không value) để bỏ filter.'),
    )
    p.add_argument(
        "--admin-level", type=int, default=DEFAULT_ADMIN_LEVEL,
        help=(f"OSM admin_level (default: {DEFAULT_ADMIN_LEVEL} = phường/xã); "
              "thử 6 nếu OSM còn dùng cấu trúc cũ (quận)."),
    )
    p.add_argument(
        "--list-names", action="store_true",
        help="Debug: in tất cả admin_level=N relations (không filter, không persist).",
    )
    return p.parse_args()


def main() -> int:
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
    args = parse_args()
    if args.list_names:
        return asyncio.run(run_list_names(
            parent_slug = args.parent_slug,
            admin_level = args.admin_level,
        ))
    return asyncio.run(run(
        parent_slug = args.parent_slug,
        target_slug = args.target_slug,
        target_name = args.target_name,
        name_prefix = args.name_prefix,
        admin_level = args.admin_level,
    ))


if __name__ == "__main__":
    sys.exit(main())