"""Composition root cho Stage 2 training pipeline.

Plan v1 §4.5. Glue:
    data.collect → spatial_cv.assign_spatial_folds → objective.run_optuna
    → objective.fit_final_model → metrics → registry_writer.save_artifact
    → registry_writer.insert_run → (optional) promote.

Caller: scripts/train_stage2.py (CLI).

12F V (build/release/run): training là build-time, KHÔNG chạy trong serving server.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd

from ..config import Settings
from . import registry_writer
from .data import TrainingFrame, collect
from .objective import fit_final_model, run_optuna
from .spatial_cv import assign_spatial_folds

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TrainingResult:
    """Tổng hợp output 1 lần train.

    Dùng cho audit + decide có gọi promote() không (caller-driven).
    """

    model_version: str
    run_id: str
    cv_rmse_mean: float
    cv_rmse_per_fold: list[float]
    test_rmse: float
    test_mae: float
    best_params: dict[str, Any]
    n_train_val: int
    n_test: int
    dataset_hash: str
    artifact_uri: str


def _compute_dataset_hash(tf: TrainingFrame) -> str:
    """SHA256 trên (timestamp, lat, lon, residual) row-by-row.

    Reproducibility: cùng dataset → cùng hash → có thể detect data drift.
    Plan §6 schema column dataset_hash CHAR(64).
    """
    parts = []
    for df in (tf.train_val, tf.test):
        h = pd.util.hash_pandas_object(
            df[["timestamp", "lat", "lon", tf.target_column]],
            index=False,
        )
        parts.append(h.to_numpy().tobytes())
    full = b"".join(parts)
    return hashlib.sha256(full).hexdigest()


def _split_train_val(
    train_val_df: pd.DataFrame,
    val_fraction: float = 0.2,
    seed: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Random split train_val → final-fit train vs early-stop val.

    Spatial fold dùng cho hyperparameter CV; sau khi đã chọn best params, refit
    cần 1 val nhỏ cho early stopping (không leakage vì best params đã chốt).
    """
    n = len(train_val_df)
    rng = np.random.default_rng(seed)
    idx = rng.permutation(n)
    n_val = max(1, int(n * val_fraction))
    val_idx = idx[:n_val]
    train_idx = idx[n_val:]
    return (
        train_val_df.iloc[train_idx].reset_index(drop=True),
        train_val_df.iloc[val_idx].reset_index(drop=True),
    )


def _evaluate(booster: lgb.Booster, x: pd.DataFrame, y: pd.Series) -> tuple[float, float]:
    pred = booster.predict(x, num_iteration=booster.best_iteration)
    err = y.to_numpy() - pred
    rmse = float(np.sqrt(np.mean(err**2)))
    mae = float(np.mean(np.abs(err)))
    return rmse, mae


def _make_model_version() -> str:
    """Timestamp-based version. Đảm bảo unique trong (domain, stage) (migration 0011 UNIQUE)."""
    return "stage2-" + datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")


def run_training(settings: Settings, auto_promote: bool = False) -> TrainingResult:
    """End-to-end training. Trả TrainingResult; KHÔNG promote nếu auto_promote=False.

    Lý do default không promote: caller có thể muốn inspect metrics trước khi
    swap active model (defensive). CLI cần --promote flag.
    """
    log.info("Stage 2 training start (env_profile=%s)", settings.env_profile)
    tf = collect(settings)

    if len(tf.train_val) < settings.spatial_kfold:
        msg = f"Not enough train+val rows ({len(tf.train_val)}) for {settings.spatial_kfold}-fold"
        raise RuntimeError(msg)

    folds = assign_spatial_folds(
        tf.train_val,
        k=settings.spatial_kfold,
        seed=settings.optuna_seed,
    )
    log.info("Spatial folds: %s", np.bincount(folds).tolist())

    x_tv = tf.train_val[list(tf.feature_columns)]
    y_tv = tf.train_val[tf.target_column]

    study = run_optuna(
        x_tv, y_tv, folds, n_trials=settings.optuna_trials, seed=settings.optuna_seed
    )

    # Refit on full train+val (spatial CV đã dùng để chọn params; final fit cần val nhỏ
    # cho early stop chứ không phải để chọn model).
    train_df, val_df = _split_train_val(tf.train_val, seed=settings.optuna_seed)
    booster = fit_final_model(
        x_train=train_df[list(tf.feature_columns)],
        y_train=train_df[tf.target_column],
        x_val=val_df[list(tf.feature_columns)],
        y_val=val_df[tf.target_column],
        best_params=study.best_params,
        seed=settings.optuna_seed,
    )

    x_test = tf.test[list(tf.feature_columns)]
    y_test = tf.test[tf.target_column]
    test_rmse, test_mae = _evaluate(booster, x_test, y_test)
    log.info("Hold-out test: rmse=%.3f mae=%.3f n=%d", test_rmse, test_mae, len(tf.test))

    # Persist artifact + registry.
    model_version = _make_model_version()
    dataset_hash = _compute_dataset_hash(tf)
    metrics = {
        "cv_rmse_mean": float(study.best_value),
        "cv_rmse_per_fold": study.best_trial.user_attrs.get("fold_rmses", []),
        "test_rmse": test_rmse,
        "test_mae": test_mae,
        "n_train_val": len(tf.train_val),
        "n_test": len(tf.test),
    }
    meta = {
        "feature_columns": list(tf.feature_columns),
        "target_column": tf.target_column,
        "env_profile": settings.env_profile,
        "train_bbox": {
            "min_lat": settings.train_bbox_min_lat,
            "max_lat": settings.train_bbox_max_lat,
            "min_lon": settings.train_bbox_min_lon,
            "max_lon": settings.train_bbox_max_lon,
        },
        "train_val_period": [settings.train_val_start, settings.train_val_end],
        "test_period": [settings.test_start, settings.test_end],
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
        notes=f"optuna {settings.optuna_trials} trials; spatial K={settings.spatial_kfold}",
    )

    if auto_promote:
        log.info("auto_promote=True → promoting %s", model_version)
        registry_writer.promote(settings, model_version)

    return TrainingResult(
        model_version=model_version,
        run_id=str(run_id),
        cv_rmse_mean=float(study.best_value),
        cv_rmse_per_fold=list(study.best_trial.user_attrs.get("fold_rmses", [])),
        test_rmse=test_rmse,
        test_mae=test_mae,
        best_params=dict(study.best_params),
        n_train_val=len(tf.train_val),
        n_test=len(tf.test),
        dataset_hash=dataset_hash,
        artifact_uri=str(paths.model_file),
    )
