"""
ml/trainer.py — Huấn luyện XGBoost, Random Forest, Gaussian Process.

Luồng:
  1. Nhận X (DataFrame features) + y (RSSI array)
  2. Scale features
  3. Train từng model
  4. Đánh giá qua cross-validation
  5. Trả về ModelBundle sẵn sàng để lưu vào model_store

Gaussian Process chỉ train trên tối đa GP_MAX_SAMPLES mẫu
(độ phức tạp O(n³) — với 500+ điểm sẽ OOM).
"""

from __future__ import annotations

import logging
import uuid
import warnings
from typing import Literal

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import (
    ConstantKernel as C, Matern, WhiteKernel,
)
from sklearn.metrics import (
    mean_absolute_error, mean_squared_error, r2_score,
)
from sklearn.model_selection import KFold, cross_val_score, train_test_split
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRegressor

from ml.features import FEATURE_NAMES
from ml.model_store import ModelBundle

logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore", category=UserWarning)

AlgorithmType = Literal["xgboost", "random_forest", "gaussian_process"]

# GP giới hạn mẫu để tránh O(n³) OOM
GP_MAX_SAMPLES = 300


# ── Model factory ──────────────────────────────────────────────────────────────

def _build_xgboost(**kwargs) -> XGBRegressor:
    defaults = dict(
        n_estimators      = 500,
        learning_rate     = 0.05,
        max_depth         = 6,
        subsample         = 0.8,
        colsample_bytree  = 0.8,
        reg_alpha         = 0.1,
        reg_lambda        = 1.0,
        min_child_weight  = 3,
        gamma             = 0.1,
        random_state      = 42,
        n_jobs            = -1,
        verbosity         = 0,
        tree_method       = "hist",   # nhanh hơn với dữ liệu nhỏ
    )
    defaults.update(kwargs)
    return XGBRegressor(**defaults)


def _build_random_forest(**kwargs) -> RandomForestRegressor:
    defaults = dict(
        n_estimators      = 300,
        max_depth         = None,
        min_samples_split = 5,
        min_samples_leaf  = 2,
        max_features      = "sqrt",
        bootstrap         = True,
        oob_score         = True,
        random_state      = 42,
        n_jobs            = -1,
    )
    defaults.update(kwargs)
    return RandomForestRegressor(**defaults)


def _build_gaussian_process(**kwargs) -> GaussianProcessRegressor:
    kernel = (
        C(1.0, (1e-3, 1e3))
        * Matern(length_scale=1.0, length_scale_bounds=(1e-2, 1e2), nu=2.5)
        + WhiteKernel(noise_level=1.0, noise_level_bounds=(1e-5, 1e2))
    )
    defaults = dict(
        kernel               = kernel,
        alpha                = 1e-6,
        n_restarts_optimizer = 3,
        normalize_y          = True,
        random_state         = 42,
    )
    defaults.update(kwargs)
    return GaussianProcessRegressor(**defaults)


MODEL_BUILDERS = {
    "xgboost"          : _build_xgboost,
    "random_forest"    : _build_random_forest,
    "gaussian_process" : _build_gaussian_process,
}


# ── Metrics ────────────────────────────────────────────────────────────────────

def _compute_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    mae  = float(mean_absolute_error(y_true, y_pred))
    r2   = float(r2_score(y_true, y_pred))
    return {"rmse_db": round(rmse, 4), "mae_db": round(mae, 4), "r2_score": round(r2, 4)}


# ── Feature importance ─────────────────────────────────────────────────────────

def _get_feature_importance(model, feature_names: list[str]) -> dict[str, float]:
    """Trả về dict {feature: importance} nếu model hỗ trợ."""
    if hasattr(model, "feature_importances_"):
        imp = model.feature_importances_
        total = imp.sum() or 1.0
        return {f: round(float(v / total), 6)
                for f, v in zip(feature_names, imp)}
    return {}


# ── Main train function ────────────────────────────────────────────────────────

def train(
    X: pd.DataFrame,
    y: np.ndarray,
    algorithm: AlgorithmType = "xgboost",
    hyperparameters: dict | None = None,
    n_cv_splits: int = 5,
) -> ModelBundle:
    """
    Train một model và trả về ModelBundle.

    Parameters
    ----------
    X              : DataFrame với cột = FEATURE_NAMES
    y              : RSSI array (float)
    algorithm      : "xgboost" | "random_forest" | "gaussian_process"
    hyperparameters: override mặc định cho model
    n_cv_splits    : số fold cross-validation (0 = bỏ qua CV)
    """
    if algorithm not in MODEL_BUILDERS:
        raise ValueError(f"algorithm phải là một trong: {list(MODEL_BUILDERS)}")

    hp = hyperparameters or {}
    X_arr = X[FEATURE_NAMES].fillna(0.0).values.astype(float)

    # ── Train/test split ──────────────────────────────────────
    # Skip split cho GP với mẫu nhỏ (<50): test set quá ít → metric noisy,
    # dùng CV để đánh giá thay thế.
    use_split = not (algorithm == "gaussian_process" and len(y) < 50)

    if use_split:
        X_train_arr, X_test_arr, y_train, y_test = train_test_split(
            X_arr, y, test_size=0.2, random_state=42,
        )
    else:
        X_train_arr, y_train = X_arr, y
        X_test_arr,  y_test  = None, None
        logger.info("[Trainer] %s n=%d <50 → skip split, dùng CV",
                    algorithm, len(y))

    # ── Scale (fit on train ONLY → tránh data leak) ───────────
    scaler = StandardScaler()
    X_train_sc = scaler.fit_transform(X_train_arr)
    X_test_sc  = scaler.transform(X_test_arr) if X_test_arr is not None else None

    # ── GP: giới hạn mẫu train (sau khi split) ────────────────
    X_fit, y_fit = X_train_sc, y_train
    if algorithm == "gaussian_process" and len(X_fit) > GP_MAX_SAMPLES:
        rng = np.random.default_rng(42)
        idx = rng.choice(len(X_fit), GP_MAX_SAMPLES, replace=False)
        X_fit, y_fit = X_fit[idx], y_fit[idx]
        logger.info("[Trainer] GP: dùng %d/%d mẫu", GP_MAX_SAMPLES, len(X_train_sc))

    # ── Build & fit ───────────────────────────────────────────
    model = MODEL_BUILDERS[algorithm](**hp)
    model.fit(X_fit, y_fit)
    logger.info("[Trainer] %s trained on %d samples", algorithm, len(X_fit))

    # ── Quantile models (XGBoost only) — uncertainty = (q90-q10)/2 ──
    # Reuse cùng training data + hyperparameters với median model,
    # chỉ override objective + quantile_alpha.
    quantile_models = {}
    if algorithm == "xgboost":
        for q_name, alpha in (("q10", 0.1), ("q90", 0.9)):
            q_hp = dict(hp)
            q_hp["objective"]      = "reg:quantileerror"
            q_hp["quantile_alpha"] = alpha
            q_model = _build_xgboost(**q_hp)
            q_model.fit(X_fit, y_fit)
            quantile_models[q_name] = q_model
        logger.info("[Trainer] XGBoost quantile models q10/q90 trained")

    # ── Metrics: PRIMARY = test (đánh giá trung thực, không overfit) ─
    train_metrics = _compute_metrics(y_train, model.predict(X_train_sc))

    if X_test_sc is not None:
        metrics = _compute_metrics(y_test, model.predict(X_test_sc))
        metrics["rmse_train"] = train_metrics["rmse_db"]
        metrics["r2_train"]   = train_metrics["r2_score"]
        metrics["n_train"]    = len(y_train)
        metrics["n_test"]     = len(y_test)
    else:
        # GP nhỏ: không có test set, chỉ có train metrics + CV
        metrics = train_metrics
        metrics["n_train"] = len(y_train)

    # ── Cross-validation (chạy trên train set, không động test) ───
    if n_cv_splits >= 2 and algorithm != "gaussian_process":
        cv     = KFold(n_splits=n_cv_splits, shuffle=True, random_state=42)
        scores = cross_val_score(model, X_train_sc, y_train,
                                 cv=cv, scoring="r2", n_jobs=-1)
        metrics["cv_r2_mean"] = round(float(scores.mean()), 4)
        metrics["cv_r2_std"]  = round(float(scores.std()),  4)
        logger.info("[Trainer] CV R²: %.4f ± %.4f",
                    metrics["cv_r2_mean"], metrics["cv_r2_std"])

    feature_imp = _get_feature_importance(model, FEATURE_NAMES)

    model_id = str(uuid.uuid4())
    bundle = ModelBundle(
        model_id         = model_id,
        algorithm        = algorithm,
        model            = model,
        scaler           = scaler,
        feature_names    = FEATURE_NAMES,
        metrics          = metrics,
        hyperparameters  = hp,
        feature_importance = feature_imp,
        quantile_models  = quantile_models,
    )

    logger.info(
        "[Trainer] Done: id=%s rmse=%.2f mae=%.2f r2=%.4f",
        model_id, metrics["rmse_db"], metrics["mae_db"], metrics["r2_score"],
    )
    return bundle