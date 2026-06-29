"""Train Extra Trees model using the reference pipeline and save it.

Usage (chạy từ repo root):
    uv run python services/ml-service/scripts/train_extra_trees.py            # ghi đè artifact active
    uv run python services/ml-service/scripts/train_extra_trees.py --candidate # ghi ra artifact .candidate

`--candidate` dùng bởi Celery retrain (tasks/retrain_ml.py): train ra artifact
tạm + metrics tạm, KHÔNG đụng model đang serve. Promotion gate ở retrain_ml.py
mới quyết định có swap candidate → active hay không (chống đẩy model kém lên
production).
"""

import argparse
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

# File nằm trong services/ml-service/scripts/ → parent.parent = services/ml-service.
# Data + model artifact đều trong ml-service/data nên path tự-chứa trong service.
ML_SERVICE_DIR = Path(__file__).resolve().parent.parent
DATA_PATH = ML_SERVICE_DIR / "data/training/processed/devices_history_full.csv"
MODEL_DIR = ML_SERVICE_DIR / "data"
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
# Cột P.1812 RSSI (build_training_csv.py --with-stage1-rssi). Dùng cho target
# residual (rssi - stage1) và/hoặc physics-as-feature.
STAGE1_COL = "stage1_rssi_dbm"

# Gap train↔val lớn (train R²~0.94 vs spatial-holdout val R²~0.20) trông giống
# overfitting, NHƯNG thực nghiệm cho thấy đây là distribution shift không gian
# (chỉ 13 gateway, 1 vùng) — KHÔNG giảm được bằng regularize. Đã thử trên val:
#   max_features=0.5 + leaf=5  → val RMSE 7.94 (xấu hơn)
#   max_features=None + leaf=4 → val RMSE 7.58 (xấu hơn)
#   max_features=None + leaf=2 → val RMSE 7.38 (TỐT NHẤT — cấu hình dưới)
# Giảm capacity chỉ làm underfit. Đòn bẩy thật cho generalization là DỮ LIỆU
# rộng hơn (thêm gateway/vùng), không phải siêu tham số. Giữ capacity tối đa;
# promotion gate (tasks/retrain_ml.py) + dải ±σ trung thực (prediction_service)
# là lớp bảo vệ khi val còn yếu.
ET_PARAMS = {
    "n_estimators": 1500,
    "max_depth": 20,
    "min_samples_split": 5,
    "min_samples_leaf": 2,
    "max_features": None,
    "random_state": 42,
    "n_jobs": -1,
}


def build_pipeline(numeric_features: list[str]):
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
            ("num", numeric_transformer, numeric_features),
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


def _resolve_output_paths(candidate: bool) -> dict[str, Path]:
    """Trả các đường dẫn output. `--candidate` → biến thể .candidate để không
    đụng artifact/metrics đang active (promotion gate xử lý swap sau)."""
    if candidate:
        return {
            "model": MODEL_DIR / "extra_trees_model.candidate.joblib",
            "train_metrics": MODEL_DIR / "train_metrics.candidate.json",
            "val_metrics": MODEL_DIR / "val_metrics.candidate.json",
            "terrain_fallback": MODEL_DIR / "terrain_fallback.candidate.json",
            "gateway_table": MODEL_DIR / "gateway_table.candidate.csv",
            "model_meta": MODEL_DIR / "model_meta.candidate.json",
        }
    return {
        "model": MODEL_PATH,
        "train_metrics": MODEL_DIR / "train_metrics.json",
        "val_metrics": VAL_METRICS_PATH,
        "terrain_fallback": MODEL_DIR / "terrain_fallback.json",
        "gateway_table": MODEL_DIR / "gateway_table.csv",
        "model_meta": MODEL_DIR / "model_meta.json",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidate",
        action="store_true",
        help="Ghi ra artifact .candidate thay vì ghi đè model active (cho promotion gate).",
    )
    parser.add_argument(
        "--target-kind",
        choices=["absolute", "residual"],
        default="absolute",
        help=(
            "absolute: target=rssi (mặc định, giữ hành vi cũ). "
            "residual: target=rssi-stage1_rssi_dbm → final=stage1+residual (fusion vật lý+ML, "
            "suy biến về vật lý khi xa dữ liệu). Cần CSV có cột stage1_rssi_dbm."
        ),
    )
    parser.add_argument(
        "--with-stage1-feature",
        action="store_true",
        help="Thêm stage1_rssi_dbm vào feature numeric (physics-as-feature). Cần cột stage1.",
    )
    args = parser.parse_args()
    out_paths = _resolve_output_paths(args.candidate)
    residual_mode = args.target_kind == "residual"

    print(f"Loading data from {DATA_PATH}")
    df = pd.read_csv(DATA_PATH)
    print(
        f"Dataset shape: {df.shape}  target_kind={args.target_kind}  "
        f"with_stage1_feature={args.with_stage1_feature}"
    )

    assert "data_split" in df.columns, (
        "CSV missing 'data_split' column — rebuild via scripts/build_training_csv.py first"
    )

    needs_stage1 = residual_mode or args.with_stage1_feature
    if needs_stage1:
        assert STAGE1_COL in df.columns, (
            f"CSV missing '{STAGE1_COL}' — rebuild via "
            "build_training_csv.py --with-stage1-rssi (cho residual/physics-feature)"
        )

    numeric_features = (
        [*NUMERIC_FEATURES, STAGE1_COL] if args.with_stage1_feature else NUMERIC_FEATURES
    )
    feature_cols = numeric_features + CATEGORICAL_FEATURES

    def _prep(split_df: pd.DataFrame):
        """(X, y_target, stage1_series, y_true_abs). Bỏ row stage1 NaN khi cần."""
        sub = split_df
        if needs_stage1:
            sub = sub[sub[STAGE1_COL].notna()].reset_index(drop=True)
        x = sub[feature_cols]
        s1 = sub[STAGE1_COL].to_numpy() if STAGE1_COL in sub.columns else None
        y_abs = sub["rssi"].to_numpy()
        y_tgt = (sub["rssi"] - sub[STAGE1_COL]).to_numpy() if residual_mode else y_abs
        return x, y_tgt, s1, y_abs

    df_train = df[df["data_split"] == "train"].reset_index(drop=True)
    df_val = df[df["data_split"] == "val"].reset_index(drop=True)
    n_test = int((df["data_split"] == "test").sum())

    X_train, y_train, s1_train, abs_train = _prep(df_train)
    print(f"Split sizes: train={len(X_train)}, val={len(df_val)}, test={n_test}")
    assert len(X_train) > 0, "Empty train split — check split rule / stage1 NaN"

    print(f"Train features shape: {X_train.shape}")
    print(
        f"Train target ({args.target_kind}) stats: mean={y_train.mean():.2f}, "
        f"std={y_train.std():.2f}, min={y_train.min():.2f}, max={y_train.max():.2f}"
    )

    terrain_fallback = {col: float(X_train[col].mean()) for col in numeric_features}

    pipeline = build_pipeline(numeric_features)
    print("Training ExtraTreesRegressor on train split...")
    pipeline.fit(X_train, y_train)

    # Metric LUÔN tính ở không gian RSSI tuyệt đối (residual → cộng lại stage1) để
    # so sánh được giữa các target_kind + để holdout/promotion gate đọc nhất quán.
    def _abs_pred(x: pd.DataFrame, stage1) -> np.ndarray:
        pred = pipeline.predict(x)
        return pred + stage1 if residual_mode else pred

    train_metrics = _metrics(abs_train, _abs_pred(X_train, s1_train))
    rmse, mae, r2 = train_metrics["rmse"], train_metrics["mae"], train_metrics["r2"]
    print("\nTraining metrics (in-sample, absolute RSSI):")
    print(f"  RMSE: {rmse:.2f} dBm")
    print(f"  MAE:  {mae:.2f} dBm")
    print(f"  R²:   {r2:.4f}")

    if len(df_val) > 0:
        X_val, _, s1_val, abs_val = _prep(df_val)
        if len(X_val) > 0:
            val_metrics = _metrics(abs_val, _abs_pred(X_val, s1_val))
            print("\nValidation metrics (val split, absolute RSSI):")
            print(f"  RMSE: {val_metrics['rmse']:.2f} dBm  (n={val_metrics['n']})")
            print(f"  MAE:  {val_metrics['mae']:.2f} dBm")
            print(f"  R²:   {val_metrics['r2']:.4f}")
        else:
            val_metrics = {"rmse": None, "mae": None, "r2": None, "n": 0}
            print("\n(val split rỗng sau lọc stage1 NaN — skip val metrics)")
    else:
        val_metrics = {"rmse": None, "mae": None, "r2": None, "n": 0}
        print("\n(val split empty — skipping val metrics)")

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    # Atomic swap: ghi xuong .new roi rename de ml-service khong serve file ban
    # do (admin retrain co the ghi de trong khi ml-service dang load). O che do
    # --candidate, dich la artifact .candidate (khong phai model active).
    model_out = out_paths["model"]
    model_tmp = model_out.with_suffix(model_out.suffix + ".new")
    joblib.dump(pipeline, model_tmp, compress=3)
    model_tmp.replace(model_out)
    print(f"\nModel saved to {model_out} ({model_out.stat().st_size / 1024:.1f} KB)")

    # Sidecar metadata — ml-service đọc để biết cách diễn giải output (residual vs
    # tuyệt đối) + danh sách feature (physics-as-feature thêm cột stage1).
    meta = {
        "target_kind": args.target_kind,
        "numeric_features": numeric_features,
        "categorical_features": CATEGORICAL_FEATURES,
        "all_features": feature_cols,
        "with_stage1_feature": args.with_stage1_feature,
    }
    meta_path = out_paths["model_meta"]
    with meta_path.open("w") as f:
        json.dump(meta, f, indent=2)
    print(f"Model meta saved to {meta_path}")

    fallback_path = out_paths["terrain_fallback"]
    with fallback_path.open("w") as f:
        json.dump(terrain_fallback, f, indent=2)
    print(f"Terrain fallback saved to {fallback_path}")

    # Metrics JSON cho Celery task doc lai sau khi train xong.
    metrics_path = out_paths["train_metrics"]
    metrics_payload = {
        "rmse": rmse,
        "mae": mae,
        "r2": r2,
        "rows_trained": len(X_train),
        "feature_count": len(feature_cols),
        "target_kind": args.target_kind,
    }
    with metrics_path.open("w") as f:
        json.dump(metrics_payload, f, indent=2)
    print(f"Metrics saved to {metrics_path}")

    val_metrics_path = out_paths["val_metrics"]
    with val_metrics_path.open("w") as f:
        json.dump(val_metrics, f, indent=2)
    print(f"Val metrics saved to {val_metrics_path}")

    gw_cols = ["gateway", "gw_lat", "gw_lon", "gw_elevation", "frequency"]
    gw_table = df[gw_cols].drop_duplicates(subset="gateway").reset_index(drop=True)
    gw_path = out_paths["gateway_table"]
    gw_table.to_csv(gw_path, index=False)
    print(f"Gateway table saved to {gw_path} ({len(gw_table)} gateways)")
    print("Done!")


if __name__ == "__main__":
    main()
