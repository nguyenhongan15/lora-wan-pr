"""
services/ml_inference.py — Orchestrate ML inference trên grid.
"""

from __future__ import annotations

import logging

import numpy as np

from ml.dem import get_dem
from ml.model_store import load
from ml.predictor import predict_grid

logger = logging.getLogger(__name__)


def infer_on_grid(
    ml_model_id: str,
    grid_lats:   np.ndarray,
    grid_lngs:   np.ndarray,
    gateways:    list[dict],
    campaign_defaults: dict | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Load model bundle + chạy predict trên lưới tọa độ (multi-gateway aggregate).
    Return: (predicted_rssi, uncertainty)
    """
    dem    = get_dem()
    bundle = load(ml_model_id)

    predicted, unc = predict_grid(
        bundle, grid_lats, grid_lngs, gateways,
        dem=dem, campaign_defaults=campaign_defaults or {},
    )

    logger.info("model_inference", extra={
        "model_id": ml_model_id,
        "n_gateways": len(gateways),
        "grid_points": len(grid_lats),
        "rssi_min": float(predicted.min()),
        "rssi_max": float(predicted.max()),
    })
    return predicted, unc