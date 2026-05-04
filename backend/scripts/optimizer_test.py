"""
scripts/optimizer_test.py — Verify greedy MCLP/LSCP + DB persistence.

Phase v3.1 step 7.

Test scenarios:
  1. Load candidates + AOI + demand → compute coverage matrix
  2. Run MCLP với K = 5, 10, 20 → so sánh coverage_ratio + cost
  3. Run LSCP với target = 0.5, 0.8, 0.95 → so sánh K_needed
  4. Persist 1 result vào DB
  5. Retrieve theo ID, verify match
  6. List runs by AOI slug
  7. Soft-delete + verify

Usage:
  docker exec lora_api python scripts/optimizer_test.py
  docker exec lora_api python scripts/optimizer_test.py --no-persist
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

import numpy as np

from database import AsyncSessionLocal
from services.candidate_repo import list_candidates_by_aoi_slug
from services.coverage_matrix import (
    CandidatePoint,
    CoverageConfig,
    compute_coverage_matrix,
)
from services.coverage_optimizer import solve_lscp, solve_mclp
from services.grid import make_adaptive_demand_grid
from services.optimization_repo import (
    get_optimization_run,
    list_optimization_runs_by_aoi_slug,
    save_optimization_run,
    soft_delete_optimization_run,
)


async def _load_polygon(db, slug: str):
    row = (await db.execute(text("""
        SELECT ST_AsText(boundary) AS wkt
        FROM aoi_polygons
        WHERE slug = :slug AND deleted_at IS NULL
    """), {"slug": slug})).mappings().first()
    return wkt_loads(row["wkt"]) if row else None


async def _load_aoi_id(db, slug: str) -> str | None:
    row = (await db.execute(text("""
        SELECT id::text AS id
        FROM aoi_polygons
        WHERE slug = :slug AND deleted_at IS NULL
    """), {"slug": slug})).mappings().first()
    return row["id"] if row else None


async def run(persist: bool, full_slug: str, urban_slug: str) -> int:
    correlation_id = f"opt_test_{int(time.time())}"

    # 1. Load inputs
    async with AsyncSessionLocal() as db:
        cands_dict = await list_candidates_by_aoi_slug(db, full_slug)
        if not cands_dict:
            print(f"ERROR: chưa có candidates cho '{full_slug}'.")
            return 1
        candidates = [
            CandidatePoint(id=c["id"], lat=c["lat"], lng=c["lng"], cost=c["cost"])
            for c in cands_dict
        ]
        full_poly  = await _load_polygon(db, full_slug)
        urban_poly = await _load_polygon(db, urban_slug)
        aoi_id     = await _load_aoi_id(db, full_slug)

    if full_poly is None or aoi_id is None:
        print(f"ERROR: AOI '{full_slug}' không tồn tại")
        return 2

    demand = make_adaptive_demand_grid(full_poly, urban_poly)

    print(f"\n=== Inputs ===")
    print(f"AOI:        {full_slug} (id={aoi_id[:8]}…)")
    print(f"Candidates: {len(candidates)}")
    print(f"Demand:     {len(demand)}")

    # 2. Compute coverage matrix (Hata + AS923 + SF12)
    config = CoverageConfig(
        model="hata", frequency_mhz=923.0, sf=12,
        tx_power_dbm=17.0, tx_antenna_height_m=30.0,
        rx_antenna_height_m=1.5,
        tx_antenna_gain_dbi=3.0, rx_antenna_gain_dbi=2.0,
    )
    matrix = compute_coverage_matrix(
        candidates, demand, config, correlation_id=correlation_id,
    )
    costs = np.array([c.cost for c in candidates], dtype=np.float64)

    print(f"Matrix:     {matrix.matrix.shape}, nnz={matrix.matrix.nnz:,}")
    print(f"Config:     {config.model} SF{config.sf} {config.frequency_mhz}MHz "
          f"hash={config.short_hash()}")

    # 3. MCLP scan K = 5, 10, 20
    print(f"\n=== MCLP (cost-aware greedy) ===")
    print(f"  K  | selected | coverage_ratio | total_cost | iters | compute_ms")
    print(f"  ---|----------|----------------|------------|-------|-----------")
    last_mclp_result = None
    for k in [5, 10, 20]:
        r = solve_mclp(matrix, costs, k_max=k, correlation_id=correlation_id)
        print(f"  {k:>2} | {r.n_selected:>8} | "
              f"{r.coverage_ratio:>14.4f} | "
              f"{r.total_cost:>10.3f} | "
              f"{r.n_iterations:>5} | "
              f"{r.compute_ms:>10.1f}")
        last_mclp_result = r

    # Top 5 selections của lần MCLP cuối (K=20)
    print(f"\n  Top 5 selected (K=20):")
    for s in last_mclp_result.selections[:5]:
        print(f"    rank={s.rank}  cand={s.candidate_id[:8]}…  "
              f"gain={s.marginal_gain:>10.3f}  cost={s.cost:.2f}")

    # 4. LSCP scan target = 0.5, 0.8, 0.95
    print(f"\n=== LSCP (target coverage, cost-aware) ===")
    print(f"  target | K_needed | achieved | total_cost | compute_ms")
    print(f"  -------|----------|----------|------------|-----------")
    for tgt in [0.5, 0.8, 0.95]:
        r = solve_lscp(
            matrix, costs,
            target_coverage=tgt, k_safety_max=100,
            correlation_id=correlation_id,
        )
        unreachable = "⚠ " if r.coverage_ratio < tgt else "  "
        print(f"  {unreachable}{tgt:>4.2f} | "
              f"{r.n_selected:>8} | "
              f"{r.coverage_ratio:>8.4f} | "
              f"{r.total_cost:>10.3f} | "
              f"{r.compute_ms:>10.1f}")

    # 5. Persist + retrieve test
    if not persist:
        print(f"\n--no-persist → bỏ qua DB tests.")
        return 0

    print(f"\n=== Persistence test ===")
    async with AsyncSessionLocal() as db:
        # Save MCLP K=10 result
        r = solve_mclp(matrix, costs, k_max=10, correlation_id=correlation_id)
        run_id = await save_optimization_run(
            db,
            aoi_id          = aoi_id,
            mode            = "mclp",
            k_max           = 10,
            target_coverage = None,
            cost_aware      = True,
            coverage_config = config,
            result          = r,
            correlation_id  = correlation_id,
            notes           = "optimizer_test.py — MCLP K=10 baseline",
        )
        print(f"Saved run: {run_id}")

        # Retrieve
        row = await get_optimization_run(db, run_id)
        assert row is not None, "get_optimization_run returned None"
        assert row["mode"] == "mclp"
        assert row["k_max"] == 10
        assert row["n_selected"] == r.n_selected
        assert abs(float(row["coverage_ratio"]) - r.coverage_ratio) < 1e-4
        print(f"Retrieved: mode={row['mode']} k_max={row['k_max']} "
              f"n_selected={row['n_selected']} "
              f"coverage_ratio={float(row['coverage_ratio']):.4f}")
        print(f"Selection_details has {len(row['selection_details'])} entries")
        first_sel = row["selection_details"][0]
        print(f"  First: rank={first_sel['rank']} h3={first_sel['h3Index']} "
              f"@({first_sel['lat']:.3f},{first_sel['lng']:.3f}) "
              f"src={first_sel['source']}")

        # List by AOI
        runs = await list_optimization_runs_by_aoi_slug(db, full_slug, limit=5)
        print(f"\nRecent runs for '{full_slug}': {len(runs)}")
        for r2 in runs[:3]:
            mode_display = (
                f"K={r2['k_max']}" if r2["mode"] == "mclp"
                else f"tgt={float(r2['target_coverage']):.2f}"
            )
            print(f"  {r2['id'][:8]}… {r2['mode']} {mode_display} "
                  f"n={r2['n_selected']} "
                  f"cov={float(r2['coverage_ratio']):.4f} "
                  f"cost={float(r2['total_cost']):.2f}")

        # Soft-delete
        deleted = await soft_delete_optimization_run(
            db, run_id, correlation_id=correlation_id,
        )
        print(f"\nSoft-delete: {deleted}")

        # Verify gone
        row_after = await get_optimization_run(db, run_id)
        assert row_after is None, "soft-delete không hoạt động đúng"
        print(f"Verified: run no longer accessible after soft-delete ✓")

    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="optimizer_test",
        description="Verify greedy MCLP/LSCP + DB persistence (step 7).",
    )
    p.add_argument("--full-slug",  default="danang")
    p.add_argument("--urban-slug", default="danang_urban")
    p.add_argument("--no-persist", action="store_true",
                   help="Skip DB save/retrieve/delete tests")
    return p.parse_args()


def main() -> int:
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
    args = parse_args()
    return asyncio.run(run(
        persist    = not args.no_persist,
        full_slug  = args.full_slug,
        urban_slug = args.urban_slug,
    ))


if __name__ == "__main__":
    sys.exit(main())