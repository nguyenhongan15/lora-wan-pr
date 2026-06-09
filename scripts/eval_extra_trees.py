"""Évaluation du modèle Extra Trees vs XGBoost — génère un rapport comparable à sixth-train/.

Usage:
    python scripts/eval_extra_trees.py
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.impute import SimpleImputer
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

log = logging.getLogger("eval_extra_trees")

REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
DATA_PATH = (
    REPO_ROOT / "services/ml-service/reference_wireless/data/processed/devices_history_full.csv"
)
REPORT_DIR = REPO_ROOT / "reports" / "seven-train"


# ---------------------------------------------------------------------------
# Feature definitions (reference_wireless pipeline)
# ---------------------------------------------------------------------------
NUMERIC_FEATURES = [
    "frequency",
    "spreading_factor",
    "log_distance",
    "log_distance_3d",
    "delta_lat",
    "delta_lon",
    "angle",
    "gw_elevation",
    "delta_elevation",
    "elevation_angle",
    "slope",
    "roughness",
    "terrain_mean",
    "terrain_std",
    "terrain_min",
    "terrain_max",
    "fresnel_obstruction_ratio",
    "min_fresnel_clearance",
    "mean_fresnel_clearance",
    "residential_ratio",
]

CATEGORICAL_FEATURES = ["gateway"]
TARGET = "rssi"

ALL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES

# Extra Trees hyperparameters (best found)
ET_PARAMS = {
    "n_estimators": 1500,
    "max_depth": 20,
    "min_samples_split": 5,
    "min_samples_leaf": 2,
    "max_features": None,
    "random_state": 42,
    "n_jobs": -1,
}

# Train/test split
TEST_SIZE = 0.2
RANDOM_STATE = 42

# Distance bins (same as train_residual_model.py)
_DIST_BINS = [(0.0, 2.0), (2.0, 5.0), (5.0, 10.0), (10.0, 50.0)]
_DIST_LABELS = ["<2km", "2-5km", "5-10km", "10-50km"]


# ---------------------------------------------------------------------------
# Building the pipeline
# ---------------------------------------------------------------------------


def build_et_pipeline() -> Pipeline:
    numeric_transformer = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
        ]
    )
    categorical_transformer = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("encoder", OneHotEncoder(handle_unknown="ignore")),
        ]
    )
    preprocessor = ColumnTransformer(
        transformers=[
            ("num", numeric_transformer, NUMERIC_FEATURES),
            ("cat", categorical_transformer, CATEGORICAL_FEATURES),
        ]
    )
    model = ExtraTreesRegressor(**ET_PARAMS)
    return Pipeline(steps=[("preprocessor", preprocessor), ("model", model)])


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def stats(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    err = y_true - y_pred
    return {
        "n": int(err.size),
        "rmse_db": float(np.sqrt(np.mean(err**2))),
        "mae_db": float(np.mean(np.abs(err))),
        "bias_db": float(np.mean(err)),
        "r2": float(1 - np.sum(err**2) / np.sum((y_true - y_true.mean()) ** 2)),
    }


# ---------------------------------------------------------------------------
# Plots (mirroring train_residual_model.py's _plot_eval)
# ---------------------------------------------------------------------------


def plot_evaluation(
    pipeline,
    feature_names: list[str],
    df_train: pd.DataFrame,
    df_test: pd.DataFrame,
    X_train: pd.DataFrame,
    X_test: pd.DataFrame,
    y_train: np.ndarray,
    y_test: np.ndarray,
    train_pred: np.ndarray,
    test_pred: np.ndarray,
    plot_dir: Path,
    model_label: str = "Extra Trees",
) -> None:
    """Generate 5 plots matching the naming convention of sixth-train report.

    Plots:
      01_learning_curve.png  — RMSE vs n_estimators (evaluates subsets of trees)
      02_pred_vs_meas.png    — Scatter predicted vs measured (test)
      03_error_vs_distance.png — Error vs distance (test)
      04_per_bin.png          — RMSE + bias per distance bin (test)
      05_feature_importance.png — Feature importance bar chart
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plot_dir.mkdir(parents=True, exist_ok=True)

    err = y_test - test_pred
    dist = df_test.get("distance_km", df_test.get("distance", np.zeros(len(y_test))))
    # Convert distance to km if in meters
    if dist.max() > 1000:
        dist = dist / 1000

    # ── Plot 1: Learning curve — RMSE vs n_estimators ──
    # Evaluate the pipeline with subsets of trees to show RMSE convergence
    et_model = pipeline.named_steps["model"]
    n_estimators_vals = sorted({1, 2, 5, 10, 20, 50, 100, 200, 500, 750, 1000, 1500})
    # Keep only values <= the actual number of trees
    n_estimators_vals = [n for n in n_estimators_vals if n <= et_model.n_estimators]

    train_rmses, val_rmses = [], []
    for n in n_estimators_vals:
        # Create a model with the same params but fewer trees
        from sklearn.ensemble import ExtraTreesRegressor

        sub_model = ExtraTreesRegressor(
            n_estimators=n,
            max_depth=et_model.max_depth,
            min_samples_split=et_model.min_samples_split,
            min_samples_leaf=et_model.min_samples_leaf,
            max_features=et_model.max_features,
            random_state=42,
            n_jobs=-1,
        )
        # Build a pipeline with the existing preprocessor + sub-model
        sub_pipeline = Pipeline(
            [
                ("preprocessor", pipeline.named_steps["preprocessor"]),
                ("model", sub_model),
            ]
        )
        sub_pipeline.fit(X_train, y_train)
        train_pred_sub = sub_pipeline.predict(X_train)
        test_pred_sub = sub_pipeline.predict(X_test)
        train_rmses.append(float(np.sqrt(np.mean((y_train - train_pred_sub) ** 2))))
        val_rmses.append(float(np.sqrt(np.mean((y_test - test_pred_sub) ** 2))))

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(n_estimators_vals, train_rmses, "o-", label="train RMSE", markersize=4)
    ax.plot(n_estimators_vals, val_rmses, "s-", label="test RMSE", markersize=4)
    ax.set_xlabel("Number of trees")
    ax.set_ylabel("RMSE (dB)")
    ax.set_title(f"{model_label} — Learning curve")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(plot_dir / "01_learning_curve.png", dpi=120)
    plt.close(fig)
    log.info(
        "Learning curve: %d evaluations [%d → %d trees]",
        len(n_estimators_vals),
        n_estimators_vals[0],
        n_estimators_vals[-1],
    )

    # ── Plot 2: Predicted vs measured (test) ──
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.scatter(y_test, test_pred, alpha=0.4, s=10)
    lim = float(max(np.abs(y_test).max(), np.abs(test_pred).max(), 1.0))
    ax.plot([-lim, lim], [-lim, lim], "k--", alpha=0.5, label="y=x")
    ax.set_xlabel("Measured RSSI (dBm)")
    ax.set_ylabel("Predicted RSSI (dBm)")
    ax.set_title(f"{model_label} — Predicted vs measured (test, n={len(y_test)})")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(plot_dir / "02_pred_vs_meas.png", dpi=120)
    plt.close(fig)

    # ── Plot 3: Error vs distance (test) ──
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.scatter(dist, err, alpha=0.4, s=10)
    ax.axhline(0, color="red", linestyle="--", alpha=0.6)
    ax.set_xlabel("Distance (km)")
    ax.set_ylabel("Error = measured - predicted (dB)")
    ax.set_title(f"{model_label} — Residual error vs distance (test)")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(plot_dir / "03_error_vs_distance.png", dpi=120)
    plt.close(fig)

    # ── Plot 4: Per distance-bin RMSE + bias (test) ──
    rmse_per, bias_per, n_per = [], [], []
    for lo, hi in _DIST_BINS:
        mask = (dist >= lo) & (dist < hi)
        if mask.sum() == 0:
            rmse_per.append(0.0)
            bias_per.append(0.0)
            n_per.append(0)
            continue
        e = err[mask]
        rmse_per.append(float(np.sqrt(np.mean(e**2))))
        bias_per.append(float(np.mean(e)))
        n_per.append(int(mask.sum()))

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    x = np.arange(len(_DIST_LABELS))
    ax1.bar(x, rmse_per)
    for i, n in enumerate(n_per):
        ax1.text(i, rmse_per[i] + 0.3, f"n={n}", ha="center", fontsize=9)
    ax1.set_xticks(x)
    ax1.set_xticklabels(_DIST_LABELS)
    ax1.set_ylabel("RMSE (dB)")
    ax1.set_title(f"{model_label} — RMSE per distance bin (test)")
    ax1.grid(True, alpha=0.3, axis="y")

    bar_colors = ["green" if abs(b) < 5 else ("orange" if abs(b) < 10 else "red") for b in bias_per]
    ax2.bar(x, bias_per, color=bar_colors)
    ax2.axhline(0, color="black", linewidth=0.8)
    for i, b in enumerate(bias_per):
        offset = 0.5 if b >= 0 else -1.0
        ax2.text(i, b + offset, f"{b:+.2f}", ha="center", fontsize=9)
    ax2.set_xticks(x)
    ax2.set_xticklabels(_DIST_LABELS)
    ax2.set_ylabel("Bias = mean(measured - predicted) (dB)")
    ax2.set_title(f"{model_label} — Bias per distance bin (test)")
    ax2.grid(True, alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig(plot_dir / "04_per_bin.png", dpi=120)
    plt.close(fig)

    # ── Plot 5: Feature importance ──
    if hasattr(et_model, "feature_importances_"):
        importances = et_model.feature_importances_
        if len(importances) == len(feature_names):
            order = np.argsort(importances)[::-1]
            fig, ax = plt.subplots(figsize=(8, 6))
            y_pos = np.arange(len(feature_names))
            ax.barh(y_pos, importances[order])
            ax.set_yticks(y_pos)
            ax.set_yticklabels([feature_names[i] for i in order])
            ax.invert_yaxis()
            ax.set_xlabel("Feature importance (normalized)")
            ax.set_title(f"{model_label} — Feature importance")
            ax.grid(True, alpha=0.3, axis="x")
            fig.tight_layout()
            fig.savefig(plot_dir / "05_feature_importance.png", dpi=120)
            plt.close(fig)

    train_rmse = float(np.sqrt(np.mean((y_train - train_pred) ** 2)))
    test_rmse = float(np.sqrt(np.mean((y_test - test_pred) ** 2)))
    log.info(
        "%s — Saved 5 plots → %s | train RMSE=%.2f vs test RMSE=%.2f (gap=%.2f dB)",
        model_label,
        plot_dir,
        train_rmse,
        test_rmse,
        test_rmse - train_rmse,
    )


# ---------------------------------------------------------------------------
# XGBoost training (fair comparison — train on same data/target)
# ---------------------------------------------------------------------------


def train_xgb(X_train: pd.DataFrame, y_train: np.ndarray) -> object | None:
    """Train an XGBoost model on the SAME features as the ET pipeline for
    a fair comparison.

    The XGBoost from 'reports/sixth-train/' was trained on *residuals* (not RSSI
    directly) and on 8 basic features. Comparing it directly is meaningless.
    Instead, we train a fresh XGBoost on the same 21 features + same target (RSSI)
    as the Extra Trees model for an apples-to-apples comparison.

    The 'gateway' column is string-encoded, so we one-hot encode it and drop
    the original column, matching what the ET pipeline does internally.
    """
    try:
        import xgboost as xgb
    except ImportError:
        log.warning("xgboost package not installed — install with: pip install xgboost")
        return None

    log.info("Training XGBoost on same features/target for fair comparison...")

    # One-hot encode the 'gateway' categorical column
    X_train_enc = X_train.copy()
    if "gateway" in X_train_enc.columns:
        X_train_enc = pd.get_dummies(X_train_enc, columns=["gateway"], prefix="gw")

    log.info("XGBoost input shape: %s", X_train_enc.shape)

    model = xgb.XGBRegressor(
        tree_method="hist",
        n_estimators=500,
        learning_rate=0.05,
        max_depth=6,
        min_child_weight=5,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_alpha=1.0,
        reg_lambda=2.0,
        n_jobs=-1,
        random_state=42,
        verbosity=0,
    )
    model.fit(X_train_enc, y_train)
    return model, X_train_enc.columns.tolist()  # return columns for test transform


# ---------------------------------------------------------------------------
# Main evaluation
# ---------------------------------------------------------------------------


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    log.info("=" * 60)
    log.info("  Extra Trees Evaluation")
    log.info("=" * 60)

    # 1. Load data
    log.info("Loading data from %s", DATA_PATH)
    df = pd.read_csv(DATA_PATH)
    log.info("Dataset shape: %s", df.shape)

    # Compute distance_km for distance-bin plots
    if "distance_km" not in df.columns and "distance" in df.columns:
        df["distance_km"] = df["distance"] / 1000.0

    # 2. Prepare features and target
    feature_cols = NUMERIC_FEATURES + CATEGORICAL_FEATURES
    X = df[feature_cols].copy()
    y = df[TARGET].to_numpy()

    log.info("Features: %d rows x %d cols", X.shape[0], X.shape[1])
    log.info("Target stats: mean=%.2f std=%.2f", y.mean(), y.std(ddof=1))

    # 3. Train/test split (spatial stratified by gateway)
    log.info("Splitting data: test_size=%.2f, random_state=%d", TEST_SIZE, RANDOM_STATE)

    # Use Stratified split by gateway to ensure test set covers all gateways
    from sklearn.model_selection import StratifiedShuffleSplit

    gw_labels = df["gateway"].astype("category").cat.codes.to_numpy()
    sss = StratifiedShuffleSplit(n_splits=1, test_size=TEST_SIZE, random_state=RANDOM_STATE)
    train_idx, test_idx = next(sss.split(X, gw_labels))

    X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
    y_train, y_test = y[train_idx], y[test_idx]
    df_test = df.iloc[test_idx]

    log.info("Train: %d, Test: %d (gateway-stratified)", len(X_train), len(X_test))

    # 4. Further split train into train/val for early stopping visualization
    # (Even though ET doesn't use early stopping, we still use a val set for error analysis)
    X_train_inner, X_val, _y_train_inner, _y_val = train_test_split(
        X_train, y_train, test_size=0.1, random_state=RANDOM_STATE
    )
    log.info("Inner split: train=%d, val=%d", len(X_train_inner), len(X_val))

    # 5. Build and train Extra Trees pipeline
    log.info("Building Extra Trees pipeline...")
    log.info("Params: %s", ET_PARAMS)
    et_pipeline = build_et_pipeline()

    log.info("Training Extra Trees...")
    et_pipeline.fit(X_train, y_train)

    # 6. Predict
    train_pred = et_pipeline.predict(X_train)
    test_pred = et_pipeline.predict(X_test)

    # 7. Metrics
    train_stats = stats(y_train, train_pred)
    test_stats = stats(y_test, test_pred)
    null_test = stats(y_test, np.zeros_like(y_test))

    log.info("─" * 50)
    log.info("  EXTRA TREES RESULTS")
    log.info("─" * 50)
    log.info(
        "  Train fit:     RMSE=%.2f  MAE=%.2f  bias=%.2f  R²=%.4f  n=%d",
        train_stats["rmse_db"],
        train_stats["mae_db"],
        train_stats["bias_db"],
        train_stats["r2"],
        train_stats["n"],
    )
    log.info(
        "  Hold-out test: RMSE=%.2f  MAE=%.2f  bias=%.2f  R²=%.4f  n=%d",
        test_stats["rmse_db"],
        test_stats["mae_db"],
        test_stats["bias_db"],
        test_stats["r2"],
        test_stats["n"],
    )
    log.info(
        "  Null baseline:  test RMSE=%.2f  MAE=%.2f", null_test["rmse_db"], null_test["mae_db"]
    )
    log.info("─" * 50)

    # 8. Train XGBoost on same data for fair comparison
    # (The old sixth-train XGBoost predicted residuals on 8 features — incomparable)
    log.info("\nTraining XGBoost on same features/target for fair comparison...")
    xgb_result = train_xgb(X_train, y_train)
    if xgb_result is not None:
        xgb_model, xgb_columns = xgb_result

        # One-hot encode test data using same columns
        X_test_enc = X_test.copy()
        if "gateway" in X_test_enc.columns:
            X_test_enc = pd.get_dummies(X_test_enc, columns=["gateway"], prefix="gw")
        # Ensure test has same columns as train (add missing, drop extra)
        for col in xgb_columns:
            if col not in X_test_enc.columns:
                X_test_enc[col] = 0
        X_test_enc = X_test_enc[xgb_columns]

        X_train_enc = pd.get_dummies(X_train.copy(), columns=["gateway"], prefix="gw")
        X_train_enc = X_train_enc[xgb_columns]

        xgb_train_pred = xgb_model.predict(X_train_enc)
        xgb_test_pred = xgb_model.predict(X_test_enc)
        xgb_train_stats = stats(y_train, xgb_train_pred)
        xgb_test_stats = stats(y_test, xgb_test_pred)
        log.info("─" * 50)
        log.info("  XGBOOST (same 21 features, same RSSI target) — TEST")
        log.info("─" * 50)
        log.info(
            "  Train: RMSE=%.2f  MAE=%.2f  bias=%.2f  R²=%.4f  n=%d",
            xgb_train_stats["rmse_db"],
            xgb_train_stats["mae_db"],
            xgb_train_stats["bias_db"],
            xgb_train_stats["r2"],
            xgb_train_stats["n"],
        )
        log.info(
            "  Test:  RMSE=%.2f  MAE=%.2f  bias=%.2f  R²=%.4f  n=%d",
            xgb_test_stats["rmse_db"],
            xgb_test_stats["mae_db"],
            xgb_test_stats["bias_db"],
            xgb_test_stats["r2"],
            xgb_test_stats["n"],
        )
        log.info(
            "  ET vs XGBoost (test): RMSE %.2f vs %.2f (diff=%.2f dB)",
            test_stats["rmse_db"],
            xgb_test_stats["rmse_db"],
            xgb_test_stats["rmse_db"] - test_stats["rmse_db"],
        )
    else:
        xgb_test_pred = None
        xgb_train_stats = None
        xgb_test_stats = None
        log.warning("XGBoost not available — skipping comparison")

    # 9. Save model
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    model_path = REPORT_DIR / "extra_trees_model.joblib"
    joblib.dump(et_pipeline, model_path, compress=3)
    log.info("Model saved -> %s (%.1f KB)", model_path, model_path.stat().st_size / 1024.0)

    # 10. Save metrics summary
    summary = {
        "model": "ExtraTreesRegressor",
        "params": ET_PARAMS,
        "n_features": len(NUMERIC_FEATURES) + len(CATEGORICAL_FEATURES),
        "n_train": len(X_train),
        "n_test": len(X_test),
        "train": train_stats,
        "test": test_stats,
        "null_baseline": null_test,
        "xgboost_comparison": None,
    }
    if xgb_test_pred is not None:
        summary["xgboost_comparison"] = {
            "model": "XGBoost (same 21 features, RSSI target)",
            "train": xgb_train_stats,
            "test": xgb_test_stats,
        }

    summary_path = REPORT_DIR / "summary.json"
    with summary_path.open("w") as f:
        json.dump(summary, f, indent=2)
    log.info("Summary saved -> %s", summary_path)

    # 11. Generate plots
    # Get feature names from the pipeline (after one-hot encoding)
    try:
        cat_encoder = (
            et_pipeline.named_steps["preprocessor"]
            .named_transformers_["cat"]
            .named_steps["encoder"]
        )
        cat_names = list(cat_encoder.get_feature_names_out(CATEGORICAL_FEATURES))
    except Exception:
        cat_names = CATEGORICAL_FEATURES[:]
    feature_names = NUMERIC_FEATURES + cat_names

    plot_evaluation(
        pipeline=et_pipeline,
        feature_names=feature_names,
        df_train=df.iloc[train_idx],
        df_test=df_test,
        X_train=X_train,
        X_test=X_test,
        y_train=y_train,
        y_test=y_test,
        train_pred=train_pred,
        test_pred=test_pred,
        plot_dir=REPORT_DIR,
        model_label="Extra Trees",
    )

    # 12. Combined comparison plot (ET vs XGBoost)
    if xgb_test_pred is not None:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(1, 2, figsize=(14, 6))

        dist_km = df_test.get("distance_km", df_test.get("distance", 0)) / 1000

        # ET error vs distance
        axes[0].scatter(
            dist_km, y_test - test_pred, alpha=0.3, s=8, c="steelblue", label="Extra Trees"
        )
        axes[0].scatter(dist_km, y_test - xgb_test_pred, alpha=0.3, s=8, c="coral", label="XGBoost")
        axes[0].axhline(0, color="black", linestyle="--", linewidth=0.8)
        axes[0].set_xlabel("Distance (km)")
        axes[0].set_ylabel("Error = measured - predicted (dB)")
        axes[0].set_title(
            "Extra Trees vs XGBoost — Error vs Distance\n(same 21 features, same RSSI target)"
        )
        axes[0].legend()
        axes[0].grid(True, alpha=0.3)

        # Per-bin comparison
        et_err = y_test - test_pred
        xgb_err = y_test - xgb_test_pred

        labels = _DIST_LABELS
        x = np.arange(len(labels))
        width = 0.35

        et_rmse_per, xgb_rmse_per = [], []
        for lo, hi in _DIST_BINS:
            mask = (dist_km >= lo) & (dist_km < hi)
            if mask.sum() == 0:
                et_rmse_per.append(0.0)
                xgb_rmse_per.append(0.0)
            else:
                et_rmse_per.append(float(np.sqrt(np.mean(et_err[mask] ** 2))))
                xgb_rmse_per.append(float(np.sqrt(np.mean(xgb_err[mask] ** 2))))

        axes[1].bar(x - width / 2, et_rmse_per, width, label="Extra Trees", color="steelblue")
        axes[1].bar(x + width / 2, xgb_rmse_per, width, label="XGBoost", color="coral")
        axes[1].set_xticks(x)
        axes[1].set_xticklabels(labels)
        axes[1].set_ylabel("RMSE (dB)")
        axes[1].set_title("RMSE per distance bin — Extra Trees vs XGBoost")
        axes[1].legend()
        axes[1].grid(True, alpha=0.3, axis="y")

        fig.tight_layout()
        fig.savefig(REPORT_DIR / "06_comparison_et_vs_xgb.png", dpi=120)
        plt.close(fig)
        log.info("Comparison plot saved -> %s/06_comparison_et_vs_xgb.png", REPORT_DIR)

    # 13. Save a text summary
    summary_txt = REPORT_DIR / "summary.txt"
    with summary_txt.open("w", encoding="utf-8") as f:
        f.write("Extra Trees evaluation report\n")
        f.write("=" * 60 + "\n\n")
        f.write(
            f"Model: ExtraTreesRegressor (n_estimators={ET_PARAMS['n_estimators']}, max_depth={ET_PARAMS['max_depth']})\n"
        )
        f.write(
            f"Features: {len(NUMERIC_FEATURES)} numeric + {len(CATEGORICAL_FEATURES)} categorical = {len(ALL_FEATURES)} total\n\n"
        )
        f.write("Metrics\n")
        f.write(f"  Train RMSE : {train_stats['rmse_db']:.2f} dBm\n")
        f.write(f"  Train MAE  : {train_stats['mae_db']:.2f} dBm\n")
        f.write(f"  Train R2   : {train_stats['r2']:.4f}\n")
        f.write(f"  Test  RMSE : {test_stats['rmse_db']:.2f} dBm\n")
        f.write(f"  Test  MAE  : {test_stats['mae_db']:.2f} dBm\n")
        f.write(f"  Test  R2   : {test_stats['r2']:.4f}\n")
        f.write(f"  Test  bias : {test_stats['bias_db']:+.2f} dB\n")
        f.write(f"  Train/Test gap : {test_stats['rmse_db'] - train_stats['rmse_db']:.2f} dB\n\n")
        f.write("Null baseline (predict mean)\n")
        f.write(f"  Test RMSE : {null_test['rmse_db']:.2f} dBm\n")
        f.write(f"  Test MAE  : {null_test['mae_db']:.2f} dBm\n\n")
        if xgb_test_pred is not None:
            xgb_s = xgb_test_stats
            f.write("XGBoost comparison (same 21 features, same RSSI target)\n")
            f.write("=" * 40 + "\n")
            f.write(f"  Train RMSE : {xgb_train_stats['rmse_db']:.2f} dBm\n")
            f.write(f"  Train MAE  : {xgb_train_stats['mae_db']:.2f} dBm\n")
            f.write(f"  Test  RMSE : {xgb_s['rmse_db']:.2f} dBm\n")
            f.write(f"  Test  MAE  : {xgb_s['mae_db']:.2f} dBm\n")
            f.write(f"  Test  R2   : {xgb_s['r2']:.4f}\n")
            f.write(f"  ET  Test RMSE: {test_stats['rmse_db']:.2f} dBm\n")
            f.write(f"  XGB Test RMSE: {xgb_s['rmse_db']:.2f} dBm\n")
            diff = xgb_s["rmse_db"] - test_stats["rmse_db"]
            f.write(f"  Difference (ET - XGBoost): {diff:+.2f} dB\n")
            if diff < 0:
                f.write(f"  => Extra Trees is {abs(diff):.2f} dB BETTER than XGBoost\n")
            else:
                f.write(f"  => XGBoost is {abs(diff):.2f} dB better than Extra Trees\n")
            f.write("\n  NOTE: This XGBoost was trained from scratch on the SAME 21 features\n")
            f.write("  and SAME target (RSSI) as the Extra Trees model for a fair\n")
            f.write("  comparison. The old sixth-train XGBoost predicted residuals on\n")
            f.write("  8 basic features and is NOT directly comparable.\n\n")
        f.write("Plots\n")
        f.write("  01_learning_curve.png        - Learning curve (RMSE vs n_estimators)\n")
        f.write("  02_pred_vs_meas.png          - Predicted vs measured (test)\n")
        f.write("  03_error_vs_distance.png     - Error vs distance (test)\n")
        f.write("  04_per_bin.png               - RMSE/Bias per distance bin (test)\n")
        f.write("  05_feature_importance.png    - Feature importance\n")
        if xgb_test_pred is not None:
            f.write("  06_comparison_et_vs_xgb.png  - Extra Trees vs XGBoost comparison\n")
        f.write(f"\nDataset: {DATA_PATH.name}\n")
        f.write(f"  n_train: {len(X_train)}\n")
        f.write(f"  n_test:  {len(X_test)}\n")
        f.write(f"  split: stratified by gateway, test_size={TEST_SIZE}\n")
    log.info("Text summary saved -> %s", summary_txt)

    log.info("=" * 60)
    log.info("  Evaluation complete! Report saved to: %s", REPORT_DIR)
    log.info("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
