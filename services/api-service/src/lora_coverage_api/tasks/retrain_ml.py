"""Celery task: retrain Extra Trees ML model.

Mirror pattern cua tasks/rebuild_coverage.py:
  - Update audit.ml_retrain_jobs (status/started_at/celery_task_id ...).
  - Run subprocess `python /app/scripts/build_training_csv.py` de rebuild CSV
    tu ts.survey_training (community rows) — bao gom DEM + landuse feature
    engineering cho toan bo central VN (Hue/DN/QN).
  - Run subprocess `python /app/scripts/train_extra_trees.py` de train tren
    CSV moi. Script tu lo atomic swap (.new -> rename) + ghi train_metrics.json.
  - Sau khi success: doc train_metrics.json, ghi metrics + rows_trained vao
    audit row.

Khong co per-gw logic (train chay 1 luot tren toan bo data).
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, cast

import httpx
from sqlalchemy import Engine, create_engine, text

from .. import celery_app as _celery_mod
from ..config import get_settings

log = logging.getLogger(__name__)

SCRIPT_PATH = Path("/app/scripts/train_extra_trees.py")
BUILD_CSV_SCRIPT_PATH = Path("/app/scripts/build_training_csv.py")
EVAL_SCRIPT_PATH = Path("/app/scripts/eval_extra_trees_holdout.py")
REPORT_SCRIPT_PATH = Path("/app/scripts/render_ml_report.py")
METRICS_PATH = Path("/app/services/ml-service/data/train_metrics.json")
VAL_METRICS_PATH = Path("/app/services/ml-service/data/val_metrics.json")
SPLIT_STATS_PATH = Path("/app/services/ml-service/data/train_split_stats.json")
ARTIFACT_PATH = Path("/app/services/ml-service/data/extra_trees_model.joblib")
REPORTS_ROOT = Path("/app/reports")
SUBPROCESS_TIMEOUT_S = 3600  # 1h — bao gom build CSV (5-30 phut) + train (~1 phut)
BUILD_CSV_TIMEOUT_S = 2400  # 40 phut — terrain sampling cho ~10k+ rows
EVAL_TIMEOUT_S = 300  # 5 phut — predict 1500 row test split, khong DEM lookup
REPORT_TIMEOUT_S = 600  # 10 phut — du cho hold-out eval + plot + PDF
TEST_RMSE_HIGH_DB = 15.0  # nguong canh bao soft (khong rollback) cho test RMSE


def _engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


@_celery_mod.celery_app.task(bind=True, name="retrain_ml_model")  # type: ignore[untyped-decorator]
def retrain_ml_model(self: Any, job_id: str) -> dict[str, Any]:
    eng = _engine()
    t_start = time.time()

    with eng.begin() as conn:
        row = conn.execute(
            text(
                "UPDATE audit.ml_retrain_jobs "
                "SET status='running', started_at=now(), celery_task_id=:tid "
                "WHERE id=:id "
                "RETURNING triggered_at, triggered_by"
            ),
            {"tid": self.request.id, "id": job_id},
        ).one()
    triggered_at_iso = row.triggered_at.isoformat() if row.triggered_at else ""
    triggered_by_id = str(row.triggered_by) if row.triggered_by else "(unknown)"

    report_dir = REPORTS_ROOT / f"retrain-{job_id}"

    # Step 1: rebuild CSV tu ts.survey_training (community rows) — DEM + landuse
    # feature engineering. Replaces the old static CSV (May 2026 snapshot).
    try:
        csv_proc = subprocess.run(
            [sys.executable, str(BUILD_CSV_SCRIPT_PATH)],
            capture_output=True,
            text=True,
            timeout=BUILD_CSV_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        elapsed = time.time() - t_start
        err = f"build_csv timeout after {BUILD_CSV_TIMEOUT_S}s: {exc!s}"
        _render_failure_report(report_dir, job_id, triggered_at_iso, triggered_by_id, err)
        with eng.begin() as conn:
            conn.execute(
                text(
                    "UPDATE audit.ml_retrain_jobs SET "
                    "status='failed', finished_at=now(), error_text=:err, report_dir=:rd "
                    "WHERE id=:id"
                ),
                {"err": err, "rd": str(report_dir), "id": job_id},
            )
        log.error("retrain job %s build_csv timed out after %.0fs", job_id, elapsed)
        return {"status": "failed", "error": "build_csv_timeout"}

    if csv_proc.returncode != 0:
        err = "build_csv failed: " + (csv_proc.stderr or "")[-3500:]
        _render_failure_report(report_dir, job_id, triggered_at_iso, triggered_by_id, err)
        with eng.begin() as conn:
            conn.execute(
                text(
                    "UPDATE audit.ml_retrain_jobs SET "
                    "status='failed', finished_at=now(), error_text=:err, report_dir=:rd "
                    "WHERE id=:id"
                ),
                {"err": err, "rd": str(report_dir), "id": job_id},
            )
        log.error("retrain job %s build_csv failed: exit=%d", job_id, csv_proc.returncode)
        return {"status": "failed", "exit_code": csv_proc.returncode, "step": "build_csv"}

    log.info("retrain job %s build_csv ok (%.0fs)", job_id, time.time() - t_start)

    # Step 2: train Extra Trees tren CSV moi.
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
        err = f"train timeout after {SUBPROCESS_TIMEOUT_S}s: {exc!s}"
        _render_failure_report(report_dir, job_id, triggered_at_iso, triggered_by_id, err)
        with eng.begin() as conn:
            conn.execute(
                text(
                    "UPDATE audit.ml_retrain_jobs SET "
                    "status='failed', finished_at=now(), error_text=:err, report_dir=:rd "
                    "WHERE id=:id"
                ),
                {"err": err, "rd": str(report_dir), "id": job_id},
            )
        log.error("retrain job %s timed out after %.0fs", job_id, elapsed)
        return {"status": "failed", "error": "timeout"}

    elapsed = time.time() - t_start
    if proc.returncode != 0:
        err = (proc.stderr or "")[-4000:]
        _render_failure_report(report_dir, job_id, triggered_at_iso, triggered_by_id, err)
        with eng.begin() as conn:
            conn.execute(
                text(
                    "UPDATE audit.ml_retrain_jobs SET "
                    "status='failed', finished_at=now(), error_text=:err, report_dir=:rd "
                    "WHERE id=:id"
                ),
                {"err": err, "rd": str(report_dir), "id": job_id},
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

    # Step 3: eval tren tap test (data_split='test' trong CSV) — viet
    # holdout_eval.json vao report_dir cho step 4 doc lai. Fail-soft.
    eval_status = _run_holdout_eval(report_dir, job_id)
    metrics["eval"] = eval_status

    # Doc val_metrics.json (train da viet) + holdout_eval.json (eval vua viet)
    # + train_split_stats.json (build_csv viet) → gop vao metrics audit.
    val_metrics_summary = _read_json_optional(VAL_METRICS_PATH)
    if val_metrics_summary:
        metrics["val"] = val_metrics_summary
    holdout_summary = _read_json_optional(report_dir / "holdout_eval.json")
    if holdout_summary and isinstance(holdout_summary.get("overall"), dict):
        metrics["test"] = holdout_summary["overall"]
        test_rmse = holdout_summary["overall"].get("rmse_db")
        if isinstance(test_rmse, (int, float)) and test_rmse > TEST_RMSE_HIGH_DB:
            metrics["warning"] = "test_rmse_high"
            log.warning(
                "retrain job %s test RMSE %.2f dB > %.1f dB nguong",
                job_id,
                test_rmse,
                TEST_RMSE_HIGH_DB,
            )
    split_stats = _read_json_optional(SPLIT_STATS_PATH)
    if split_stats:
        metrics["split_stats"] = split_stats

    # Hot-reload ml-service. Fail-soft: log warning + ghi vao metrics nhung
    # KHONG fail job (model file da swap xong, ml-service tu reload khi restart).
    reload_status = _call_ml_service_reload()
    if reload_status:
        metrics["ml_service_reload"] = reload_status

    # Render bao cao (plots + HTML + PDF). Fail-soft — neu fail, ghi log + bao
    # cao loi vao metrics nhung KHONG fail job (model da swap xong).
    report_status = _render_report(report_dir, job_id, triggered_at_iso, triggered_by_id)
    metrics["report"] = report_status

    with eng.begin() as conn:
        conn.execute(
            text(
                "UPDATE audit.ml_retrain_jobs SET "
                "status='succeeded', finished_at=now(), "
                "rows_trained=:rows, artifact_path=:art, "
                "metrics=CAST(:m AS jsonb), report_dir=:rd "
                "WHERE id=:id"
            ),
            {
                "rows": rows_trained,
                "art": str(ARTIFACT_PATH),
                "m": json.dumps(metrics),
                "rd": str(report_dir),
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


def _run_holdout_eval(report_dir: Path, job_id: str) -> dict[str, Any]:
    """Chay eval_extra_trees_holdout.py qua subprocess. Fail-soft: tra dict status.

    Eval doc CSV training (data_split='test'), khong cham DB, khong recompute DEM.
    Viet ket qua vao <report_dir>/holdout_eval.json.
    """
    report_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(EVAL_SCRIPT_PATH),
        "--out-dir",
        str(report_dir),
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=EVAL_TIMEOUT_S, check=False
        )
    except subprocess.TimeoutExpired:
        log.warning("Hold-out eval timeout for job %s", job_id)
        return {"status": "timeout"}
    if proc.returncode != 0:
        tail = (proc.stderr or "")[-1500:]
        log.warning("Hold-out eval failed for job %s: %s", job_id, tail)
        return {"status": "failed", "stderr_tail": tail}
    return {"status": "ok"}


def _read_json_optional(path: Path) -> dict[str, Any] | None:
    """Doc JSON neu file ton tai. Fail-soft: tra None khi loi."""
    if not path.exists():
        return None
    try:
        return cast("dict[str, Any]", json.loads(path.read_text()))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Khong doc duoc %s: %s", path, exc)
        return None


def _render_report(
    report_dir: Path, job_id: str, triggered_at: str, triggered_by: str
) -> dict[str, Any]:
    """Goi render_ml_report.py qua subprocess. Fail-soft: tra dict status."""
    report_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(REPORT_SCRIPT_PATH),
        "--out-dir",
        str(report_dir),
        "--job-id",
        job_id,
        "--triggered-at",
        triggered_at,
        "--triggered-by",
        triggered_by,
        "--holdout-json",
        str(report_dir / "holdout_eval.json"),
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=REPORT_TIMEOUT_S, check=False
        )
    except subprocess.TimeoutExpired:
        log.warning("Report render timeout for job %s", job_id)
        return {"status": "timeout"}
    if proc.returncode != 0:
        tail = (proc.stderr or "")[-1500:]
        log.warning("Report render failed for job %s: %s", job_id, tail)
        return {"status": "failed", "stderr_tail": tail}
    return {"status": "ok"}


def _render_failure_report(
    report_dir: Path, job_id: str, triggered_at: str, triggered_by: str, error_text: str
) -> None:
    """Mini-report cho failed job — chi summary.html voi loi.

    Fail-soft tuyet doi: bat moi exception, KHONG re-raise — bao cao loi
    khong duoc lam kep job da fail.
    """
    try:
        sys.path.insert(0, str(Path("/app/scripts")))
        from render_ml_report import render_failure_report  # type: ignore[import-not-found]

        report_dir.mkdir(parents=True, exist_ok=True)
        render_failure_report(
            report_dir,
            {
                "job_id": job_id,
                "triggered_at": triggered_at,
                "triggered_by": triggered_by,
                "generated_at": "",
            },
            error_text,
        )
    except Exception as exc:
        log.warning("Failure-report render failed for job %s: %s", job_id, exc)


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
        # joblib.load 122MB Extra Trees ~10-15s. Bump timeout đủ rộng cho
        # model lớn hơn trong tương lai (n_estimators=1500 hiện tại).
        resp = httpx.post(url, headers=headers, timeout=60.0)
        resp.raise_for_status()
        log.info("ml-service reload ok: %s", resp.json())
        return "ok"
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("ml-service reload failed: %s", exc)
        return f"failed: {exc!s}"
