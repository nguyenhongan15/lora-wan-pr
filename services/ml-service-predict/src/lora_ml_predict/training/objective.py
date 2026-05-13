"""Optuna TPE objective cho LightGBM Stage 2.

Plan v1 §4.3, Q8 (100 trials).

What:
  build_objective(X, y, folds) → callable(trial) → float (mean CV RMSE).
Hidden:
  LightGBM hyperparameter search space, Huber loss config, early stopping,
  per-fold train/val partition theo spatial fold.
Failure mode:
  KHÔNG raise — trial bad → return float('inf'), Optuna tự skip.

Loss = Huber (robust với outlier RSSI fading). Metric = RMSE (so sánh với
σ̂=23 dB baseline của Stage 1 path-loss fit, memory project_path_loss_fit_baseline).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import lightgbm as lgb
import numpy as np
import optuna
import pandas as pd

log = logging.getLogger(__name__)


def _suggest_params(trial: optuna.Trial, seed: int) -> dict[str, Any]:
    """Search space — moderately tight để 100 trials phủ đủ.

    Huber alpha = 0.9 (chuẩn LightGBM): residual nhỏ → MSE, lớn → MAE.
    Phù hợp với shadow fading log-normal có heavy tail.
    """
    return {
        "objective": "huber",
        "alpha": 0.9,
        "metric": "rmse",
        "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
        "num_leaves": trial.suggest_int("num_leaves", 15, 127),
        "min_data_in_leaf": trial.suggest_int("min_data_in_leaf", 10, 100),
        "feature_fraction": trial.suggest_float("feature_fraction", 0.6, 1.0),
        "bagging_fraction": trial.suggest_float("bagging_fraction", 0.6, 1.0),
        "bagging_freq": trial.suggest_int("bagging_freq", 0, 5),
        "lambda_l1": trial.suggest_float("lambda_l1", 1e-4, 10.0, log=True),
        "lambda_l2": trial.suggest_float("lambda_l2", 1e-4, 10.0, log=True),
        "max_depth": trial.suggest_int("max_depth", 4, 12),
        "verbose": -1,
        "seed": seed,
        "deterministic": True,
        "force_col_wise": True,
    }


def build_objective(
    x: pd.DataFrame,
    y: pd.Series,
    folds: np.ndarray,
    seed: int = 42,
    num_boost_round: int = 2000,
    early_stopping_rounds: int = 50,
) -> Callable[[optuna.Trial], float]:
    """Closure capture data + folds → objective function cho Optuna.

    Cross-validation tay (không dùng lgb.cv) vì fold đã pre-computed theo
    spatial cluster, không phải random K-fold.
    """
    k = int(folds.max()) + 1

    def objective(trial: optuna.Trial) -> float:
        params = _suggest_params(trial, seed)
        fold_rmses: list[float] = []
        for fold_id in range(k):
            val_mask = folds == fold_id
            train_mask = ~val_mask
            x_tr, y_tr = x[train_mask], y[train_mask]
            x_val, y_val = x[val_mask], y[val_mask]

            dtrain = lgb.Dataset(x_tr, label=y_tr)
            dval = lgb.Dataset(x_val, label=y_val, reference=dtrain)
            booster = lgb.train(
                params,
                dtrain,
                num_boost_round=num_boost_round,
                valid_sets=[dval],
                callbacks=[
                    lgb.early_stopping(early_stopping_rounds, verbose=False),
                    lgb.log_evaluation(0),
                ],
            )
            pred = booster.predict(x_val, num_iteration=booster.best_iteration)
            rmse = float(np.sqrt(np.mean((y_val.to_numpy() - pred) ** 2)))
            fold_rmses.append(rmse)
        mean_rmse = float(np.mean(fold_rmses))
        trial.set_user_attr("fold_rmses", fold_rmses)
        return mean_rmse

    return objective


def run_optuna(
    x: pd.DataFrame,
    y: pd.Series,
    folds: np.ndarray,
    n_trials: int,
    seed: int = 42,
) -> optuna.Study:
    """TPE sampler + median pruner. Return study đã chạy xong."""
    sampler = optuna.samplers.TPESampler(seed=seed)
    study = optuna.create_study(direction="minimize", sampler=sampler)
    obj = build_objective(x, y, folds, seed=seed)
    log.info("Starting Optuna TPE search: %d trials", n_trials)
    study.optimize(obj, n_trials=n_trials, show_progress_bar=False)
    log.info(
        "Best trial #%d: mean_rmse=%.3f params=%s",
        study.best_trial.number,
        study.best_value,
        study.best_params,
    )
    return study


def fit_final_model(
    x_train: pd.DataFrame,
    y_train: pd.Series,
    x_val: pd.DataFrame,
    y_val: pd.Series,
    best_params: dict[str, Any],
    seed: int = 42,
    num_boost_round: int = 4000,
    early_stopping_rounds: int = 100,
) -> lgb.Booster:
    """Refit với best params trên full train+val (early stop trên val subset).

    Best params là output của run_optuna().best_params — chỉ có hyperparameter,
    còn objective/alpha/metric phải bổ sung lại.
    """
    params = {
        "objective": "huber",
        "alpha": 0.9,
        "metric": "rmse",
        "verbose": -1,
        "seed": seed,
        "deterministic": True,
        "force_col_wise": True,
        **best_params,
    }
    dtrain = lgb.Dataset(x_train, label=y_train)
    dval = lgb.Dataset(x_val, label=y_val, reference=dtrain)
    return lgb.train(
        params,
        dtrain,
        num_boost_round=num_boost_round,
        valid_sets=[dval],
        callbacks=[
            lgb.early_stopping(early_stopping_rounds, verbose=False),
            lgb.log_evaluation(0),
        ],
    )
