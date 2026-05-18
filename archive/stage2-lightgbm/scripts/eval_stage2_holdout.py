"""Evaluate Stage 1 baseline vs Stage 1+2 on spatial-split test fold.

Pipeline mirrors retrain.run_retrain():
  1. data.collect(settings) → time-split TrainingFrame.
  2. concat train_val + test, then SpatialStratifiedSplitter.assign() → spatial test fold.
  3. Load latest artifact, apply Categorical dtype with stored category_maps.
  4. Predict residual; report Stage 1 vs Stage 1+2 (raw and +guardrail).

Output:
  - Overall RMSE/MAE/bias.
  - Per spreading_factor breakdown.
  - Per distance bucket breakdown.
  - Top feature importance (gain).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from lora_ml_predict.config import get_settings
from lora_ml_predict.training import data as data_mod
from lora_ml_predict.training.guardrail import clean
from lora_ml_predict.training.splitter import SpatialStratifiedSplitter


def _rmse(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.sqrt(np.mean((a - b) ** 2)))


def _mae(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.mean(np.abs(a - b)))


def main() -> None:
    settings = get_settings()
    artifact_dir: Path = settings.stage2_artifact_dir
    latest = sorted(artifact_dir.glob("stage2-*"))[-1]
    print(f"Artifact: {latest.name}", file=sys.stderr)

    meta = json.loads((latest / "meta.json").read_text(encoding="utf-8"))
    feature_cols: list[str] = meta["feature_columns"]
    categorical: list[str] = meta["categorical_features"]
    category_maps: dict[str, list[str]] = meta["category_maps"]

    booster = lgb.Booster(model_file=str(latest / "model.lgb"))

    print("Collecting features (re-extracting; ~90s)...", file=sys.stderr)
    tf = data_mod.collect(settings)
    combined = pd.concat([tf.train_val, tf.test], ignore_index=True)
    splitter = SpatialStratifiedSplitter(seed=settings.optuna_seed)
    labels = splitter.assign(combined)
    test_df = combined[labels == "test"].reset_index(drop=True)
    print(f"Test rows: {len(test_df)}", file=sys.stderr)

    x_test = test_df[feature_cols].copy()
    for col in categorical:
        cats = category_maps[col]
        x_test[col] = pd.Categorical(x_test[col].astype(str), categories=cats)

    y_obs = test_df["rssi_dbm_measured"].to_numpy(dtype=np.float64)
    residual_true = test_df["residual_db"].to_numpy(dtype=np.float64)
    rssi_stage1 = y_obs - residual_true

    residual_pred = booster.predict(x_test)
    rssi_raw_stage12 = rssi_stage1 + residual_pred
    rssi_clean, violated = clean(rssi_stage1, residual_pred)

    print()
    print(f"=== OVERALL (test set, n={len(y_obs)}) ===")
    print(
        f"  Stage 1 only             RMSE={_rmse(rssi_stage1, y_obs):6.2f}"
        f"  MAE={_mae(rssi_stage1, y_obs):6.2f}"
        f"  bias={float(np.mean(rssi_stage1 - y_obs)):+6.2f}"
    )
    print(
        f"  Stage 1+2 (no guardrail) RMSE={_rmse(rssi_raw_stage12, y_obs):6.2f}"
        f"  MAE={_mae(rssi_raw_stage12, y_obs):6.2f}"
        f"  bias={float(np.mean(rssi_raw_stage12 - y_obs)):+6.2f}"
    )
    print(
        f"  Stage 1+2 (+guardrail)   RMSE={_rmse(rssi_clean, y_obs):6.2f}"
        f"  MAE={_mae(rssi_clean, y_obs):6.2f}"
        f"  bias={float(np.mean(rssi_clean - y_obs)):+6.2f}"
    )
    n_viol = int(np.sum(violated))
    print(f"  guardrail violations: {n_viol}/{len(y_obs)} = {n_viol / len(y_obs):.1%}")

    print()
    print("=== PER SPREADING FACTOR ===")
    print(f"  {'SF':>3} {'n':>6}   {'Stg1 RMSE':>10}   {'Stg1+2 RMSE':>11}   {'Improv':>7}")
    sf_arr = test_df["spreading_factor"].to_numpy()
    for sf in sorted(np.unique(sf_arr).tolist()):
        mask = sf_arr == sf
        r1 = _rmse(rssi_stage1[mask], y_obs[mask])
        r12 = _rmse(rssi_clean[mask], y_obs[mask])
        improv = (r1 - r12) / r1 if r1 > 0 else 0.0
        print(f"  {int(sf):>3} {int(mask.sum()):>6}   {r1:>10.2f}   {r12:>11.2f}   {improv:>+7.1%}")

    print()
    print("=== PER DISTANCE BUCKET (km) ===")
    print(f"  {'bucket':>12} {'n':>6}   {'Stg1 RMSE':>10}   {'Stg1+2 RMSE':>11}   {'Improv':>7}")
    d_km = np.power(10.0, test_df["log10_distance_to_serving_gw_km"].to_numpy(dtype=np.float64))
    edges = [0.0, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, float("inf")]
    labels_b = ["0-0.5", "0.5-1", "1-2", "2-5", "5-10", "10-20", "20+"]
    bucket_arr = np.asarray(pd.cut(d_km, bins=edges, labels=labels_b, include_lowest=True))
    for lab in labels_b:
        mask = bucket_arr == lab
        n = int(mask.sum())
        if n == 0:
            continue
        r1 = _rmse(rssi_stage1[mask], y_obs[mask])
        r12 = _rmse(rssi_clean[mask], y_obs[mask])
        improv = (r1 - r12) / r1 if r1 > 0 else 0.0
        print(f"  {lab:>12} {n:>6}   {r1:>10.2f}   {r12:>11.2f}   {improv:>+7.1%}")

    print()
    print("=== TOP FEATURE IMPORTANCE (gain) ===")
    importance = booster.feature_importance(importance_type="gain")
    names = booster.feature_name()
    order = np.argsort(importance)[::-1]
    total = float(importance.sum())
    for i in order[:8]:
        share = importance[i] / total if total > 0 else 0.0
        print(f"  {names[i]:>30}  gain={float(importance[i]):>10.0f}  ({share:.1%})")


if __name__ == "__main__":
    main()
