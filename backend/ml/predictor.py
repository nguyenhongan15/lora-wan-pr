"""
ml/predictor.py — Dự đoán RSSI trên grid không gian từ model đã train.

Nhận:
  - ModelBundle (từ model_store)
  - Danh sách tọa độ grid (lat, lng)
  - Thông tin gateway (lat, lng, altitude, antenna_height)
  - DEMReader (optional)
  - Thông tin campaign default (SF, freq, land_use, building_density)

Trả về:
  - predicted: np.ndarray RSSI (dBm)
  - uncertainty: np.ndarray std dev (dBm) — 0 nếu model không hỗ trợ
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

from ml.features import FEATURE_NAMES, engineer_row
from ml.model_store import ModelBundle

if TYPE_CHECKING:
    from ml.dem import DEMReader

logger = logging.getLogger(__name__)


def predict_grid(
    bundle: ModelBundle,
    grid_lats: np.ndarray,
    grid_lngs: np.ndarray,
    gateways: list[dict],
    dem: "DEMReader | None" = None,
    campaign_defaults: dict | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Dự đoán RSSI cho từng điểm grid, multi-gateway.

    LoRaWAN star-of-stars (TS002 §6): 1 packet uplink được nhiều gateway nhận;
    coverage tại 1 điểm = max RSSI giữa các gateway nghe được. Hàm này predict
    riêng cho từng gateway rồi aggregate bằng argmax per grid point.

    Parameters
    ----------
    bundle           : ModelBundle đã load từ model_store
    grid_lats/lngs   : tọa độ các điểm lưới (shape N,)
    gateways         : list dict, mỗi gateway có keys:
                       lat, lng, altitude_m, antenna_height_m
    dem              : DEMReader (nếu None → bỏ qua DEM features)
    campaign_defaults: dict với spreading_factor, freq_mhz, building_density, land_use

    Returns
    -------
    predicted   : np.ndarray (N,) — RSSI dBm (max trên các gateway)
    uncertainty : np.ndarray (N,) — std dBm tại gateway có RSSI cao nhất
    """
    defaults = campaign_defaults or {}
    n_grid = len(grid_lats)

    if not gateways:
        empty = np.zeros(n_grid)
        return empty, empty

    # Imports dùng chung cho mọi gateway
    from ml.features import engineer_dataframe
    from sklearn.gaussian_process import GaussianProcessRegressor

    model = bundle.model
    quantile_models = getattr(bundle, "quantile_models", None) or {}

    # ── Predict per gateway ────────────────────────────────────────────────
    all_predicted   = np.full((len(gateways), n_grid), -140.0, dtype=float)
    all_uncertainty = np.zeros((len(gateways), n_grid), dtype=float)

    for gw_idx, gateway in enumerate(gateways):
        rows = []
        for lat_rx, lng_rx in zip(grid_lats, grid_lngs):
            rows.append({
                "lat_rx"            : lat_rx,
                "lng_rx"            : lng_rx,
                "lat_tx"            : gateway["lat"],
                "lng_tx"            : gateway["lng"],
                "h_rx"              : 1.5,   # thiết bị cầm tay mặc định
                "h_tx"              : float(gateway.get("antenna_height_m") or 10.0),
                "spreading_factor"  : defaults.get("spreading_factor", 9),
                "freq_mhz"          : defaults.get("freq_mhz", 868.0),
                "building_density"  : defaults.get("building_density", 0.3),
                "land_use"          : defaults.get("land_use", "rural"),
                "obstacle_count_los": 0,
            })

        df_feat = engineer_dataframe(rows, dem=dem)
        X = df_feat[FEATURE_NAMES].values.astype(float)

        if len(X) == 0:
            continue

        X_sc = bundle.scaler.transform(X)

        if isinstance(model, GaussianProcessRegressor):
            predicted, std = model.predict(X_sc, return_std=True)
            uncertainty = std.astype(float)
        else:
            predicted = model.predict(X_sc)
            if quantile_models:
                q10 = quantile_models["q10"].predict(X_sc)
                q90 = quantile_models["q90"].predict(X_sc)
                uncertainty = (q90 - q10) / 2.0
            else:
                uncertainty = _estimate_uncertainty_rf(model, X_sc)

        all_predicted[gw_idx]   = predicted.astype(float)
        all_uncertainty[gw_idx] = np.clip(uncertainty.astype(float), 0.0, None)

    # ── Aggregate: max RSSI per grid point, lấy uncertainty của best GW ────
    best_gw_idx = np.argmax(all_predicted, axis=0)
    grid_idx    = np.arange(n_grid)
    final_predicted   = all_predicted[best_gw_idx, grid_idx]
    final_uncertainty = all_uncertainty[best_gw_idx, grid_idx]

    # Clamp RSSI trong khoảng vật lý hợp lý (-140 → -30 dBm)
    final_predicted = np.clip(final_predicted, -140.0, -30.0)

    logger.info(
        "[Predictor] %d grid pts × %d GW | RSSI %.1f–%.1f dBm",
        n_grid, len(gateways), final_predicted.min(), final_predicted.max(),
    )
    return final_predicted, final_uncertainty


def _estimate_uncertainty_rf(model, X_sc: np.ndarray) -> np.ndarray:
    """
    Ước tính uncertainty cho Random Forest bằng std của các tree predictions.
    Trả về mảng 0 nếu model không phải RF.
    """
    from sklearn.ensemble import RandomForestRegressor

    if not isinstance(model, RandomForestRegressor):
        return np.zeros(len(X_sc))

    # Dự đoán từng tree
    tree_preds = np.array([
        tree.predict(X_sc) for tree in model.estimators_
    ])   # shape: (n_trees, n_samples)

    return tree_preds.std(axis=0)