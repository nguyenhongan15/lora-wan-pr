"""
scripts/coverage_matrix_test.py — Verify coverage matrix end-to-end với data thật.

Read-only test:
  1. Load candidates từ DB (slug=danang)
  2. Load AOI polygons (full + urban) → gen demand on-the-fly
  3. Compute coverage matrix với config Hata + AS923 + SF10 (default Vietnam)
  4. In stats: shape, nnz, density, breakdown timings
  5. Test cache: hit/miss/clear

Không persist gì. Dùng để verify step 6.

Usage:
  docker exec lora_api python scripts/coverage_matrix_test.py
  docker exec lora_api python scripts/coverage_matrix_test.py --sf 12
  docker exec lora_api python scripts/coverage_matrix_test.py --model log_distance
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
from services.candidate_repo import list_candidates_by_aoi_slug
from services.coverage_matrix import (
    CandidatePoint,
    CoverageConfig,
    clear_cache,
    compute_coverage_matrix,
    get_or_compute_coverage_matrix,
)
from services.grid import make_adaptive_demand_grid

logger = logging.getLogger(__name__)


async def _load_polygon(db, slug: str):
    row = (await db.execute(text("""
        SELECT ST_AsText(boundary) AS wkt
        FROM aoi_polygons
        WHERE slug = :slug AND deleted_at IS NULL
    """), {"slug": slug})).mappings().first()
    return wkt_loads(row["wkt"]) if row else None


async def run(
    full_slug:    str,
    urban_slug:   str,
    model:        str,
    sf:           int,
    frequency:    float,
    tx_power:     float,
    tx_height:    float,
) -> int:
    # 1. Load data
    async with AsyncSessionLocal() as db:
        cands_dict = await list_candidates_by_aoi_slug(db, full_slug)
        if not cands_dict:
            print(f"ERROR: chưa có candidates cho slug='{full_slug}'. "
                  f"Chạy candidate_bootstrap.py trước.")
            return 1
        candidates = [
            CandidatePoint(id=c["id"], lat=c["lat"], lng=c["lng"], cost=c["cost"])
            for c in cands_dict
        ]

        full_poly  = await _load_polygon(db, full_slug)
        urban_poly = await _load_polygon(db, urban_slug)

    if full_poly is None:
        print(f"ERROR: AOI '{full_slug}' không tồn tại")
        return 2

    # 2. Generate demand on-the-fly (theo plan v3.1: không persist)
    t = time.perf_counter()
    demand = make_adaptive_demand_grid(full_poly, urban_poly)
    demand_ms = (time.perf_counter() - t) * 1000

    print(f"\n=== Inputs ===")
    print(f"Candidates:   {len(candidates)}  ({sum(1 for c in cands_dict if c['source']=='grid')} grid + "
          f"{sum(1 for c in cands_dict if c['source']=='infra')} infra)")
    print(f"Demand cells: {len(demand)}  ({sum(1 for d in demand if d.density_class=='urban')} urban + "
          f"{sum(1 for d in demand if d.density_class=='rural')} rural)")
    print(f"Demand gen:   {demand_ms:.1f} ms")

    # 3. Build config
    config = CoverageConfig(
        model                = model,
        frequency_mhz        = frequency,
        sf                   = sf,
        tx_power_dbm         = tx_power,
        tx_antenna_height_m  = tx_height,
        rx_antenna_height_m  = 1.5,
        tx_antenna_gain_dbi  = 3.0,
        rx_antenna_gain_dbi  = 2.0,
    )

    print(f"\n=== Config ===")
    print(f"Model:     {config.model}")
    print(f"Frequency: {config.frequency_mhz} MHz")
    print(f"SF:        {config.sf}  (sensitivity ~ {-129 + (10-sf)*3:.1f} dBm at SF{sf})")
    print(f"Tx power:  {config.tx_power_dbm} dBm")
    print(f"Tx height: {config.tx_antenna_height_m} m")
    print(f"R_max:     {config.r_max_m/1000:.0f} km")
    print(f"Hash:      {config.short_hash()}")

    # 4. Compute matrix (không cache — measure raw time)
    print(f"\n=== Compute (no cache) ===")
    t = time.perf_counter()
    matrix = compute_coverage_matrix(
        candidates, demand, config,
        correlation_id="cov_matrix_test_001",
    )
    raw_ms = (time.perf_counter() - t) * 1000

    print(f"Total time:        {raw_ms:.0f} ms")
    print(f"Matrix shape:      {matrix.matrix.shape}")
    print(f"Non-zero entries:  {matrix.matrix.nnz:,}")
    print(f"Density:           {matrix.density * 100:.3f}%")
    print(f"Memory (estimate): {matrix.matrix.data.nbytes / 1024 / 1024:.2f} MB")

    # 5. Test cache
    print(f"\n=== Cache test ===")
    clear_cache()

    t = time.perf_counter()
    m1 = get_or_compute_coverage_matrix(candidates, demand, config)
    miss_ms = (time.perf_counter() - t) * 1000

    t = time.perf_counter()
    m2 = get_or_compute_coverage_matrix(candidates, demand, config)
    hit_ms = (time.perf_counter() - t) * 1000

    print(f"Cache miss (first call):  {miss_ms:.0f} ms")
    print(f"Cache hit  (second call): {hit_ms:.2f} ms  (speedup {miss_ms/max(hit_ms,0.01):.0f}×)")
    print(f"Same object: {m1 is m2}")

    # 6. Sanity check: top 5 candidates by coverage count
    print(f"\n=== Top 5 candidates by demand cells covered ===")
    coverage_per_cand = matrix.matrix.getnnz(axis=1)   # nnz per row
    top5 = coverage_per_cand.argsort()[-5:][::-1]
    for rank, i in enumerate(top5, 1):
        cand_id = matrix.candidate_ids[i][:8]
        n_covered = coverage_per_cand[i]
        cand_lat = candidates[i].lat
        cand_lng = candidates[i].lng
        print(f"  #{rank}  cand={cand_id}…  covers {n_covered:>5} cells  "
              f"@ ({cand_lat:.3f}, {cand_lng:.3f})  cost={candidates[i].cost:.2f}")

    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="coverage_matrix_test",
        description="Verify coverage matrix step 6 (read-only, không persist).",
    )
    p.add_argument("--full-slug",  default="danang")
    p.add_argument("--urban-slug", default="danang_urban")
    p.add_argument("--model", default="hata", choices=["hata", "log_distance"])
    p.add_argument("--sf", type=int, default=10, choices=[7, 8, 9, 10, 11, 12])
    p.add_argument("--frequency", type=float, default=923.0,
                   help="MHz (Vietnam dùng AS923)")
    p.add_argument("--tx-power", type=float, default=17.0,
                   help="dBm (AS923 max gateway 24 dBm)")
    p.add_argument("--tx-height", type=float, default=30.0,
                   help="meters")
    return p.parse_args()


def main() -> int:
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
    args = parse_args()
    return asyncio.run(run(
        full_slug  = args.full_slug,
        urban_slug = args.urban_slug,
        model      = args.model,
        sf         = args.sf,
        frequency  = args.frequency,
        tx_power   = args.tx_power,
        tx_height  = args.tx_height,
    ))


if __name__ == "__main__":
    sys.exit(main())