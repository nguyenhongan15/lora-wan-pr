"""Celery task: làm tươi dữ liệu địa lý hàng tháng → DSM mới → rebuild heatmap.

Mục đích (user 2026-06-26): footprint nhà OSM thay đổi theo thời gian (nhà mới
xây/mới map). Định kỳ tải OSM mới nhất → build lại DSM → rebuild "bản đồ ước
lượng" để dự đoán phản ánh hiện trạng mới nhất.

Pipeline (chạy trong celery-worker):
  1. fetch_osm_pbf.py  → tải Geofabrik VN PBF về /geo/osm (nguồn chính xác nhất).
  2. build_dsm.py      → DTM (/data/dem, ro) + nhà OSM → DSM tiles /geo/dem-surface.
  3. precompute_rssi_heatmap.py --force --surface-dem-dir /geo/dem-surface
                        → rebuild composite (FORCE: DSM đổi nên phải build lại
                          dù không có survey mới — khác rebuild_coverage incremental).
  4. UPDATE geo.gateways.last_rebuild_at = now() (đánh dấu đã rebuild).

Ràng buộc hạ tầng: /data mount READ-ONLY → DSM regenerate PHẢI ghi vào volume
ghi-được /geo (docker-compose: ./data/geo:/geo:rw). rebuild_coverage_map đọc
DSM qua LORA_HEATMAP_SURFACE_DEM_DIRECTORY=/geo/dem-surface (cùng path).

Cadence: hàng tháng qua Celery beat (celery_app.beat_schedule). Có thể trigger
tay qua admin endpoint nếu cần.

Lưu ý độ chính xác: refresh cập nhật VỊ TRÍ nhà (footprint), KHÔNG sửa được
chiều cao (OSM/MS/Google thiếu height cho VN → vẫn giả định ~9m theo loại).
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, text

from .. import celery_app as _celery_mod
from ..config import get_settings

log = logging.getLogger(__name__)

# Paths trong container (bind-mount docker-compose).
FETCH_SCRIPT = Path("/app/scripts/fetch_osm_pbf.py")
BUILD_DSM_SCRIPT = Path("/app/scripts/build_dsm.py")
HEATMAP_SCRIPT = Path("/app/scripts/precompute_rssi_heatmap.py")
DEM_DIR = Path(os.environ.get("LORA_DEM_DIRECTORY", "/data/dem"))
GEO_DIR = Path(os.environ.get("LORA_GEO_CACHE_DIR", "/geo"))  # volume ghi-được

FETCH_TIMEOUT_S = 1800  # 30 phút — PBF VN ~350MB
BUILD_DSM_TIMEOUT_S = 1800  # 30 phút — scan PBF + rasterize 3 tile
HEATMAP_TIMEOUT_S = 5400  # 90 phút — DSM + de-speckle full Đà Nẵng


def _engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


def _run(label: str, cmd: list[str], timeout: int, env: dict[str, str]) -> tuple[bool, str]:
    """Chạy 1 subprocess fail-soft. Trả (ok, stderr_tail)."""
    log.info("refresh_geo: %s → %s", label, " ".join(cmd))
    try:
        proc = subprocess.run(
            cmd, env=env, capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired:
        return False, f"{label} timeout sau {timeout}s"
    if proc.returncode != 0:
        return False, (proc.stderr or "")[-2000:]
    return True, ""


@_celery_mod.celery_app.task(bind=True, name="refresh_geo_data")  # type: ignore[untyped-decorator]
def refresh_geo_data(self: Any, force_heatmap: bool = True) -> dict[str, Any]:
    """Tải OSM mới → build DSM → rebuild heatmap. Trả dict trạng thái từng bước."""
    t_start = time.time()
    result: dict[str, Any] = {"steps": {}}

    pbf_path = GEO_DIR / "osm" / "vietnam-latest.osm.pbf"
    dsm_dir = GEO_DIR / "dem-surface"
    env = os.environ.copy()

    # Step 1: tải OSM PBF mới nhất.
    ok, err = _run(
        "fetch_osm",
        [sys.executable, str(FETCH_SCRIPT), "--out", str(pbf_path)],
        FETCH_TIMEOUT_S,
        env,
    )
    result["steps"]["fetch_osm"] = "ok" if ok else f"failed: {err}"
    if not ok:
        log.error("refresh_geo: fetch_osm failed: %s", err)
        result["status"] = "failed"
        return result

    # Step 2: build DSM = max(Copernicus canopy nền, DTM + nhà OSM mới) → /geo
    # (ghi-được). --base-surface-dir giữ canopy clutter ĐÃ VALIDATED (Copernicus
    # surface tĩnh, RMSE 13.4/bias 0), chỉ chèn nhà OSM tươi nơi cao hơn. KHÔNG
    # build footprint thuần (0.61% → rural không clutter → quá lạc quan).
    base_surface = os.environ.get("LORA_SURFACE_DEM_DIRECTORY", "/data/dem-surface")
    ok, err = _run(
        "build_dsm",
        [
            sys.executable,
            str(BUILD_DSM_SCRIPT),
            "--dem-dir",
            str(DEM_DIR),
            "--pbf",
            str(pbf_path),
            "--out-dir",
            str(dsm_dir),
            "--base-surface-dir",
            base_surface,
            "--force",
        ],
        BUILD_DSM_TIMEOUT_S,
        env,
    )
    result["steps"]["build_dsm"] = "ok" if ok else f"failed: {err}"
    if not ok:
        log.error("refresh_geo: build_dsm failed: %s", err)
        result["status"] = "failed"
        return result

    # Step 3: rebuild heatmap với DSM mới. FORCE vì DSM đổi (không phụ thuộc
    # survey mới như rebuild_coverage incremental). Khử đốm σ2/open3.
    if force_heatmap:
        ok, err = _run(
            "rebuild_heatmap",
            [
                sys.executable,
                str(HEATMAP_SCRIPT),
                "--force",
                "--per-gw-radius-km",
                "30",
                "--surface-dem-dir",
                str(dsm_dir),
                "--smooth-sigma",
                "2",
                "--opening-size",
                "3",
            ],
            HEATMAP_TIMEOUT_S,
            env,
        )
        result["steps"]["rebuild_heatmap"] = "ok" if ok else f"failed: {err}"
        if not ok:
            log.error("refresh_geo: rebuild_heatmap failed: %s", err)
            result["status"] = "failed"
            return result

        # Đánh dấu đã rebuild toàn bộ gw public (tránh rebuild_coverage incremental
        # chạy lại thừa ngay sau đó).
        try:
            with _engine().begin() as conn:
                conn.execute(
                    text("UPDATE geo.gateways SET last_rebuild_at = now() WHERE is_public = true")
                )
        except Exception as exc:
            log.warning("refresh_geo: update last_rebuild_at failed: %s", exc)

    result["status"] = "succeeded"
    result["elapsed_s"] = round(time.time() - t_start, 1)
    log.info("refresh_geo: done in %.0fs", time.time() - t_start)
    return result
