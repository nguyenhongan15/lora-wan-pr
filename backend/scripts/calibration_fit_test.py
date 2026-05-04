"""
scripts/calibration_fit_test.py — Verify path-loss calibration end-to-end.

Phase v3.1 step 1.5.x — Option C (disabled by default, strict physics).

Test flow:
  1. Fit urban gộp tất cả SF + gateway quality filter
  2. Fit urban per SF (12, 10) — verify per-SF strategy
  3. Fit rural (no data → expect None)
  4. IF có CalibrationResult với n in physics range:
       persist với activate=False, verify Option C behavior
     ELSE:
       skip persist, log "Framework ready, data quality not sufficient"

Usage:
  docker exec lora_api python scripts/calibration_fit_test.py
  docker exec lora_api python scripts/calibration_fit_test.py --no-persist
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time

sys.path.insert(0, ".")

from database import AsyncSessionLocal
from services.calibration_fit import (
    CalibrationFilters,
    CalibrationResult,
    fit_path_loss,
    N_PATH_LOSS_MIN,
    N_PATH_LOSS_MAX,
)
from services.calibration_repo import (
    get_active_calibration,
    get_calibration,
    list_calibrations,
    save_calibration,
    set_active_calibration,
    soft_delete_calibration,
)
from services.calibration_cache import (
    get_calibrated_params,
    invalidate as invalidate_cache,
)


def _print_result(label: str, result, elapsed_ms: float):
    if result is None:
        print(f"  ❌ {label}: fit FAILED (xem log để biết lý do)")
        return
    print(f"  {label}:")
    print(f"    Fit time:           {elapsed_ms:.0f} ms")
    print(f"    quality_tier:       {result.quality_tier}")
    print(f"    n (path loss exp):  {result.n_path_loss_exponent:.3f}")
    print(f"    intercept (dB):     {result.intercept_db:.2f}")
    print(f"    sigma (dB):         {result.sigma_db:.2f}")
    print(f"    R²:                 {result.r_squared:.4f}")
    print(f"    RMSE (dB):          {result.rmse_db:.2f}")
    print(f"    Samples total:      {result.n_samples_total:,}")
    print(f"    Samples fitted:     {result.n_samples_fitted:,}")
    print(f"    Outliers removed:   {result.n_outliers_removed:,}")
    print(f"    Distance range:     [{result.distance_min_m:.1f}, "
          f"{result.distance_max_m:.1f}] m")


async def run(persist: bool) -> int:
    correlation_id = f"cal_test_{int(time.time())}"
    print(f"\nPhysics range: n ∈ [{N_PATH_LOSS_MIN}, {N_PATH_LOSS_MAX}] "
          f"(ITU-R P.1411 / Rappaport)")

    async with AsyncSessionLocal() as db:
        # ─── 1. Fit urban gộp tất cả SF ────────────────────────────────────
        print("\n=== 1. Fit urban gộp all SF (with gateway quality filter) ===")
        t = time.perf_counter()
        result_all = await fit_path_loss(
            db,
            CalibrationFilters(
                environment_type="urban",
                use_gateway_quality_filter=True,
            ),
            correlation_id=correlation_id,
        )
        elapsed = (time.perf_counter() - t) * 1000
        _print_result("Urban all-SF", result_all, elapsed)

        # ─── 2. Fit per SF ─────────────────────────────────────────────────
        print("\n=== 2. Fit per-SF ===")
        per_sf: dict[int, "CalibrationResult | None"] = {}
        for sf in (12, 10):
            t = time.perf_counter()
            res = await fit_path_loss(
                db,
                CalibrationFilters(
                    environment_type="urban",
                    spreading_factor=sf,
                    use_gateway_quality_filter=True,
                ),
                correlation_id=correlation_id,
            )
            elapsed = (time.perf_counter() - t) * 1000
            _print_result(f"Urban SF{sf}", res, elapsed)
            per_sf[sf] = res

        # ─── 3. Fit rural (no data — expect None) ──────────────────────────
        print("\n=== 3. Fit rural (no data — expect None) ===")
        result_rural = await fit_path_loss(
            db,
            CalibrationFilters(environment_type="rural"),
            correlation_id=correlation_id,
        )
        if result_rural is None:
            print("  ✓ Đúng kỳ vọng: trả None (no data)")
        else:
            print(f"  ⚠ Bất ngờ: rural fit ra quality={result_rural.quality_tier}")

        # ─── 4. Pick best result để test persist ──────────────────────────
        candidates = [r for r in [result_all, *per_sf.values()] if r is not None]

        if not candidates:
            print("\n" + "=" * 70)
            print("  ⚠ KHÔNG có CalibrationResult nào trong physics range.")
            print("  ⚠ Đây là HÀNH VI ĐÚNG theo Option C (strict physics):")
            print("     - Framework calibration đã build và sẵn sàng")
            print("     - Data hiện tại fit ra n NGOÀI range [1.6, 6.0]")
            print("     - Cho thấy data quality issue (gateway location, ADR, ...)")
            print("     - Không persist invalid calibration vào DB → đúng physics")
            print("  → Khi data tốt hơn (drive test thật), sẽ tự động fit thành công.")
            print("=" * 70)
            return 0

        best = max(candidates, key=lambda r: r.r_squared)
        print(f"\n  → Best result: SF={best.filters.spreading_factor}, "
              f"quality={best.quality_tier}, R²={best.r_squared:.3f}, "
              f"n={best.n_path_loss_exponent:.3f}")

        if not persist:
            print("\n--no-persist → bỏ qua DB tests.")
            return 0

        # ─── 5. Persist với activate=False (Option C default) ─────────────
        print("\n=== 5. Persist (Option C: activate=False) ===")
        cal_id = await save_calibration(
            db, best,
            activate=False,
            correlation_id=correlation_id,
            notes=f"calibration_fit_test.py — quality={best.quality_tier}",
        )
        print(f"  Saved: {cal_id}, activate=False")

        retrieved = await get_calibration(db, cal_id)
        assert retrieved is not None
        assert retrieved["is_active"] is False, "Option C: phải KHÔNG active sau save"
        print(f"  ✓ Verified: row saved, is_active=False")

        active = await get_active_calibration(db, "urban")
        assert active is None or active["id"] != str(cal_id)
        print(f"  ✓ Active lookup: {active}")

        # ─── 6. Cache test pre-activate ───────────────────────────────────
        print("\n=== 6. Cache test: pre-activate ===")
        invalidate_cache()
        params_before = await get_calibrated_params(db, "urban")
        assert params_before is None, "Chưa active → cache trả None"
        print(f"  ✓ get_calibrated_params('urban') = None (chưa active)")

        # ─── 7. Manual activate ───────────────────────────────────────────
        print("\n=== 7. Manual activate ===")
        success = await set_active_calibration(
            db, cal_id, correlation_id=correlation_id,
        )
        assert success
        print(f"  ✓ set_active_calibration: {success}")

        invalidate_cache()
        params_after = await get_calibrated_params(db, "urban")
        assert params_after is not None
        assert params_after["calibration_id"] == str(cal_id)
        print(f"  ✓ get_calibrated_params('urban'): n={params_after['n_path_loss_exponent']:.3f}, "
              f"σ={params_after['sigma_db']:.2f}")

        # ─── 8. Cleanup ───────────────────────────────────────────────────
        print("\n=== 8. List + soft-delete ===")
        all_runs = await list_calibrations(db, environment_type="urban", limit=10)
        print(f"  Total urban calibrations: {len(all_runs)}")
        for r in all_runs[:5]:
            print(f"    {r['id'][:8]}… is_active={r['is_active']} "
                  f"R²={float(r['r_squared']):.3f} n={float(r['n_path_loss_exponent']):.2f}")

        deleted = await soft_delete_calibration(
            db, cal_id, correlation_id=correlation_id,
        )
        assert deleted
        print(f"  Soft-delete: {deleted}")

        gone = await get_calibration(db, cal_id)
        assert gone is None
        print(f"  ✓ Verified: không còn truy cập sau soft-delete")

    print("\n✓ All tests passed.")
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="calibration_fit_test")
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
    return asyncio.run(run(persist=not args.no_persist))


if __name__ == "__main__":
    sys.exit(main())