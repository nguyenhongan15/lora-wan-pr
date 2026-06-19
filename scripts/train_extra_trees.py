"""Train Extra Trees model using the reference pipeline and save it.

Usage:
    uv run python scripts/train_extra_trees.py
"""

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = (
    REPO_ROOT / "services/ml-service/reference_wireless/data/processed/devices_history_full.csv"
)
MODEL_DIR = REPO_ROOT / "services/ml-service/data"
MODEL_PATH = MODEL_DIR / "extra_trees_model.joblib"
VAL_METRICS_PATH = MODEL_DIR / "val_metrics.json"

# Feature definitions (matching reference_wireless/src/ml/pipeline.py)
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

ET_PARAMS = {
    "n_estimators": 1500,
    "max_depth": 20,
    "min_samples_split": 5,
    "min_samples_leaf": 2,
    "max_features": None,
    "random_state": 42,
    "n_jobs": -1,
}


def build_pipeline():
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


def _metrics(y_true, y_pred) -> dict:
    residuals = y_true - y_pred
    return {
        "rmse": float(np.sqrt(np.mean(residuals**2))),
        "mae": float(np.mean(np.abs(residuals))),
        "r2": float(1 - np.sum(residuals**2) / np.sum((y_true - y_true.mean()) ** 2)),
        "n": len(y_true),
    }


def main():
    print(f"Loading data from {DATA_PATH}")
    df = pd.read_csv(DATA_PATH)
    print(f"Dataset shape: {df.shape}")

    assert "data_split" in df.columns, (
        "CSV missing 'data_split' column — rebuild via scripts/build_training_csv.py first"
    )

    df_train = df[df["data_split"] == "train"].reset_index(drop=True)
    df_val = df[df["data_split"] == "val"].reset_index(drop=True)
    n_test = int((df["data_split"] == "test").sum())
    print(f"Split sizes: train={len(df_train)}, val={len(df_val)}, test={n_test}")
    assert len(df_train) > 0, "Empty train split — check build_training_csv split rule"

    feature_cols = NUMERIC_FEATURES + CATEGORICAL_FEATURES
    X_train = df_train[feature_cols]
    y_train = df_train[TARGET]

    print(f"Train features shape: {X_train.shape}")
    print(
        f"Train target stats: mean={y_train.mean():.2f}, std={y_train.std():.2f}, "
        f"min={y_train.min():.2f}, max={y_train.max():.2f}"
    )

    terrain_fallback = {col: float(df_train[col].mean()) for col in NUMERIC_FEATURES}

    pipeline = build_pipeline()
    print("Training ExtraTreesRegressor on train split...")
    pipeline.fit(X_train, y_train)

    y_pred_train = pipeline.predict(X_train)
    train_metrics = _metrics(y_train.to_numpy(), y_pred_train)
    rmse, mae, r2 = train_metrics["rmse"], train_metrics["mae"], train_metrics["r2"]
    print("\nTraining metrics (in-sample, train split):")
    print(f"  RMSE: {rmse:.2f} dBm")
    print(f"  MAE:  {mae:.2f} dBm")
    print(f"  R²:   {r2:.4f}")

    if len(df_val) > 0:
        X_val = df_val[feature_cols]
        y_val = df_val[TARGET]
        y_pred_val = pipeline.predict(X_val)
        val_metrics = _metrics(y_val.to_numpy(), y_pred_val)
        print("\nValidation metrics (val split, unseen sessions):")
        print(f"  RMSE: {val_metrics['rmse']:.2f} dBm  (n={val_metrics['n']})")
        print(f"  MAE:  {val_metrics['mae']:.2f} dBm")
        print(f"  R²:   {val_metrics['r2']:.4f}")
    else:
        val_metrics = {"rmse": None, "mae": None, "r2": None, "n": 0}
        print("\n(val split empty — skipping val metrics)")

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    # Atomic swap: ghi xuong .new roi rename de ml-service khong serve file ban
    # do (admin retrain co the ghi de trong khi ml-service dang load).
    model_tmp = MODEL_PATH.with_suffix(MODEL_PATH.suffix + ".new")
    joblib.dump(pipeline, model_tmp, compress=3)
    model_tmp.replace(MODEL_PATH)
    print(f"\nModel saved to {MODEL_PATH} ({MODEL_PATH.stat().st_size / 1024:.1f} KB)")

    fallback_path = MODEL_DIR / "terrain_fallback.json"
    with fallback_path.open("w") as f:
        json.dump(terrain_fallback, f, indent=2)
    print(f"Terrain fallback saved to {fallback_path}")

    # Metrics JSON cho Celery task doc lai sau khi train xong.
    metrics_path = MODEL_DIR / "train_metrics.json"
    metrics_payload = {
        "rmse": rmse,
        "mae": mae,
        "r2": r2,
        "rows_trained": len(df_train),
        "feature_count": len(feature_cols),
    }
    with metrics_path.open("w") as f:
        json.dump(metrics_payload, f, indent=2)
    print(f"Metrics saved to {metrics_path}")

    with VAL_METRICS_PATH.open("w") as f:
        json.dump(val_metrics, f, indent=2)
    print(f"Val metrics saved to {VAL_METRICS_PATH}")

    gw_cols = ["gateway", "gw_lat", "gw_lon", "gw_elevation", "frequency"]
    gw_table = df[gw_cols].drop_duplicates(subset="gateway").reset_index(drop=True)
    gw_path = MODEL_DIR / "gateway_table.csv"
    gw_table.to_csv(gw_path, index=False)
    print(f"Gateway table saved to {gw_path} ({len(gw_table)} gateways)")
    print("Done!")


if __name__ == "__main__":
    main()
