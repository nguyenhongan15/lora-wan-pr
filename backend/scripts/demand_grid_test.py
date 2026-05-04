"""
scripts/demand_grid_test.py — Verify adaptive demand grid generation.

Read-only test. Load 2 AOI từ DB → gen demand grid → in stats.
Không persist gì hết.

Usage:
  docker exec lora_api python scripts/demand_grid_test.py
  docker exec lora_api python scripts/demand_grid_test.py --urban-h3-res 8 --rural-h3-res 7
  docker exec lora_api python scripts/demand_grid_test.py --no-urban   # uniform rural toàn AOI
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time

from shapely.wkt import loads as wkt_loads
from sqlalchemy import text

sys.path.insert(0, ".")

from database import AsyncSessionLocal
from services.grid import (
    RURAL_H3_RESOLUTION_DEFAULT,
    URBAN_H3_RESOLUTION_DEFAULT,
    make_adaptive_demand_grid,
)

logger = logging.getLogger(__name__)


async def _load_polygon(db, slug: str):
    row = (await db.execute(text("""
        SELECT ST_AsText(boundary) AS wkt
        FROM aoi_polygons
        WHERE slug = :slug AND deleted_at IS NULL
    """), {"slug": slug})).mappings().first()
    if not row:
        return None
    return wkt_loads(row["wkt"])


async def run(
    full_slug:     str,
    urban_slug:    str | None,
    urban_h3_res:  int,
    rural_h3_res:  int,
) -> int:
    async with AsyncSessionLocal() as db:
        full_poly = await _load_polygon(db, full_slug)
        if full_poly is None:
            logger.error("demand_test.full_aoi_not_found", extra={"slug": full_slug})
            return 1

        urban_poly = None
        if urban_slug:
            urban_poly = await _load_polygon(db, urban_slug)
            if urban_poly is None:
                logger.error(
                    "demand_test.urban_aoi_not_found",
                    extra={"slug": urban_slug,
                           "hint": "Chạy urban_aoi_bootstrap.py trước"},
                )
                return 2

    # Generate adaptive grid
    t0 = time.perf_counter()
    cells = make_adaptive_demand_grid(
        full_poly, urban_poly,
        urban_h3_res=urban_h3_res,
        rural_h3_res=rural_h3_res,
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000

    urban_cells = [c for c in cells if c.density_class == "urban"]
    rural_cells = [c for c in cells if c.density_class == "rural"]

    print(f"\n=== Adaptive demand grid stats ===")
    print(f"Generation time: {elapsed_ms:.1f} ms")
    print(f"Total demand cells: {len(cells)}")
    print(f"  Urban (res {urban_h3_res}): {len(urban_cells)}")
    print(f"  Rural (res {rural_h3_res}): {len(rural_cells)}")

    if urban_cells:
        print(f"\nSample urban cells:")
        for c in urban_cells[:3]:
            print(f"  h3={c.h3_index} lat={c.lat:.4f} lng={c.lng:.4f} weight={c.weight}")

    if rural_cells:
        print(f"\nSample rural cells:")
        for c in rural_cells[:3]:
            print(f"  h3={c.h3_index} lat={c.lat:.4f} lng={c.lng:.4f} weight={c.weight}")
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="demand_grid_test",
        description="Verify adaptive demand grid (read-only, không persist).",
    )
    p.add_argument("--full-slug", default="danang", help='Full AOI slug')
    p.add_argument("--urban-slug", default="danang_urban", help='Urban AOI slug')
    p.add_argument("--no-urban", action="store_true",
                   help="Skip urban polygon → uniform rural toàn AOI")
    p.add_argument("--urban-h3-res", type=int, default=URBAN_H3_RESOLUTION_DEFAULT,
                   help=f"Urban H3 resolution (default {URBAN_H3_RESOLUTION_DEFAULT})")
    p.add_argument("--rural-h3-res", type=int, default=RURAL_H3_RESOLUTION_DEFAULT,
                   help=f"Rural H3 resolution (default {RURAL_H3_RESOLUTION_DEFAULT})")
    return p.parse_args()


def main() -> int:
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
    args = parse_args()
    return asyncio.run(run(
        full_slug    = args.full_slug,
        urban_slug   = None if args.no_urban else args.urban_slug,
        urban_h3_res = args.urban_h3_res,
        rural_h3_res = args.rural_h3_res,
    ))


if __name__ == "__main__":
    sys.exit(main())