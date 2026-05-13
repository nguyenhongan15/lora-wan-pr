"""Training diagnostics — phát hiện overfit + spatial generalization.

Sinh 2 file (must-have):
    03_cv_per_fold.png         — RMSE per spatial fold (đọc từ meta.json)
    04_boosting_curve.png      — train/val RMSE vs iteration (re-train ngắn)

CV bar đọc từ meta — instant. Boosting curve cần re-train ~30s vì booster đã save
không lưu evals_result.
"""

from __future__ import annotations

import logging
from pathlib import Path

import lightgbm as lgb
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from ..data_loader import EvalBundle

log = logging.getLogger(__name__)


def _retrain_with_history(
    x_train: pd.DataFrame,
    y_train: np.ndarray,
    x_val: pd.DataFrame,
    y_val: np.ndarray,
    hyperparams: dict,
    categorical_features: list[str],
    seed: int = 42,
) -> dict:
    """Re-train với best_params + record_evaluation callback → evals_result dict."""
    params = {
        "objective": "huber",
        "alpha": 0.9,
        "metric": "rmse",
        "verbose": -1,
        "seed": seed,
        "deterministic": True,
        "force_col_wise": True,
        **hyperparams,
    }
    cat_arg = categorical_features or "auto"
    dtrain = lgb.Dataset(x_train, label=y_train, categorical_feature=cat_arg)
    dval = lgb.Dataset(x_val, label=y_val, reference=dtrain, categorical_feature=cat_arg)
    evals_result: dict = {}
    lgb.train(
        params,
        dtrain,
        num_boost_round=4000,
        valid_sets=[dtrain, dval],
        valid_names=["train", "val"],
        callbacks=[
            lgb.early_stopping(100, verbose=False),
            lgb.log_evaluation(0),
            lgb.record_evaluation(evals_result),
        ],
    )
    return evals_result


def render(bundle: EvalBundle, out_dir: Path) -> None:
    """Render 2 training diagnostic plots."""
    # 03 — CV per-fold bar (instant — đọc meta)
    cv_rmses = bundle.meta["metrics"]["cv_rmse_per_fold"]
    cv_mean = bundle.meta["metrics"]["cv_rmse_mean"]
    fig, ax = plt.subplots(figsize=(8, 5))
    fold_ids = [f"Fold {i}" for i in range(len(cv_rmses))]
    bars = ax.bar(fold_ids, cv_rmses, color="steelblue", edgecolor="black")
    ax.axhline(
        cv_mean, color="red", linestyle="--", linewidth=1.0, label=f"Mean = {cv_mean:.2f} dB"
    )
    for bar, rmse in zip(bars, cv_rmses, strict=True):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.05,
            f"{rmse:.2f}",
            ha="center",
            va="bottom",
            fontsize=9,
        )
    ax.set_ylabel("RMSE (dB)")
    ax.set_title("Cross-validation RMSE per spatial fold (grid-cell GroupKFold)")
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(True, alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig(out_dir / "03_cv_per_fold.png", dpi=140)
    plt.close(fig)

    # 04 — Boosting curve
    hyperparams = bundle.meta["hyperparams"]
    n = len(bundle.train_val)
    rng = np.random.default_rng(42)
    idx = rng.permutation(n)
    n_val = max(1, int(n * 0.2))
    val_idx, train_idx = idx[:n_val], idx[n_val:]
    feature_columns = list(bundle.feature_columns)
    categorical_features = list(bundle.meta.get("categorical_features", []))
    category_maps: dict[str, list[str]] = bundle.meta.get("category_maps", {})
    x = bundle.train_val[feature_columns].copy()
    for col in categorical_features:
        cats = category_maps.get(col)
        if cats is None:
            continue
        x[col] = pd.Categorical(x[col].astype(str), categories=cats)
    y = bundle.train_val[bundle.target_column].to_numpy()

    log.info("Re-training cho boosting curve (~30s)")
    evals_result = _retrain_with_history(
        x.iloc[train_idx],
        y[train_idx],
        x.iloc[val_idx],
        y[val_idx],
        hyperparams,
        categorical_features,
    )
    train_rmse = evals_result["train"]["rmse"]
    val_rmse = evals_result["val"]["rmse"]
    iterations = list(range(1, len(train_rmse) + 1))

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(iterations, train_rmse, label="Train RMSE", linewidth=1.2)
    ax.plot(iterations, val_rmse, label="Val RMSE", linewidth=1.2)
    best_iter = int(np.argmin(val_rmse)) + 1
    ax.axvline(
        best_iter, color="red", linestyle="--", linewidth=1.0, label=f"Best iter = {best_iter}"
    )
    ax.set_xlabel("Boosting iteration")
    ax.set_ylabel("RMSE (dB)")
    ax.set_title("Boosting curve — train vs val (early-stop @ best val)")
    ax.legend(loc="best", fontsize=9)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_dir / "04_boosting_curve.png", dpi=140)
    plt.close(fig)

    log.info("Training diagnostic plots saved → %s", out_dir)
