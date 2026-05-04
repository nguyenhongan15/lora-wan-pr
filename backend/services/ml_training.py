"""
services/ml_training.py — Orchestrate ML model training.

Router chỉ gọi train_from_rows() — không biết chi tiết feature engineering.
"""

from __future__ import annotations

import logging

import numpy as np

from ml.dem import get_dem
from ml.dem_predict_patch import enrich_with_dem
from ml.features import engineer_dataframe
from ml.model_store import ModelBundle, save
from ml.trainer import train

logger = logging.getLogger(__name__)


def train_from_rows(
    rows: list[dict],
    *,
    algorithm: str = "xgboost",
    hyperparameters: dict | None = None,
    n_cv_splits: int = 5,
) -> ModelBundle:
    """
    Pipeline: enrich DEM → engineer features → train → save bundle.

    rows: list dict với keys: lat_rx, lng_rx, lat_tx, lng_tx, rssi_dbm, ...
    """
    dem  = get_dem()
    rows = enrich_with_dem(rows, dem)

    df   = engineer_dataframe(rows, dem=dem)
    y    = np.array([r["rssi_dbm"] for r in rows], dtype=float)

    bundle = train(
        df, y,
        algorithm=algorithm,
        hyperparameters=hyperparameters,
        n_cv_splits=n_cv_splits,
    )
    save(bundle)

    logger.info("model_trained", extra={
        "model_id": bundle.model_id,
        "algorithm": bundle.algorithm,
        "n_samples": len(rows),
        "rmse_db":  bundle.metrics.get("rmse_db"),
        "r2_score": bundle.metrics.get("r2_score"),
    })
    return bundle
