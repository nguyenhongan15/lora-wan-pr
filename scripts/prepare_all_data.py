"""End-to-end data pipeline: 1 lệnh chuẩn bị mọi thứ frontend cần.

Mục tiêu: chạy 1 lần (~30 phút), tối hôm sau wake up có đủ data cho web-app
hiển thị min-SF coverage map ở `/coverage` route.

Pipeline (7 bước, abort ngay khi 1 bước fail):
  1. Pre-flight   — verify DEM, OSM PBF, DB connection, disk free (>5 GB).
  2. DSM tiles    — chạy scripts/build_dsm.py mỗi terrain tile chưa có surface
                    counterpart. --force để rebuild tất cả.
  3. Smoke test   — gọi CrcCovlibBackend.basic_transmission_loss_db trên 1 link
                    gateway→target gần đó, expect finite PL trong [50, 200] dB.
  4. Validation   — pull ~100 sample test (Jan-Feb 2026) từ DB, compute bias +
                    RMSE Stage 1 ITU. So với baseline +11.65 dB / 7-14 dB.
  5. Min-SF       — scripts/precompute_minsf.py --force cho tất cả gateway
                    is_public=true, output thẳng vào apps/web-app/public/coverage/minsf/.
  6. Manifest     — verify manifest.json đầy đủ, count GeoJSON, log size.
  7. Summary      — bảng tóm tắt timing + bytes + paths để check sáng hôm sau.

ITU digital maps (P.453 refractivity, P.1510 temperature, P.836 water vapor)
đã ship sẵn trong crc-covlib wheel — không cần download/config riêng.

Run:
    uv run --project services/api-service python scripts/prepare_all_data.py
    uv run --project services/api-service python scripts/prepare_all_data.py --force-dsm
    uv run --project services/api-service python scripts/prepare_all_data.py --skip-minsf

Env vars (đọc từ .env auto):
    LORA_DEM_DIRECTORY          REQUIRED — Copernicus GLO-30 terrain tiles
    LORA_SURFACE_DEM_DIRECTORY  REQUIRED — DSM output dir (auto-create)
    LORA_DB_URL                 REQUIRED — Postgres URL cho validation + gateway pull
    LORA_OSM_PBF                Path tới vietnam-*.osm.pbf (default infer dem-sibling)

Exit codes:
    0 — all steps OK
    2 — pre-flight fail (env, files, DB)
    3 — DSM build fail
    4 — smoke test fail (backend non-finite hoặc out-of-range)
    5 — validation fail (sample query 0 row)
    6 — min-SF fail (subprocess non-zero)
    7 — manifest fail (file missing)
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API_SRC = REPO_ROOT / "services" / "api-service" / "src"
sys.path.insert(0, str(API_SRC))

log = logging.getLogger("prepare_all_data")

_FRONTEND_MINSF_DIR = REPO_ROOT / "apps" / "web-app" / "public" / "coverage" / "minsf"


@dataclass
class StepResult:
    name: str
    ok: bool
    elapsed_s: float
    details: dict[str, object] = field(default_factory=dict)
    error: str | None = None


# ── Step 1: Pre-flight ────────────────────────────────────────────────────────


def _step_preflight() -> StepResult:
    t0 = time.time()
    details: dict[str, object] = {}
    missing: list[str] = []

    for var in ("LORA_DEM_DIRECTORY", "LORA_SURFACE_DEM_DIRECTORY"):
        v = os.environ.get(var, "")
        details[var] = v or "(not set)"
        if not v:
            missing.append(var)

    db_url = os.environ.get("LORA_DB_URL") or os.environ.get("DATABASE_URL", "")
    details["DB_URL"] = "set" if db_url else "(not set)"
    if not db_url:
        missing.append("LORA_DB_URL or DATABASE_URL")

    if missing:
        return StepResult(
            "preflight",
            False,
            time.time() - t0,
            details,
            f"Missing env vars: {', '.join(missing)}",
        )

    dem_dir = Path(os.environ["LORA_DEM_DIRECTORY"])
    if not dem_dir.is_dir():
        return StepResult(
            "preflight", False, time.time() - t0, details, f"DEM dir missing: {dem_dir}"
        )
    tifs = list(dem_dir.glob("*.tif"))
    details["dem_tif_count"] = len(tifs)
    if not tifs:
        return StepResult("preflight", False, time.time() - t0, details, f"No .tif in {dem_dir}")

    surface_dir = Path(os.environ["LORA_SURFACE_DEM_DIRECTORY"])
    surface_dir.mkdir(parents=True, exist_ok=True)
    details["surface_dem_dir"] = str(surface_dir)

    pbf_env = os.environ.get("LORA_OSM_PBF", "")
    if pbf_env:
        pbf = Path(pbf_env)
    else:
        candidates = list(dem_dir.parent.glob("osm/*.osm.pbf"))
        pbf = candidates[0] if candidates else Path()
    if not pbf.is_file():
        return StepResult(
            "preflight",
            False,
            time.time() - t0,
            details,
            f"OSM PBF not found (set LORA_OSM_PBF). Tried: {pbf}",
        )
    details["osm_pbf"] = str(pbf)
    details["osm_pbf_mb"] = round(pbf.stat().st_size / 1e6, 1)
    os.environ["LORA_OSM_PBF"] = str(pbf)

    try:
        free_bytes = shutil.disk_usage(dem_dir).free
        details["disk_free_gb"] = round(free_bytes / 1e9, 1)
        if free_bytes < 5 * 1024**3:
            return StepResult(
                "preflight",
                False,
                time.time() - t0,
                details,
                f"Disk free <5 GB: {free_bytes / 1e9:.1f} GB",
            )
    except OSError as e:
        log.warning("disk_usage check failed: %s", e)

    try:
        import psycopg

        url = db_url.replace("postgresql+psycopg://", "postgresql://", 1)
        with psycopg.connect(url, connect_timeout=5) as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM geo.gateways WHERE is_public = true")
            (n_gw,) = cur.fetchone()
            details["public_gateway_count"] = n_gw
        if n_gw == 0:
            return StepResult(
                "preflight", False, time.time() - t0, details, "No public gateway in DB"
            )
    except Exception as e:
        return StepResult("preflight", False, time.time() - t0, details, f"DB probe fail: {e}")

    return StepResult("preflight", True, time.time() - t0, details)


# ── Step 2: DSM build ─────────────────────────────────────────────────────────


def _step_dsm_build(force: bool) -> StepResult:
    t0 = time.time()
    dem_dir = Path(os.environ["LORA_DEM_DIRECTORY"])
    surface_dir = Path(os.environ["LORA_SURFACE_DEM_DIRECTORY"])
    pbf = Path(os.environ["LORA_OSM_PBF"])

    terrain_tifs = sorted(dem_dir.glob("*.tif"))
    to_build = [t for t in terrain_tifs if force or not (surface_dir / t.name).is_file()]

    details: dict[str, object] = {
        "terrain_tiles": len(terrain_tifs),
        "to_build": len(to_build),
        "surface_dir": str(surface_dir),
    }

    if not to_build:
        return StepResult("dsm_build", True, time.time() - t0, {**details, "skipped": True})

    # build_dsm.py loops dem-dir tiles tự động + skip nếu output đã có (cùng
    # logic). 1 subprocess call cover tất cả tile to_build.
    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "build_dsm.py"),
        "--dem-dir",
        str(dem_dir),
        "--pbf",
        str(pbf),
        "--out-dir",
        str(surface_dir),
    ]
    if force:
        cmd.append("--force")

    log.info("build_dsm.py → %s", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=False)
    if proc.returncode != 0:
        return StepResult(
            "dsm_build", False, time.time() - t0, details, f"build_dsm.py exit={proc.returncode}"
        )

    return StepResult("dsm_build", True, time.time() - t0, details)


# ── Step 3: Backend smoke test ────────────────────────────────────────────────


def _step_smoke() -> StepResult:
    t0 = time.time()
    details: dict[str, object] = {}
    try:
        from lora_coverage_api.application.itu.backend import GeoPoint, LinkGeometry
        from lora_coverage_api.infrastructure.itu.crc_covlib_backend import CrcCovlibBackend

        backend = CrcCovlibBackend(
            dem_directory=Path(os.environ["LORA_DEM_DIRECTORY"]),
            surface_dem_directory=Path(os.environ["LORA_SURFACE_DEM_DIRECTORY"]),
        )

        # Đà Nẵng test link — DNIIT center → target ~2 km E.
        link = LinkGeometry(
            tx=GeoPoint(latitude=16.0740935, longitude=108.1524913),
            rx=GeoPoint(latitude=16.0740935, longitude=108.17),
            tx_antenna_height_m=20.0,
            rx_antenna_height_m=1.5,
            freq_mhz=923.2,
        )
        pl = backend.basic_transmission_loss_db(link)
        details["path_loss_db"] = round(pl, 2)
        if not math.isfinite(pl) or pl < 50.0 or pl > 200.0:
            return StepResult("smoke", False, time.time() - t0, details, f"PL out of range: {pl}")
    except Exception as e:
        return StepResult("smoke", False, time.time() - t0, details, f"{type(e).__name__}: {e}")

    return StepResult("smoke", True, time.time() - t0, details)


# ── Step 4: Validation against test hold-out ──────────────────────────────────


def _step_validation(sample_size: int) -> StepResult:
    t0 = time.time()
    details: dict[str, object] = {"sample_size": sample_size}
    try:
        import psycopg
        from lora_coverage_api.application.itu.backend import GeoPoint, LinkGeometry
        from lora_coverage_api.infrastructure.itu.crc_covlib_backend import CrcCovlibBackend

        backend = CrcCovlibBackend(
            dem_directory=Path(os.environ["LORA_DEM_DIRECTORY"]),
            surface_dem_directory=Path(os.environ["LORA_SURFACE_DEM_DIRECTORY"]),
        )

        db_url = (os.environ.get("LORA_DB_URL") or os.environ["DATABASE_URL"]).replace(
            "postgresql+psycopg://", "postgresql://", 1
        )
        sql = """
            SELECT
              t.rssi_dbm,
              t.frequency_mhz,
              ST_Y(t.location::geometry) AS rx_lat,
              ST_X(t.location::geometry) AS rx_lon,
              g.code AS gw_code,
              ST_Y(g.location::geometry) AS gw_lat,
              ST_X(g.location::geometry) AS gw_lon,
              g.antenna_height_m AS gw_h,
              g.antenna_gain_dbi AS gw_gain,
              g.tx_power_dbm AS gw_tx
            FROM ts.survey_training t
            JOIN geo.gateways g ON g.id = t.serving_gateway_id
            WHERE t.timestamp >= '2026-01-01'
              AND t.timestamp < '2026-03-01'
            ORDER BY random()
            LIMIT %s
        """
        with psycopg.connect(db_url, connect_timeout=5) as conn, conn.cursor() as cur:
            cur.execute(sql, (sample_size,))
            cols = [d.name for d in cur.description]
            rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

        if not rows:
            return StepResult(
                "validation",
                False,
                time.time() - t0,
                details,
                "0 sample rows in Jan-Feb 2026 test window — DB empty?",
            )

        residuals: list[float] = []
        n_err = 0
        for r in rows:
            try:
                link = LinkGeometry(
                    tx=GeoPoint(latitude=float(r["gw_lat"]), longitude=float(r["gw_lon"])),
                    rx=GeoPoint(latitude=float(r["rx_lat"]), longitude=float(r["rx_lon"])),
                    tx_antenna_height_m=float(r["gw_h"]),
                    rx_antenna_height_m=1.5,
                    freq_mhz=float(r["frequency_mhz"]),
                )
                pl = backend.basic_transmission_loss_db(link)
                rssi_pred = float(r["gw_tx"]) + float(r["gw_gain"]) - pl
                resid = float(r["rssi_dbm"]) - rssi_pred
                residuals.append(resid)
            except Exception:
                n_err += 1
                continue

        if not residuals:
            return StepResult(
                "validation",
                False,
                time.time() - t0,
                details,
                f"All {n_err} samples failed — backend or geometry broken",
            )

        bias = sum(residuals) / len(residuals)
        rmse = math.sqrt(sum(r * r for r in residuals) / len(residuals))
        details.update(
            {
                "n_ok": len(residuals),
                "n_err": n_err,
                "bias_db": round(bias, 2),
                "rmse_db": round(rmse, 2),
                "baseline_bias_db": 11.65,
                "baseline_rmse_db_range": "7-14",
            }
        )
    except Exception as e:
        return StepResult(
            "validation", False, time.time() - t0, details, f"{type(e).__name__}: {e}"
        )

    return StepResult("validation", True, time.time() - t0, details)


# ── Step 5: Min-SF precompute ─────────────────────────────────────────────────


def _step_minsf(
    workers: int, radius_km: float | None, grid_m: float, force: bool
) -> StepResult:
    t0 = time.time()
    _FRONTEND_MINSF_DIR.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "precompute_minsf.py"),
        "--workers",
        str(workers),
        "--grid-m",
        str(grid_m),
        "--output-dir",
        str(_FRONTEND_MINSF_DIR),
    ]
    if radius_km is not None:
        cmd.extend(["--radius-km", str(radius_km)])
    if force:
        cmd.append("--force")

    log.info("precompute_minsf.py → %s", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=False)
    elapsed = time.time() - t0
    if proc.returncode != 0:
        return StepResult(
            "minsf",
            False,
            elapsed,
            {"output_dir": str(_FRONTEND_MINSF_DIR)},
            f"precompute_minsf.py exit={proc.returncode}",
        )

    geojsons = list(_FRONTEND_MINSF_DIR.glob("*.geojson"))
    return StepResult(
        "minsf",
        True,
        elapsed,
        {
            "output_dir": str(_FRONTEND_MINSF_DIR),
            "geojson_count": len(geojsons),
            "elapsed_s": round(elapsed, 1),
        },
    )


# ── Step 6: Manifest sanity ───────────────────────────────────────────────────


def _step_manifest() -> StepResult:
    t0 = time.time()
    manifest_path = _FRONTEND_MINSF_DIR / "manifest.json"
    if not manifest_path.is_file():
        return StepResult(
            "manifest", False, time.time() - t0, {}, f"manifest.json missing: {manifest_path}"
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return StepResult(
            "manifest", False, time.time() - t0, {}, f"manifest.json parse error: {e}"
        )

    gateways = manifest.get("gateways", [])
    actual_files = {p.name for p in _FRONTEND_MINSF_DIR.glob("*.geojson")}
    missing = [g["code"] for g in gateways if f"{g['code']}.geojson" not in actual_files]
    if missing:
        return StepResult(
            "manifest",
            False,
            time.time() - t0,
            {"manifest_count": len(gateways)},
            f"Manifest references {len(missing)} missing GeoJSON: {missing[:5]}",
        )

    total_mb = sum(p.stat().st_size for p in _FRONTEND_MINSF_DIR.glob("*.geojson")) / 1e6
    return StepResult(
        "manifest",
        True,
        time.time() - t0,
        {
            "manifest_count": len(gateways),
            "geojson_count": len(actual_files),
            "total_mb": round(total_mb, 2),
        },
    )


# ── Driver ───────────────────────────────────────────────────────────────────


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    env_path = REPO_ROOT / ".env"
    if env_path.is_file():
        load_dotenv(env_path, override=False)


def _print_summary(results: list[StepResult]) -> None:
    total = sum(r.elapsed_s for r in results)
    log.info("=" * 72)
    log.info("PIPELINE SUMMARY")
    log.info("=" * 72)
    for r in results:
        status = "OK " if r.ok else "FAIL"
        log.info("  [%s] %-12s %7.1fs  %s", status, r.name, r.elapsed_s, r.details)
        if r.error:
            log.error("       error: %s", r.error)
    log.info("-" * 72)
    log.info("Total elapsed: %.1fs (%.1f min)", total, total / 60.0)
    log.info("=" * 72)


_EXIT_CODES = {
    "preflight": 2,
    "dsm_build": 3,
    "smoke": 4,
    "validation": 5,
    "minsf": 6,
    "manifest": 7,
}


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    _load_dotenv()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force-dsm", action="store_true", help="Rebuild all DSM tiles")
    parser.add_argument(
        "--skip-validation", action="store_true", help="Skip step 4 (mini Stage 1 validation)"
    )
    parser.add_argument("--skip-minsf", action="store_true", help="Skip step 5 (min-SF precompute)")
    parser.add_argument("--validation-sample", type=int, default=100)
    parser.add_argument("--minsf-workers", type=int, default=8)
    parser.add_argument(
        "--minsf-radius-km",
        type=float,
        default=None,
        help=(
            "Override per-gateway auto-radius. Mặc định auto từ link-budget "
            "(Friis − 30 dB clutter, cap [5, 50] km)."
        ),
    )
    parser.add_argument("--minsf-grid-m", type=float, default=50.0)
    parser.add_argument(
        "--force-minsf",
        action="store_true",
        help=(
            "Pass --force xuống precompute_minsf.py để recompute tất cả gateway. "
            "Mặc định skip gateway đã có .geojson (overnight rerun chỉ cần khi "
            "Stage 1 backend đổi)."
        ),
    )
    args = parser.parse_args()

    results: list[StepResult] = []

    def _run(name: str, fn) -> bool:
        log.info("[%s] start", name)
        r = fn()
        results.append(r)
        if r.ok:
            log.info("[%s] OK in %.1fs — %s", name, r.elapsed_s, r.details)
        else:
            log.error("[%s] FAIL in %.1fs — %s", name, r.elapsed_s, r.error)
        return r.ok

    if not _run("preflight", _step_preflight):
        _print_summary(results)
        return _EXIT_CODES["preflight"]

    if not _run("dsm_build", lambda: _step_dsm_build(args.force_dsm)):
        _print_summary(results)
        return _EXIT_CODES["dsm_build"]

    if not _run("smoke", _step_smoke):
        _print_summary(results)
        return _EXIT_CODES["smoke"]

    if not args.skip_validation:
        if not _run("validation", lambda: _step_validation(args.validation_sample)):
            _print_summary(results)
            return _EXIT_CODES["validation"]

    if not args.skip_minsf:
        if not _run(
            "minsf",
            lambda: _step_minsf(
                args.minsf_workers,
                args.minsf_radius_km,
                args.minsf_grid_m,
                force=args.force_minsf,
            ),
        ):
            _print_summary(results)
            return _EXIT_CODES["minsf"]

        if not _run("manifest", _step_manifest):
            _print_summary(results)
            return _EXIT_CODES["manifest"]

    _print_summary(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
