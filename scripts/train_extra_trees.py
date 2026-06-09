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


def main():
    print(f"Loading data from {DATA_PATH}")
    df = pd.read_csv(DATA_PATH)
    print(f"Dataset shape: {df.shape}")

    feature_cols = NUMERIC_FEATURES + CATEGORICAL_FEATURES
    X = df[feature_cols]
    y = df[TARGET]

    print(f"Features shape: {X.shape}")
    print(
        f"Target stats: mean={y.mean():.2f}, std={y.std():.2f}, min={y.min():.2f}, max={y.max():.2f}"
    )

    terrain_fallback = {col: float(df[col].mean()) for col in NUMERIC_FEATURES}

    pipeline = build_pipeline()
    print("Training ExtraTreesRegressor...")
    pipeline.fit(X, y)

    y_pred = pipeline.predict(X)
    residuals = y - y_pred
    rmse = float(np.sqrt(np.mean(residuals**2)))
    mae = float(np.mean(np.abs(residuals)))
    r2 = float(1 - np.sum(residuals**2) / np.sum((y - y.mean()) ** 2))
    print("\nTraining metrics:")
    print(f"  RMSE: {rmse:.2f} dBm")
    print(f"  MAE:  {mae:.2f} dBm")
    print(f"  R²:   {r2:.4f}")

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipeline, MODEL_PATH, compress=3)
    print(f"\nModel saved to {MODEL_PATH} ({MODEL_PATH.stat().st_size / 1024:.1f} KB)")

    fallback_path = MODEL_DIR / "terrain_fallback.json"
    with fallback_path.open("w") as f:
        json.dump(terrain_fallback, f, indent=2)
    print(f"Terrain fallback saved to {fallback_path}")

    gw_cols = ["gateway", "gw_lat", "gw_lon", "gw_elevation", "frequency"]
    gw_table = df[gw_cols].drop_duplicates(subset="gateway").reset_index(drop=True)
    gw_path = MODEL_DIR / "gateway_table.csv"
    gw_table.to_csv(gw_path, index=False)
    print(f"Gateway table saved to {gw_path} ({len(gw_table)} gateways)")
    print("Done!")


if __name__ == "__main__":
    main()
