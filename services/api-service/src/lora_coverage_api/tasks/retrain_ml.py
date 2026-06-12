"""Celery task: retrain Extra Trees ML model.

Mirror pattern cua tasks/rebuild_coverage.py:
  - Update audit.ml_retrain_jobs (status/started_at/celery_task_id ...).
  - Run subprocess: `python /app/scripts/train_extra_trees.py`.
    Script tu lo atomic swap (.new -> rename) + ghi train_metrics.json.
  - Sau khi success: doc train_metrics.json, ghi metrics + rows_trained vao
    audit row.

Khong co per-gw logic (train chay 1 luot tren toan bo data).

GHI CHU (TODO): `train_extra_trees.py` doc tu CSV preprocessed
`services/ml-service/reference_wireless/data/processed/devices_history_full.csv`,
KHONG phai tu `ts.survey_training`. Nen retrain hien tai khong reflect admin
delete-approved-data. Future work: rebuild CSV tu survey_training truoc khi train.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import Engine, create_engine, text

from .. import celery_app as _celery_mod
from ..config import get_settings

log = logging.getLogger(__name__)

SCRIPT_PATH = Path("/app/scripts/train_extra_trees.py")
METRICS_PATH = Path("/app/services/ml-service/data/train_metrics.json")
ARTIFACT_PATH = Path("/app/services/ml-service/data/extra_trees_model.joblib")
SUBPROCESS_TIMEOUT_S = 3600  # 1h


def _engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


@_celery_mod.celery_app.task(bind=True, name="retrain_ml_model")  # type: ignore[untyped-decorator]
def retrain_ml_model(self: Any, job_id: str) -> dict[str, Any]:
    eng = _engine()
    t_start = time.time()

    with eng.begin() as conn:
        conn.execute(
            text(
                "UPDATE audit.ml_retrain_jobs "
                "SET status='running', started_at=now(), celery_task_id=:tid "
                "WHERE id=:id"
            ),
            {"tid": self.request.id, "id": job_id},
        )

    cmd = [sys.executable, str(SCRIPT_PATH)]
    try:
        proc = subprocess.run(
            cmd,
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
                    "UPDATE audit.ml_retrain_jobs SET "
                    "status='failed', finished_at=now(), error_text=:err "
                    "WHERE id=:id"
                ),
                {"err": err, "id": job_id},
            )
        log.error("retrain job %s timed out after %.0fs", job_id, elapsed)
        return {"status": "failed", "error": "timeout"}

    elapsed = time.time() - t_start
    if proc.returncode != 0:
        err = (proc.stderr or "")[-4000:]
        with eng.begin() as conn:
            conn.execute(
                text(
                    "UPDATE audit.ml_retrain_jobs SET "
                    "status='failed', finished_at=now(), error_text=:err "
                    "WHERE id=:id"
                ),
                {"err": err, "id": job_id},
            )
        log.error("retrain job %s failed: exit=%d (%.0fs)", job_id, proc.returncode, elapsed)
        return {"status": "failed", "exit_code": proc.returncode, "stderr_tail": err}

    metrics: dict[str, Any] = {}
    rows_trained: int | None = None
    try:
        metrics_raw = json.loads(METRICS_PATH.read_text())
        rows_trained = int(metrics_raw.pop("rows_trained", 0)) or None
        metrics = metrics_raw
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        log.warning("retrain job %s succeeded but metrics read failed: %s", job_id, exc)

    # Hot-reload ml-service. Fail-soft: log warning + ghi vao metrics nhung
    # KHONG fail job (model file da swap xong, ml-service tu reload khi restart).
    reload_status = _call_ml_service_reload()
    if reload_status:
        metrics["ml_service_reload"] = reload_status

    with eng.begin() as conn:
        conn.execute(
            text(
                "UPDATE audit.ml_retrain_jobs SET "
                "status='succeeded', finished_at=now(), "
                "rows_trained=:rows, artifact_path=:art, "
                "metrics=CAST(:m AS jsonb) "
                "WHERE id=:id"
            ),
            {
                "rows": rows_trained,
                "art": str(ARTIFACT_PATH),
                "m": json.dumps(metrics),
                "id": job_id,
            },
        )
    log.info("retrain job %s succeeded: rows=%s (%.0fs)", job_id, rows_trained, elapsed)
    return {
        "status": "succeeded",
        "rows_trained": rows_trained,
        "metrics": metrics,
        "elapsed_s": round(elapsed, 1),
    }


def _call_ml_service_reload() -> str | None:
    """POST ml-service /admin/reload. Trả 'ok' / 'failed: <reason>' / None nếu
    base URL chưa cấu hình (Stage 2 disabled)."""
    s = get_settings()
    base = (s.stage2_predict_base_url or "").rstrip("/")
    if not base:
        log.info("ml-service reload skipped: STAGE2_PREDICT_BASE_URL empty")
        return None
    url = f"{base}/admin/reload"
    headers = {"Authorization": f"Bearer {s.stage2_auth_token}"}
    try:
        resp = httpx.post(url, headers=headers, timeout=10.0)
        resp.raise_for_status()
        log.info("ml-service reload ok: %s", resp.json())
        return "ok"
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("ml-service reload failed: %s", exc)
        return f"failed: {exc!s}"
