"""Celery task: rebuild composite RSSI heatmap + per-gateway geojson.

Config "Bản đồ ước lượng" (chốt 2026-06-09):
  - Stage 1 P.1812 + DTM (terrain only, KHÔNG DSM).
  - Per-gateway noise floor calibrate từ survey (geo.gateways.noise_floor_dbm).
  - Survey overlay per-gw: gw có điểm đo (serving_gateway_id) nhận overlay
    riêng trên sub-grid của mình; gw không có điểm đo giữ pure physics.
  - KHÔNG dùng Stage 2 ML (`--no-stage2`) — heatmap thuần vật lý.
  - Lý do chốt: user policy 2026-06-09 — composite max-agg sẽ inherit overlay
    từ per-gw tự nhiên; map mỗi gw "trung thực" với phép đo của riêng mình.

Logic Simplified Incremental:
- Query MAX(timestamp) per gateway từ ts.survey_training so với
  geo.gateways.last_rebuild_at.
- Nếu KHÔNG gw nào có MAX(timestamp) > last_rebuild_at → skip toàn bộ, không
  chạy script (đúng yêu cầu "không có gói tin mới thì không chạy").
- Nếu có ≥1 gw → chạy FULL `scripts/precompute_rssi_heatmap.py` (composite phải
  nhất quán toàn bộ gw, không thể chỉ rebuild subset). Sau thành công, update
  last_rebuild_at = now() cho TẤT CẢ gw eligible.

Chạy trong process Celery worker (concurrency=1, set ở celery_app.py). Script
con dùng multiprocessing.Pool — subprocess top-level nên không vướng "daemonic
processes can't have children" của prefork pool.
"""

from __future__ import annotations

import json
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

# Path bên trong container — bind-mounted ở docker-compose.yml (Phase B2).
SCRIPT_PATH = Path("/app/scripts/precompute_rssi_heatmap.py")
SUBPROCESS_TIMEOUT_S = 5400  # 90 phút hard limit (grid 25m + radius 30km ~60-80 phút)
# Mô hình ML (residual) để fusion vật lý + ML khi sinh bản đồ. Có model → bản đồ
# kết hợp; thiếu → tự động lui về bản đồ thuần vật lý (không vỡ rebuild).
ML_MODEL_PATH = Path("/app/services/ml-service/data/extra_trees_model.joblib")
ML_META_PATH = Path("/app/services/ml-service/data/model_meta.json")


def _engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


@_celery_mod.celery_app.task(bind=True, name="rebuild_coverage_map")  # type: ignore[untyped-decorator]
def rebuild_coverage_map(self: Any, job_id: str) -> dict[str, Any]:
    eng = _engine()
    t_start = time.time()

    with eng.begin() as conn:
        conn.execute(
            text(
                "UPDATE audit.coverage_rebuild_jobs "
                "SET status='running', started_at=now(), celery_task_id=:tid "
                "WHERE id=:id"
            ),
            {"tid": self.request.id, "id": job_id},
        )
        rows = conn.execute(
            text(
                "SELECT gw.code, gw.last_rebuild_at, "
                'MAX(t."timestamp") AS max_ts '
                "FROM geo.gateways gw "
                "LEFT JOIN ts.survey_training t "
                "  ON t.serving_gateway_id = gw.id "
                "WHERE gw.is_public = true "
                "GROUP BY gw.id, gw.code, gw.last_rebuild_at "
                "ORDER BY gw.code"
            )
        ).all()

    per_gw_log: dict[str, dict[str, Any]] = {}
    needs_rebuild: list[str] = []
    for r in rows:
        code = r.code
        if r.max_ts is None:
            per_gw_log[code] = {"status": "skipped", "reason": "no_data"}
            continue
        if r.last_rebuild_at is None or r.max_ts > r.last_rebuild_at:
            needs_rebuild.append(code)
            per_gw_log[code] = {
                "status": "pending",
                "max_ts": r.max_ts.isoformat(),
                "last_rebuild_at": (r.last_rebuild_at.isoformat() if r.last_rebuild_at else None),
            }
        else:
            per_gw_log[code] = {"status": "skipped", "reason": "no_new_data"}

    total = len(rows)
    skipped = total - len(needs_rebuild)

    if not needs_rebuild:
        elapsed = time.time() - t_start
        with eng.begin() as conn:
            conn.execute(
                text(
                    "UPDATE audit.coverage_rebuild_jobs SET "
                    "status='succeeded', finished_at=now(), "
                    "gateways_total=:total, gateways_rebuilt=0, "
                    "gateways_skipped=:skipped, "
                    "per_gw_log=CAST(:log AS jsonb) "
                    "WHERE id=:id"
                ),
                {
                    "total": total,
                    "skipped": skipped,
                    "log": json.dumps(per_gw_log),
                    "id": job_id,
                },
            )
        log.info(
            "rebuild job %s: no new data, skipped all %d gw (%.0fs)",
            job_id,
            total,
            elapsed,
        )
        return {
            "status": "succeeded",
            "gateways_rebuilt": 0,
            "gateways_skipped": skipped,
        }

    log.info(
        "rebuild job %s: %d/%d gw cần rebuild → run full script",
        job_id,
        len(needs_rebuild),
        total,
    )
    # Config "Bản đồ ước lượng" (cập nhật 2026-06-26 — chuyển DTM → DSM):
    #   P.1812 + DSM (DTM + chiều cao nhà OSM) + per-gw NF + survey overlay (per-gw).
    #   - DSM thắng DTM+P.2108 trên survey thật (RMSE 13.4 vs 23.6 dB, bias ~0 vs
    #     −11) + đồng nhất với /predict (vốn đã dùng DSM). P.2108 TỰ TẮT khi có
    #     surface (script: apply_p2108 = not surface_dem_dir) → không double-count.
    #   - Khử đốm --smooth-sigma 2 --opening-size 3 cho DSM building-resolution.
    #   - Stage 2 ML vẫn KHÔNG dùng cho heatmap (thuần vật lý); survey overlay
    #     luôn bật theo default script.
    #   - --force: overwrite output (admin rebuild phải ghi đè).
    #   surface dir: LORA_HEATMAP_SURFACE_DEM_DIRECTORY (refresh_geo_data ghi
    #   /geo/dem-surface) → fallback LORA_SURFACE_DEM_DIRECTORY (/data/dem-surface,
    #   cùng /predict). Thiếu cả hai → fallback DTM + P.2108 (không vỡ rebuild).
    cmd = [
        sys.executable,
        str(SCRIPT_PATH),
        "--force",
        # SF12 nghe được tới ~25 km nhưng default sub-grid 15 km cắt mất cell xa.
        # Bump 30 km để cover trường hợp board01 đo được −118 dBm @ 21.6 km
        # (gateway 7276ff002e062cf2 vùng Hoà Khánh ↔ Cẩm Lệ).
        "--per-gw-radius-km",
        "30",
    ]
    subproc_env = os.environ.copy()
    surface_dir = (
        os.environ.get("LORA_HEATMAP_SURFACE_DEM_DIRECTORY")
        or get_settings().lora_surface_dem_directory
    )
    if surface_dir and Path(surface_dir).is_dir():
        cmd += ["--surface-dem-dir", surface_dir, "--smooth-sigma", "2", "--opening-size", "3"]
        log.info(
            "rebuild job %s: DSM mode (surface=%s, P.2108 off, de-speckle σ2/open3)",
            job_id,
            surface_dir,
        )
        # Fusion vật lý + ML: chỉ bật ở chế độ DSM (khớp cấu hình lúc huấn luyện
        # residual) và khi có sẵn model. RSSI = P.1812 + hiệu chỉnh ML (bị chặn).
        if ML_MODEL_PATH.exists() and ML_META_PATH.exists():
            cmd += ["--ml-model", str(ML_MODEL_PATH), "--ml-workers", "4", "--ml-max-km", "12"]
            log.info("rebuild job %s: ML fusion BẬT (residual, model=%s)", job_id, ML_MODEL_PATH)
        else:
            log.info(
                "rebuild job %s: ML fusion TẮT (chưa có model residual) → bản đồ thuần vật lý",
                job_id,
            )
    else:
        # Không có DSM → fallback DTM + P.2108. Clear env để script chạy DTM-only.
        subproc_env["LORA_SURFACE_DEM_DIRECTORY"] = ""
        log.warning(
            "rebuild job %s: DSM dir thiếu (%r) → fallback DTM + P.2108", job_id, surface_dir
        )
    try:
        proc = subprocess.run(
            cmd,
            env=subproc_env,
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        elapsed = time.time() - t_start
        err = f"timeout after {SUBPROCESS_TIMEOUT_S}s: {exc!s}"
        with eng.begin() as conn:
            conn.execute(
                text(
                    "UPDATE audit.coverage_rebuild_jobs SET "
                    "status='failed', finished_at=now(), "
                    "gateways_total=:total, gateways_rebuilt=0, "
                    "gateways_skipped=:skipped, "
                    "per_gw_log=CAST(:log AS jsonb), "
                    "error_text=:err WHERE id=:id"
                ),
                {
                    "total": total,
                    "skipped": skipped,
                    "log": json.dumps(per_gw_log),
                    "err": err,
                    "id": job_id,
                },
            )
        log.error("rebuild job %s timed out after %.0fs", job_id, elapsed)
        return {"status": "failed", "error": "timeout"}

    elapsed = time.time() - t_start
    if proc.returncode != 0:
        err = (proc.stderr or "")[-4000:]
        for code in needs_rebuild:
            per_gw_log[code] = {"status": "failed"}
        with eng.begin() as conn:
            conn.execute(
                text(
                    "UPDATE audit.coverage_rebuild_jobs SET "
                    "status='failed', finished_at=now(), "
                    "gateways_total=:total, gateways_rebuilt=0, "
                    "gateways_skipped=:skipped, "
                    "per_gw_log=CAST(:log AS jsonb), "
                    "error_text=:err WHERE id=:id"
                ),
                {
                    "total": total,
                    "skipped": skipped,
                    "log": json.dumps(per_gw_log),
                    "err": err,
                    "id": job_id,
                },
            )
        log.error(
            "rebuild job %s failed: exit=%d (%.0fs)",
            job_id,
            proc.returncode,
            elapsed,
        )
        return {
            "status": "failed",
            "exit_code": proc.returncode,
            "stderr_tail": err,
        }

    for code in needs_rebuild:
        per_gw_log[code] = {"status": "rebuilt"}
    with eng.begin() as conn:
        conn.execute(
            text("UPDATE geo.gateways SET last_rebuild_at = now() WHERE code = ANY(:codes)"),
            {"codes": needs_rebuild},
        )
        conn.execute(
            text(
                "UPDATE audit.coverage_rebuild_jobs SET "
                "status='succeeded', finished_at=now(), "
                "gateways_total=:total, gateways_rebuilt=:rebuilt, "
                "gateways_skipped=:skipped, "
                "per_gw_log=CAST(:log AS jsonb) "
                "WHERE id=:id"
            ),
            {
                "total": total,
                "rebuilt": len(needs_rebuild),
                "skipped": skipped,
                "log": json.dumps(per_gw_log),
                "id": job_id,
            },
        )
    log.info(
        "rebuild job %s succeeded: %d rebuilt, %d skipped (%.0fs)",
        job_id,
        len(needs_rebuild),
        skipped,
        elapsed,
    )
    return {
        "status": "succeeded",
        "gateways_rebuilt": len(needs_rebuild),
        "gateways_skipped": skipped,
        "elapsed_s": round(elapsed, 1),
    }
