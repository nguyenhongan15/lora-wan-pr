"""Eval Extra Trees tren test split cua training CSV (no DB query, no leakage).

Plan: build_training_csv.py da gan cot `data_split` ∈ {train, val, test} dua
tren H3 res 8 + session 1h + buffer 1-ring. Script nay chi can doc CSV +
filter test split → predict → metrics. Khong cham DB, khong recompute DEM/OSM.

Output: <out_dir>/holdout_eval.json voi schema cu de render_ml_report.py
khong vo:
    {"window": {"start", "end"},   # = min/max timestamp test split (dong)
     "bbox_name": "csv_data_split=test",
     "bbox": null,
     "max_link_km": null,
     "feature_mode": "csv_data_split=test (no DB query, no leakage)",
     "overall": {n, rmse_db, mae_db, bias_db, r2},
     "per_distance_bin": [...],
     "v06_xgboost_baseline_rmse_db": 10.58,
     "delta_vs_v06_db": ...}

Usage:
    python scripts/eval_extra_trees_holdout.py [--out-dir reports/seven-train]
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = REPO_ROOT / "services/ml-service/data/training/processed/devices_history_full.csv"
MODEL_PATH = REPO_ROOT / "services" / "ml-service" / "data" / "extra_trees_model.joblib"
DEFAULT_REPORT_DIR = REPO_ROOT / "reports" / "seven-train"

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
ALL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES
TARGET = "rssi"

V06_XGB_BASELINE_RMSE_DB = 10.58


def compute_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    err = y_true - y_pred
    denom = np.sum((y_true - y_true.mean()) ** 2)
    return {
        "n": len(err),
        "rmse_db": float(np.sqrt(np.mean(err**2))),
        "mae_db": float(np.mean(np.abs(err))),
        "bias_db": float(np.mean(err)),
        "r2": float(1 - np.sum(err**2) / denom) if denom > 0 else float("nan"),
    }


def per_distance_bin_metrics(
    df: pd.DataFrame, y_pred: np.ndarray, y_true: np.ndarray
) -> list[dict]:
    bins = [(0.0, 2.0), (2.0, 5.0), (5.0, 10.0), (10.0, 50.0)]
    out = []
    dist_km = np.power(10.0, df["log_distance"].to_numpy()) / 1000.0
    for lo, hi in bins:
        mask = (dist_km >= lo) & (dist_km < hi)
        if mask.sum() == 0:
            continue
        m = compute_metrics(y_true[mask], y_pred[mask])
        m["bin_km"] = f"{lo}-{hi}"
        out.append(m)
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--csv",
        default=str(DATA_PATH),
        help="Training CSV path (must contain data_split column).",
    )
    p.add_argument(
        "--out-dir",
        default=str(DEFAULT_REPORT_DIR),
        help="Output directory for holdout_eval.json.",
    )
    p.add_argument(
        "--model",
        default=str(MODEL_PATH),
        help="Model artifact to evaluate (default: active model). Promotion gate "
        "passes the .candidate path để eval truoc khi swap.",
    )
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    log = logging.getLogger("eval_holdout")

    csv_path = Path(args.csv)
    out_dir = Path(args.out_dir)
    model_path = Path(args.model)
    if not csv_path.exists():
        raise SystemExit(f"CSV not found at {csv_path}. Run build_training_csv.py first.")
    if not model_path.exists():
        raise SystemExit(f"Model not found at {model_path}. Run train_extra_trees.py first.")

    log.info("Loading CSV from %s", csv_path)
    df = pd.read_csv(csv_path)
    if "data_split" not in df.columns:
        raise SystemExit(
            "CSV missing 'data_split' column — rebuild via build_training_csv.py "
            "(H3+temporal split required)."
        )

    df_test = df[df["data_split"] == "test"].reset_index(drop=True)
    if len(df_test) == 0:
        raise SystemExit("No rows with data_split=='test' — check split rule")
    log.info("Test split rows: %d", len(df_test))

    log.info("Loading model from %s", model_path)
    model = joblib.load(model_path)

    X = df_test[ALL_FEATURES]
    y_true = df_test[TARGET].to_numpy()

    log.info("Predicting %d rows...", len(X))
    y_pred = model.predict(X)
    overall = compute_metrics(y_true, y_pred)
    bins = per_distance_bin_metrics(df_test, y_pred, y_true)

    log.info("─" * 60)
    log.info("Extra Trees on test split (H3+temporal hold-out, no leakage):")
    log.info(
        "  RMSE=%.2f  MAE=%.2f  bias=%+.2f  R²=%.4f  n=%d",
        overall["rmse_db"],
        overall["mae_db"],
        overall["bias_db"],
        overall["r2"],
        overall["n"],
    )
    log.info("  Per distance bin:")
    for b in bins:
        log.info(
            "    %s km : RMSE=%.2f MAE=%.2f bias=%+.2f n=%d",
            b["bin_km"],
            b["rmse_db"],
            b["mae_db"],
            b["bias_db"],
            b["n"],
        )
    log.info("  v0.6 XGBoost baseline: RMSE=%.2f dB", V06_XGB_BASELINE_RMSE_DB)
    delta = overall["rmse_db"] - V06_XGB_BASELINE_RMSE_DB
    verdict = "WORSE" if delta > 0 else "BETTER"
    log.info("  Δ vs v0.6: %+.2f dB → ET %s", delta, verdict)
    log.info("─" * 60)

    ts = pd.to_datetime(df_test["time"], utc=True, errors="coerce")
    ts_min = ts.min()
    ts_max = ts.max()

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "holdout_eval.json"
    out_path.write_text(
        json.dumps(
            {
                "window": {
                    "start": ts_min.isoformat() if pd.notna(ts_min) else None,
                    "end": ts_max.isoformat() if pd.notna(ts_max) else None,
                },
                "bbox_name": "csv_data_split=test",
                "bbox": None,
                "max_link_km": None,
                "feature_mode": "csv_data_split=test (no DB query, no leakage)",
                "overall": overall,
                "per_distance_bin": bins,
                "v06_xgboost_baseline_rmse_db": V06_XGB_BASELINE_RMSE_DB,
                "delta_vs_v06_db": overall["rmse_db"] - V06_XGB_BASELINE_RMSE_DB,
            },
            indent=2,
        )
    )
    log.info("Saved → %s", out_path)


if __name__ == "__main__":
    main()
