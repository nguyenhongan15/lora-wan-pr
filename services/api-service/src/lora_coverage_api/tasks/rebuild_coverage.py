"""Celery task: rebuild composite RSSI heatmap + per-gateway geojson.

Config "Bản đồ ước lượng" (chốt 2026-06-09):
  - Stage 1 P.1812 + DTM (terrain only, KHÔNG DSM).
  - Per-gateway noise floor calibrate từ survey (geo.gateways.noise_floor_dbm).
  - Survey overlay per-gw: gw có điểm đo (serving_gateway_id) nhận overlay
    riêng trên sub-grid của mình; gw không có điểm đo giữ pure physics.
  - KHÔNG dùng Stage 2 XGBoost (`--no-stage2`).
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
SUBPROCESS_TIMEOUT_S = 3600  # 1h hard limit


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
    # Config "Bản đồ ước lượng" (chốt 2026-06-09):
    #   P.1812 + DTM (terrain only) + per-gw NF + survey overlay (per-gw).
    #   - KHÔNG dùng DSM (surface model) — clear LORA_SURFACE_DEM_DIRECTORY.
    #     Worker container có thể có env này từ Stage 1 ITU calibration,
    #     KHÔNG được rò rỉ vào subprocess heatmap.
    #   - KHÔNG dùng Stage 2 XGBoost — --no-stage2.
    #   - Survey overlay per-gw: gw có điểm đo nhận overlay riêng (filter
    #     serving_gateway_id), gw không có điểm đo giữ pure physics.
    #   - --force: script skip nếu output file đã tồn tại; admin rebuild
    #     PHẢI overwrite.
    cmd = [
        sys.executable,
        str(SCRIPT_PATH),
        "--no-stage2",
        "--survey-overlay",
        "--force",
    ]
    subproc_env = os.environ.copy()
    subproc_env["LORA_SURFACE_DEM_DIRECTORY"] = ""
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
