"""Stage 2 retrain orchestrator — v2.0 pipeline.

Plan v2 §4.5. Pipeline:
  1. collect() → combined DataFrame (bỏ time-split của data.collect, dùng spatial).
  2. SpatialStratifiedSplitter.assign() → train_val vs test (cell-stratified hold-out).
  3. recalibrate() → Stage 1 fit report (không auto-update Stage 1 config).
  4. compute_feature_bounds(train_val) → bounds dict cho OODDetector.
  5. Spatial CV K=5 trên train_val → Optuna TPE 100 trials → best params.
  6. fit_final_model(train+val với early stop val nhỏ).
  7. Predict trên test → guardrail.clean → metrics (raw + after-guardrail).
  8. Compute PSI vs previous active model bounds (drift signal).
  9. save_artifact v2.0 + insert_run + (optional) promote.

Caller: scripts/retrain_stage2.py (CLI).

KHÔNG mutate Stage 1 EnvironmentalProfile — recal report là tín hiệu thôi.

12F V: training là build-time, KHÔNG chạy trong serving process.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd

from ..config import Settings
from . import registry_writer
from .bounds import compute_feature_bounds
from .data import CATEGORICAL_FEATURES, FEATURE_COLUMNS, collect
from .drift import population_stability_index
from .guardrail import (
    RESIDUAL_MAX_ABS_DB,
    RSSI_MAX_DBM,
    RSSI_MIN_DBM,
    clean,
)
from .objective import fit_final_model, run_optuna
from .spatial_cv import assign_spatial_folds
from .splitter import SpatialStratifiedSplitter
from .stage1_recal import Stage1RecalReport, recalibrate

log = logging.getLogger(__name__)


# Schema marker — tăng khi đổi artifact format (loader phải tương thích).
_ARTIFACT_SCHEMA_VERSION = "2.0"


@dataclass(frozen=True, slots=True)
class RetrainResult:
    """Output 1 lần retrain — caller dùng để audit + quyết định promote."""

    model_version: str
    run_id: str
    cv_rmse_mean: float
    cv_rmse_per_fold: list[float]
    test_rmse: float
    test_mae: float
    test_rmse_guardrail: float  # sau khi áp clip residual + clip RSSI
    n_guardrail_violations: int
    best_params: dict[str, Any]
    n_train_val: int
    n_test: int
    dataset_hash: str
    artifact_uri: str
    stage1_recal: Stage1RecalReport
    drift_psi: dict[str, float]  # per-feature PSI vs prev model bounds; rỗng nếu first run


# ── Helpers ───────────────────────────────────────────────────────────────────


def _compute_dataset_hash(train_val: pd.DataFrame, test: pd.DataFrame, target_col: str) -> str:
    """SHA256 trên (timestamp, lat, lon, target) — reproducibility marker."""
    parts = []
    for df in (train_val, test):
        h = pd.util.hash_pandas_object(
            df[["timestamp", "lat", "lon", target_col]],
            index=False,
        )
        parts.append(h.to_numpy().tobytes())
    return hashlib.sha256(b"".join(parts)).hexdigest()


def _make_model_version() -> str:
    return "stage2-" + datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")


def _apply_categorical_dtype(
    df: pd.DataFrame,
    categorical_cols: tuple[str, ...],
    category_maps: dict[str, list[Any]],
) -> pd.DataFrame:
    """In-place set category dtype với fixed category list (train-time snapshot).

    Lý do dùng fixed list thay vì .astype('category'):
      LightGBM cần SAME category mapping ở train/eval/predict. Nếu test có
      gateway mới, ta dùng pd.Categorical(values, categories=stored_list)
      → unseen value = NaN code (-1), LightGBM treat as missing và đi
      default direction. Hành vi xác định, repeatable.
    """
    out = df.copy()
    for col in categorical_cols:
        cats = category_maps[col]
        out[col] = pd.Categorical(out[col], categories=cats)
    return out


def _build_category_maps(
    train_df: pd.DataFrame,
    categorical_cols: tuple[str, ...],
) -> dict[str, list[Any]]:
    """Map từ category col → sorted list giá trị unique trong train.

    JSON-friendly (cast np scalar → native). Lưu vào meta.json để serving
    rebuild đúng pd.Categorical.
    """
    maps: dict[str, list[Any]] = {}
    for col in categorical_cols:
        uniques = sorted(train_df[col].dropna().unique().tolist())
        # numpy scalar → native cho JSON.
        maps[col] = [_to_native(v) for v in uniques]
    return maps


def _to_native(v: Any) -> Any:
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return float(v)
    return v


def _evaluate_residual(
    booster: lgb.Booster, x: pd.DataFrame, y: pd.Series
) -> tuple[float, float, np.ndarray]:
    pred = booster.predict(x, num_iteration=booster.best_iteration)
    err = y.to_numpy() - pred
    rmse = float(np.sqrt(np.mean(err**2)))
    mae = float(np.mean(np.abs(err)))
    return rmse, mae, np.asarray(pred, dtype=np.float64)


def _drift_psi_against_prev(
    settings: Settings,
    current_train: pd.DataFrame,
    feature_cols: tuple[str, ...],
    categorical_cols: tuple[str, ...],
) -> dict[str, float]:
    """Tính PSI từng feature numeric giữa train hiện tại vs train của model active.

    Đọc meta.json của active model qua registry. Nếu chưa có active model
    hoặc meta thiếu reference distribution → trả {}.

    Skip categorical: PSI cần distribution liên tục; categorical drift đo
    bằng category-set diff sẽ làm sau.
    """
    active = registry_writer.get_active_model_version(settings)
    if active is None:
        log.info("No previous active model → skip drift PSI")
        return {}
    _, prev_uri = active
    try:
        prev_meta = registry_writer.load_meta(prev_uri)
    except FileNotFoundError:
        log.warning("Previous artifact meta missing → skip drift PSI")
        return {}
    prev_ref = prev_meta.get("reference_distribution")
    if not prev_ref:
        log.info("Previous meta lacks reference_distribution → skip drift PSI")
        return {}

    cat_set = set(categorical_cols)
    psi: dict[str, float] = {}
    for col in feature_cols:
        if col in cat_set or col not in prev_ref:
            continue
        reference = np.asarray(prev_ref[col], dtype=np.float64)
        current = current_train[col].to_numpy(dtype=np.float64)
        try:
            psi[col] = population_stability_index(reference, current)
        except ValueError:
            continue
    if psi:
        log.info("Drift PSI vs previous model: %s", {k: f"{v:.3f}" for k, v in psi.items()})
    return psi


def _reference_distribution(
    train_df: pd.DataFrame,
    feature_cols: tuple[str, ...],
    categorical_cols: tuple[str, ...],
    sample_n: int = 1000,
) -> dict[str, list[float]]:
    """Sub-sample numeric train distribution để lưu meta.json cho PSI lần sau.

    1000 sample đủ ổn định cho PSI 10-bin (mỗi bin ~100 sample). Full data quá
    nặng cho JSON; sub-sample deterministic theo seed cũng tạo reproducible PSI.
    """
    rng = np.random.default_rng(42)
    n = min(sample_n, len(train_df))
    idx = rng.choice(len(train_df), size=n, replace=False)
    sub = train_df.iloc[idx]
    cat_set = set(categorical_cols)
    ref: dict[str, list[float]] = {}
    for col in feature_cols:
        if col in cat_set:
            continue
        ref[col] = [float(v) for v in sub[col].to_numpy()]
    return ref


# ── Main orchestration ───────────────────────────────────────────────────────


def run_retrain(settings: Settings, auto_promote: bool = False) -> RetrainResult:
    """End-to-end retrain. Trả RetrainResult; KHÔNG promote nếu auto_promote=False.

    Default không promote: caller (CLI / cron) phải inspect drift_psi + test
    metrics + recal report trước khi swap active model.
    """
    log.info("Stage 2 retrain start (env_profile=%s)", settings.env_profile)

    # 1. Fetch + Stage1 residual + features. data.collect() đã time-split nhưng
    #    plan v2 dùng spatial split → concat lại rồi split tay.
    tf = collect(settings)
    combined = pd.concat([tf.train_val, tf.test], ignore_index=True)
    log.info("Combined dataset: %d rows", len(combined))

    # 2. Spatial stratified split (cell hold-out).
    splitter = SpatialStratifiedSplitter(seed=settings.optuna_seed)
    split_labels = splitter.assign(combined)
    train_val_df = combined[split_labels == "train"].reset_index(drop=True)
    test_df = combined[split_labels == "test"].reset_index(drop=True)
    split_report = splitter.last_report
    log.info(
        "Spatial split: train=%d, test=%d, test_frac=%.3f",
        split_report.n_train if split_report else -1,
        split_report.n_test if split_report else -1,
        split_report.test_fraction_actual if split_report else -1,
    )
    if len(train_val_df) < settings.spatial_kfold:
        msg = f"train_val rows ({len(train_val_df)}) < spatial_kfold ({settings.spatial_kfold})"
        raise RuntimeError(msg)

    # 3. Stage 1 recal report (signal-only, không tự đổi config).
    #    ITU model không có exponent → recal trả bias + σ residual.
    recal_report = recalibrate(train_val_df)

    # 4. Feature bounds cho OODDetector (chỉ trên train).
    feature_bounds = compute_feature_bounds(
        train_val_df,
        feature_cols=FEATURE_COLUMNS,
        categorical_cols=CATEGORICAL_FEATURES,
    )

    # 5. Category mapping cố định từ train — đảm bảo predict-time consistency.
    category_maps = _build_category_maps(train_val_df, CATEGORICAL_FEATURES)
    train_val_cat = _apply_categorical_dtype(train_val_df, CATEGORICAL_FEATURES, category_maps)
    test_cat = _apply_categorical_dtype(test_df, CATEGORICAL_FEATURES, category_maps)

    # 6. Spatial CV folds trong train_val + Optuna.
    folds = assign_spatial_folds(
        train_val_cat,
        k=settings.spatial_kfold,
        seed=settings.optuna_seed,
    )
    log.info("Spatial CV folds: %s", np.bincount(folds).tolist())

    x_tv = train_val_cat[list(FEATURE_COLUMNS)]
    y_tv = train_val_cat[tf.target_column]
    study = run_optuna(
        x_tv, y_tv, folds, n_trials=settings.optuna_trials, seed=settings.optuna_seed
    )

    # 7. Final refit. Tách 1 val nhỏ trong train_val cho early stop.
    rng = np.random.default_rng(settings.optuna_seed)
    perm = rng.permutation(len(train_val_cat))
    n_val = max(1, int(len(train_val_cat) * 0.2))
    val_idx_arr, train_idx_arr = perm[:n_val], perm[n_val:]
    train_part = train_val_cat.iloc[train_idx_arr].reset_index(drop=True)
    val_part = train_val_cat.iloc[val_idx_arr].reset_index(drop=True)

    booster = fit_final_model(
        x_train=train_part[list(FEATURE_COLUMNS)],
        y_train=train_part[tf.target_column],
        x_val=val_part[list(FEATURE_COLUMNS)],
        y_val=val_part[tf.target_column],
        best_params=study.best_params,
        seed=settings.optuna_seed,
    )

    # 8. Evaluate test — raw RMSE trên residual + guardrail RMSE trên RSSI cuối.
    x_test = test_cat[list(FEATURE_COLUMNS)]
    y_test_residual = test_cat[tf.target_column]
    test_rmse, test_mae, residual_pred = _evaluate_residual(booster, x_test, y_test_residual)
    log.info("Test raw residual: rmse=%.3f mae=%.3f n=%d", test_rmse, test_mae, len(test_df))

    # Guardrail trên RSSI tổng. rssi_stage1 = rssi_measured - residual_truth.
    rssi_measured = test_df["rssi_dbm_measured"].to_numpy(dtype=np.float64)
    rssi_stage1 = rssi_measured - y_test_residual.to_numpy(dtype=np.float64)
    rssi_final, violated = clean(rssi_stage1, residual_pred)
    rssi_err = rssi_measured - rssi_final
    test_rmse_guardrail = float(np.sqrt(np.mean(rssi_err**2)))
    n_violations = int(violated.sum())
    log.info(
        "Test after guardrail: rssi_rmse=%.3f (n_clip=%d/%d)",
        test_rmse_guardrail,
        n_violations,
        len(violated),
    )

    # 9. Drift PSI vs previous active model.
    drift_psi = _drift_psi_against_prev(
        settings,
        current_train=train_val_df,
        feature_cols=FEATURE_COLUMNS,
        categorical_cols=CATEGORICAL_FEATURES,
    )

    # 10. Persist artifact + registry.
    model_version = _make_model_version()
    dataset_hash = _compute_dataset_hash(train_val_df, test_df, tf.target_column)
    metrics = {
        "cv_rmse_mean": float(study.best_value),
        "cv_rmse_per_fold": list(study.best_trial.user_attrs.get("fold_rmses", [])),
        "test_rmse": test_rmse,
        "test_mae": test_mae,
        "test_rmse_guardrail": test_rmse_guardrail,
        "n_guardrail_violations": n_violations,
        "n_train_val": len(train_val_df),
        "n_test": len(test_df),
    }
    meta: dict[str, Any] = {
        "schema_version": _ARTIFACT_SCHEMA_VERSION,
        "feature_columns": list(FEATURE_COLUMNS),
        "categorical_features": list(CATEGORICAL_FEATURES),
        "category_maps": category_maps,
        "target_column": tf.target_column,
        "env_profile": settings.env_profile,
        "train_bbox": {
            "min_lat": settings.train_bbox_min_lat,
            "max_lat": settings.train_bbox_max_lat,
            "min_lon": settings.train_bbox_min_lon,
            "max_lon": settings.train_bbox_max_lon,
        },
        "split": {
            "strategy": "spatial_grid_stratified_holdout",
            "cell_size_deg": splitter.cell_size_deg,
            "test_fraction": 0.2,
            "n_train_cells": split_report.n_train_cells if split_report else None,
            "n_test_cells": split_report.n_test_cells if split_report else None,
            "test_fraction_actual": split_report.test_fraction_actual if split_report else None,
        },
        "feature_bounds": feature_bounds,
        "guardrail": {
            "residual_max_abs_db": RESIDUAL_MAX_ABS_DB,
            "rssi_min_dbm": RSSI_MIN_DBM,
            "rssi_max_dbm": RSSI_MAX_DBM,
        },
        "stage1_recal": {
            "bias_db": recal_report.bias_db,
            "sigma_db": recal_report.sigma_db,
            "n_samples": recal_report.n_samples,
            "bias_review_threshold_db": recal_report.bias_review_threshold_db,
            "sigma_review_threshold_db": recal_report.sigma_review_threshold_db,
            "recommend_review": recal_report.recommend_review,
        },
        "drift_psi_vs_prev": drift_psi,
        "reference_distribution": _reference_distribution(
            train_val_df, FEATURE_COLUMNS, CATEGORICAL_FEATURES
        ),
        "metrics": metrics,
        "hyperparams": study.best_params,
        "dataset_hash": dataset_hash,
    }

    paths = registry_writer.save_artifact(settings, model_version, booster, meta)
    run_id = registry_writer.insert_run(
        settings,
        model_version=model_version,
        dataset_hash=dataset_hash,
        artifact_uri=str(paths.model_file),
        metrics=metrics,
        hyperparams=study.best_params,
        notes=(
            f"v2 spatial split; optuna {settings.optuna_trials} trials; "
            f"K={settings.spatial_kfold}; "
            f"recal bias={recal_report.bias_db:+.2f}dB σ={recal_report.sigma_db:.2f}dB"
        ),
    )

    if auto_promote:
        log.info("auto_promote=True → promoting %s", model_version)
        registry_writer.promote(settings, model_version)

    return RetrainResult(
        model_version=model_version,
        run_id=str(run_id),
        cv_rmse_mean=float(study.best_value),
        cv_rmse_per_fold=list(study.best_trial.user_attrs.get("fold_rmses", [])),
        test_rmse=test_rmse,
        test_mae=test_mae,
        test_rmse_guardrail=test_rmse_guardrail,
        n_guardrail_violations=n_violations,
        best_params=dict(study.best_params),
        n_train_val=len(train_val_df),
        n_test=len(test_df),
        dataset_hash=dataset_hash,
        artifact_uri=str(paths.model_file),
        stage1_recal=recal_report,
        drift_psi=drift_psi,
    )


# ── CLI ───────────────────────────────────────────────────────────────────────


def main() -> int:
    """`python -m lora_ml_predict.training.retrain [--promote]` entrypoint."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--promote",
        action="store_true",
        help="Auto-promote new model to active after train",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )

    from ..config import get_settings

    settings = get_settings()
    result = run_retrain(settings, auto_promote=args.promote)
    print(
        json.dumps(
            {
                "model_version": result.model_version,
                "run_id": result.run_id,
                "cv_rmse_mean": result.cv_rmse_mean,
                "test_rmse": result.test_rmse,
                "test_rmse_guardrail": result.test_rmse_guardrail,
                "n_guardrail_violations": result.n_guardrail_violations,
                "stage1_recal_bias_db": result.stage1_recal.bias_db,
                "stage1_recal_sigma_db": result.stage1_recal.sigma_db,
                "stage1_recal_recommend_review": result.stage1_recal.recommend_review,
                "drift_psi": result.drift_psi,
                "artifact_uri": result.artifact_uri,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
