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
ML_DATA_DIR = Path("/app/services/ml-service/data")
METRICS_PATH = ML_DATA_DIR / "train_metrics.json"
VAL_METRICS_PATH = ML_DATA_DIR / "val_metrics.json"
SPLIT_STATS_PATH = ML_DATA_DIR / "train_split_stats.json"
ARTIFACT_PATH = ML_DATA_DIR / "extra_trees_model.joblib"

# Candidate artifacts — train --candidate ghi ra day, promotion gate moi swap
# sang active (ARTIFACT_PATH) neu dat nguong.
CANDIDATE_ARTIFACT_PATH = ML_DATA_DIR / "extra_trees_model.candidate.joblib"
CANDIDATE_METRICS_PATH = ML_DATA_DIR / "train_metrics.candidate.json"
CANDIDATE_VAL_METRICS_PATH = ML_DATA_DIR / "val_metrics.candidate.json"
CANDIDATE_FALLBACK_PATH = ML_DATA_DIR / "terrain_fallback.candidate.json"
CANDIDATE_GATEWAY_TABLE_PATH = ML_DATA_DIR / "gateway_table.candidate.csv"
ACTIVE_FALLBACK_PATH = ML_DATA_DIR / "terrain_fallback.json"
ACTIVE_GATEWAY_TABLE_PATH = ML_DATA_DIR / "gateway_table.csv"
# Snapshot val/test metrics cua model dang active (ghi luc promote) — promotion
# gate doc lai de so sanh "candidate co tệ hơn active không".
ACTIVE_MODEL_METRICS_PATH = ML_DATA_DIR / "active_model_metrics.json"

REPORTS_ROOT = Path("/app/reports")
SUBPROCESS_TIMEOUT_S = 3600  # 1h — bao gom build CSV (5-30 phut) + train (~1 phut)
BUILD_CSV_TIMEOUT_S = 2400  # 40 phut — terrain sampling cho ~10k+ rows
EVAL_TIMEOUT_S = 300  # 5 phut — predict 1500 row test split, khong DEM lookup
REPORT_TIMEOUT_S = 600  # 10 phut — du cho hold-out eval + plot + PDF
TEST_RMSE_HIGH_DB = 15.0  # nguong tuyet doi: candidate test RMSE > nguong -> KHONG promote
# Candidate val RMSE duoc phep tệ hơn active toi da bao nhieu dB thi van promote.
# Luu y: val split duoc tinh lai moi lan build_csv (data thay doi) nen so sanh
# nay la xap xi, khong phai cung 1 tap val — dung lam regression-guard mem.
VAL_RMSE_REGRESSION_TOLERANCE_DB = 1.0


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

    # Step 2: train Extra Trees tren CSV moi -> ghi ra artifact .candidate
    # (KHONG dung model active; promotion gate o Step 4 moi swap neu dat).
    cmd = [sys.executable, str(SCRIPT_PATH), "--candidate"]
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
        metrics_raw = json.loads(CANDIDATE_METRICS_PATH.read_text())
        rows_trained = int(metrics_raw.pop("rows_trained", 0)) or None
        metrics = metrics_raw
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        log.warning("retrain job %s succeeded but metrics read failed: %s", job_id, exc)

    # Step 3: eval candidate tren tap test (data_split='test' trong CSV) — viet
    # holdout_eval.json vao report_dir cho step 4/report doc lai. Fail-soft.
    eval_status = _run_holdout_eval(report_dir, job_id, model_path=CANDIDATE_ARTIFACT_PATH)
    metrics["eval"] = eval_status

    # Doc candidate val + holdout test + split stats → gop vao metrics audit.
    candidate_val = _read_json_optional(CANDIDATE_VAL_METRICS_PATH)
    if candidate_val:
        metrics["val"] = candidate_val
    holdout_summary = _read_json_optional(report_dir / "holdout_eval.json")
    candidate_test: dict[str, Any] | None = None
    if holdout_summary and isinstance(holdout_summary.get("overall"), dict):
        candidate_test = holdout_summary["overall"]
        metrics["test"] = candidate_test
    split_stats = _read_json_optional(SPLIT_STATS_PATH)
    if split_stats:
        metrics["split_stats"] = split_stats

    # Step 4: PROMOTION GATE — chi swap candidate -> active khi dat nguong.
    # Chong day model kem len production (truoc day model luon bi ghi de).
    active_metrics = _read_json_optional(ACTIVE_MODEL_METRICS_PATH)
    promote, reason = _promotion_decision(candidate_val, candidate_test, active_metrics)
    metrics["promoted"] = promote
    metrics["promotion_reason"] = reason

    if promote:
        try:
            _promote_candidate(candidate_val, candidate_test)
            log.info("retrain job %s PROMOTED candidate -> active (%s)", job_id, reason)
        except OSError as exc:
            # Swap loi (vd. disk) — giu model cu, danh dau khong promote.
            metrics["promoted"] = False
            metrics["promotion_reason"] = f"promote IO error: {exc!s}"
            log.error("retrain job %s promote failed: %s", job_id, exc)
            promote = False
        else:
            # Hot-reload ml-service chi khi da swap artifact moi. Fail-soft.
            reload_status = _call_ml_service_reload()
            if reload_status:
                metrics["ml_service_reload"] = reload_status
    else:
        _discard_candidate()
        log.warning("retrain job %s NOT promoted: %s", job_id, reason)

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


def _run_holdout_eval(
    report_dir: Path, job_id: str, model_path: Path = ARTIFACT_PATH
) -> dict[str, Any]:
    """Chay eval_extra_trees_holdout.py qua subprocess. Fail-soft: tra dict status.

    Eval doc CSV training (data_split='test'), khong cham DB, khong recompute DEM.
    Viet ket qua vao <report_dir>/holdout_eval.json. `model_path` mac dinh model
    active; retrain truyen .candidate de eval truoc khi promote.
    """
    report_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(EVAL_SCRIPT_PATH),
        "--out-dir",
        str(report_dir),
        "--model",
        str(model_path),
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


def _promotion_decision(
    candidate_val: dict[str, Any] | None,
    candidate_test: dict[str, Any] | None,
    active_metrics: dict[str, Any] | None,
) -> tuple[bool, str]:
    """Quyet dinh co swap candidate -> active khong.

    Quy tac:
      1. Sanity tuyet doi: candidate test RMSE phai <= TEST_RMSE_HIGH_DB.
      2. Bootstrap: chua co model active (hoac chua co metrics snapshot) -> promote
         neu qua (1).
      3. Regression-guard: candidate val RMSE khong duoc tệ hơn active qua
         VAL_RMSE_REGRESSION_TOLERANCE_DB.
    Thieu metric (None) -> bo qua check tuong ung (fail-open ve phia promote, tru
    khi test RMSE vuot nguong tuyet doi).
    """
    test_rmse = candidate_test.get("rmse_db") if candidate_test else None
    if isinstance(test_rmse, (int, float)) and test_rmse > TEST_RMSE_HIGH_DB:
        return False, f"test RMSE {test_rmse:.2f} dB > nguong {TEST_RMSE_HIGH_DB:.1f} dB"

    if not ARTIFACT_PATH.exists() or not active_metrics:
        return True, "bootstrap (chua co model active de so sanh)"

    cand_val_rmse = candidate_val.get("rmse") if candidate_val else None
    active_val = active_metrics.get("val") if isinstance(active_metrics.get("val"), dict) else None
    active_val_rmse = active_val.get("rmse") if active_val else None
    if isinstance(cand_val_rmse, (int, float)) and isinstance(active_val_rmse, (int, float)):
        if cand_val_rmse > active_val_rmse + VAL_RMSE_REGRESSION_TOLERANCE_DB:
            return False, (
                f"val RMSE {cand_val_rmse:.2f} dB tệ hơn active {active_val_rmse:.2f} dB "
                f"quá nguong {VAL_RMSE_REGRESSION_TOLERANCE_DB:.1f} dB"
            )
        return True, (
            f"val RMSE {cand_val_rmse:.2f} dB vs active {active_val_rmse:.2f} dB — dat nguong"
        )
    return True, "dat sanity test RMSE (thieu val metric de so sanh active)"


def _promote_candidate(
    candidate_val: dict[str, Any] | None,
    candidate_test: dict[str, Any] | None,
) -> None:
    """Atomic-swap candidate -> active + dong bo metrics/aux files.

    `.replace()` la atomic rename tren cung filesystem (ML_DATA_DIR) — ml-service
    khong bao gio doc file ban do.
    """
    CANDIDATE_ARTIFACT_PATH.replace(ARTIFACT_PATH)
    # Dong bo metrics + aux artifacts cua candidate sang ten active.
    for src, dst in (
        (CANDIDATE_METRICS_PATH, METRICS_PATH),
        (CANDIDATE_VAL_METRICS_PATH, VAL_METRICS_PATH),
        (CANDIDATE_FALLBACK_PATH, ACTIVE_FALLBACK_PATH),
        (CANDIDATE_GATEWAY_TABLE_PATH, ACTIVE_GATEWAY_TABLE_PATH),
    ):
        if src.exists():
            src.replace(dst)
    # Snapshot metrics cua model vua promote — lan retrain sau doc lai de so sanh.
    snapshot = {"val": candidate_val or {}, "test": candidate_test or {}}
    ACTIVE_MODEL_METRICS_PATH.write_text(json.dumps(snapshot, indent=2))


def _discard_candidate() -> None:
    """Xoa cac file candidate khi khong promote (giu model active nguyen ven)."""
    for path in (
        CANDIDATE_ARTIFACT_PATH,
        CANDIDATE_METRICS_PATH,
        CANDIDATE_VAL_METRICS_PATH,
        CANDIDATE_FALLBACK_PATH,
        CANDIDATE_GATEWAY_TABLE_PATH,
    ):
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            log.warning("Khong xoa duoc candidate %s: %s", path, exc)


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
