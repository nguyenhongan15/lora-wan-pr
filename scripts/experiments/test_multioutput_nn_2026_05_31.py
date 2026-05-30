"""Test feasibility: multi-output MLP (RSSI residual + SNR) vs single-output baseline.

Lý thuyết:
  - Stage 1 (ITU P.1812) chỉ predict path-loss → RSSI; KHÔNG predict SNR.
  - SNR mang info bổ sung về noise floor, nhiễu, fading → orthogonal với
    path-loss; có thể regularize hidden layer của model.
  - Multi-task NN: shared trunk + 2 head (1 cho rssi_residual, 1 cho snr_db).
    Joint loss = MSE(rssi_res) + λ·MSE(snr_std). Hai target standardize trước.

Pipeline:
  1. Build cache với (X, y_rssi_residual, y_snr_db) — rerun Stage 1 nếu cache cũ chỉ có y_rssi.
  2. Train baseline MLP (1 output: rssi_residual).
  3. Train multi-output MLP (2 outputs: rssi_residual + snr_db).
  4. Compare test RMSE trên rssi_residual (apples-to-apples).
  5. Compare với XGBoost v0.5 cùng setup.

Chạy:
    docker cp scripts/experiments/test_multioutput_nn_2026_05_31.py \\
        lora-wan-api:/tmp/test_mo.py
    docker exec lora-wan-api python /tmp/test_mo.py
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("test_multi_nn")

CACHE_PATH = Path("/tmp/stage2_multi_cache.npz")
RAW_COLS = [
    "lat",
    "lon",
    "sf",
    "frequency_mhz",
    "gw_lat",
    "gw_lon",
    "gw_alt",
    "gw_ant_h",
    "gw_gain",
    "gw_tx_p",
]
TRAINING_FEATS = [
    "lat",
    "lon",
    "sf",
    "gw_lat",
    "gw_lon",
    "distance_km",
    "log_distance_km",
    "delta_alt_m",
]
BBOX_DANANG = (15.8, 16.3, 107.9, 108.5)


def add_derived(X: np.ndarray) -> pd.DataFrame:
    df = pd.DataFrame(X, columns=RAW_COLS)
    lat1, lon1 = np.radians(df["lat"]), np.radians(df["lon"])
    lat2, lon2 = np.radians(df["gw_lat"]), np.radians(df["gw_lon"])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    df["distance_km"] = 2 * 6371.0088 * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))
    df["log_distance_km"] = np.log1p(df["distance_km"])
    df["delta_alt_m"] = df["gw_alt"] + df["gw_ant_h"]
    return df


def build_cache() -> None:
    """Re-query DB + rerun Stage 1 + lưu (X, y_rssi, y_snr)."""
    import psycopg

    _API_SRC = Path("/install/lib/python3.12/site-packages")
    if str(_API_SRC) not in sys.path:
        sys.path.insert(0, str(_API_SRC))
    from lora_coverage_api.application.itu.model import Stage1ItuModel
    from lora_coverage_api.application.path_loss import resolve_environment_profile
    from lora_coverage_api.domain.coverage import Gateway, GatewayId, Target
    from lora_coverage_api.infrastructure.itu.crc_covlib_backend import CrcCovlibBackend

    db_url = os.environ.get("LORA_DB_URL") or os.environ["DATABASE_URL"]
    # psycopg connect không nhận driver suffix; strip nếu có.
    db_url = db_url.replace("postgresql+psycopg://", "postgresql://")
    min_lat, max_lat, min_lon, max_lon = BBOX_DANANG

    sql = """
        SELECT ST_Y(t.location::geometry) AS lat,
               ST_X(t.location::geometry) AS lon,
               t.rssi_dbm, t.snr_db, t.spreading_factor,
               t.serving_gateway_id,
               gw.code, gw.name, gw.altitude_m, gw.antenna_height_m,
               gw.antenna_gain_dbi, gw.tx_power_dbm, gw.frequency_mhz,
               ST_Y(gw.location::geometry) AS gw_lat,
               ST_X(gw.location::geometry) AS gw_lon,
               t.timestamp
        FROM ts.survey_training t
        JOIN geo.gateways gw ON gw.id = t.serving_gateway_id
        WHERE t.timestamp >= %s::date AND t.timestamp <= %s::date
          AND ST_Y(t.location::geometry) BETWEEN %s AND %s
          AND ST_X(t.location::geometry) BETWEEN %s AND %s
          AND t.serving_gateway_id IS NOT NULL
          AND ST_DistanceSphere(t.location::geometry, gw.location::geometry) < %s
        ORDER BY t.timestamp, t.id
    """

    def fetch(start, end):
        with psycopg.connect(db_url) as conn, conn.cursor() as cur:
            cur.execute(sql, [start, end, min_lat, max_lat, min_lon, max_lon, 50_000.0])
            return cur.fetchall()

    train_rows = fetch("2025-11-01", "2026-01-01")
    test_rows = fetch("2026-01-01", "2026-03-01")
    log.info("DB: train=%d test=%d", len(train_rows), len(test_rows))

    surf_raw = os.environ.get("LORA_SURFACE_DEM_DIRECTORY") or ""
    backend = CrcCovlibBackend(
        dem_directory=Path(os.environ["LORA_DEM_DIRECTORY"]),
        surface_dem_directory=Path(surf_raw) if surf_raw else None,
        model_version="multi-cache",
        percent_time=float(os.environ.get("LORA_ITU_PERCENT_TIME", "50.0")),
        percent_location=float(os.environ.get("LORA_ITU_PERCENT_LOCATION", "50.0")),
    )
    stage1 = Stage1ItuModel(
        model_version="multi-cache",
        backend=backend,
        env_profile=resolve_environment_profile(os.environ.get("LORA_ENV_PROFILE", "suburban")),
    )

    def build(rows, label):
        X, y_r, y_s = [], [], []
        n_err = 0
        n_total = len(rows)
        log_every = max(1, n_total // 10)
        for i, r in enumerate(rows):
            try:
                t = Target(
                    latitude=float(r[0]),
                    longitude=float(r[1]),
                    spreading_factor=int(r[4]),
                    frequency_mhz=float(r[12]),
                )
                gw = Gateway(
                    id=GatewayId(r[5]),
                    code=str(r[6]),
                    name=str(r[7]),
                    latitude=float(r[13]),
                    longitude=float(r[14]),
                    altitude_m=float(r[8]),
                    antenna_height_m=float(r[9]),
                    antenna_gain_dbi=float(r[10]),
                    tx_power_dbm=float(r[11]),
                    frequency_mhz=float(r[12]),
                )
                pred = stage1.predict(t, gw)
                y_r.append(float(r[2]) - pred.uplink_rssi_dbm)
                y_s.append(float(r[3]))
                X.append(
                    [
                        t.latitude,
                        t.longitude,
                        float(t.spreading_factor),
                        t.frequency_mhz,
                        gw.latitude,
                        gw.longitude,
                        gw.altitude_m,
                        gw.antenna_height_m,
                        gw.antenna_gain_dbi,
                        gw.tx_power_dbm,
                    ]
                )
            except Exception as e:
                n_err += 1
                if n_err <= 3:
                    log.warning("[%s] row %d: %r", label, i, e)
            if (i + 1) % log_every == 0:
                log.info("[%s] %d/%d (err=%d)", label, i + 1, n_total, n_err)
        return (
            np.asarray(X, dtype=np.float64),
            np.asarray(y_r, dtype=np.float64),
            np.asarray(y_s, dtype=np.float64),
        )

    log.info("Stage 1 on train...")
    Xtr, yrtr, ystr = build(train_rows, "train")
    log.info("Stage 1 on test...")
    Xte, yrte, yste = build(test_rows, "test")
    np.savez(
        CACHE_PATH,
        X_train=Xtr,
        y_rssi_train=yrtr,
        y_snr_train=ystr,
        X_test=Xte,
        y_rssi_test=yrte,
        y_snr_test=yste,
    )
    log.info("Saved cache → %s", CACHE_PATH)


def run_test() -> None:
    from sklearn.neural_network import MLPRegressor
    from sklearn.preprocessing import StandardScaler

    c = np.load(CACHE_PATH)
    Xtr_raw, Xte_raw = c["X_train"], c["X_test"]
    y_rssi_tr, y_rssi_te = c["y_rssi_train"], c["y_rssi_test"]
    y_snr_tr, y_snr_te = c["y_snr_train"], c["y_snr_test"]
    log.info("train=%d test=%d", len(Xtr_raw), len(Xte_raw))
    log.info("y_rssi train: mean=%.2f std=%.2f", y_rssi_tr.mean(), y_rssi_tr.std())
    log.info("y_snr  train: mean=%.2f std=%.2f", y_snr_tr.mean(), y_snr_tr.std())

    df_tr = add_derived(Xtr_raw)[TRAINING_FEATS]
    df_te = add_derived(Xte_raw)[TRAINING_FEATS]
    sx = StandardScaler().fit(df_tr)
    Xtr = sx.transform(df_tr)
    Xte = sx.transform(df_te)

    # Standardize y for joint loss balance
    sy_r = StandardScaler().fit(y_rssi_tr.reshape(-1, 1))
    sy_s = StandardScaler().fit(y_snr_tr.reshape(-1, 1))
    y_rssi_tr_s = sy_r.transform(y_rssi_tr.reshape(-1, 1)).ravel()
    y_snr_tr_s = sy_s.transform(y_snr_tr.reshape(-1, 1)).ravel()

    # === Baseline NN single-output (rssi_residual standardized) ===
    log.info("Training single-output MLP...")
    t0 = time.time()
    nn1 = MLPRegressor(
        hidden_layer_sizes=(64, 32),
        activation="relu",
        solver="adam",
        learning_rate_init=1e-3,
        batch_size=128,
        alpha=1e-3,
        max_iter=500,
        early_stopping=True,
        validation_fraction=0.15,
        n_iter_no_change=20,
        random_state=42,
    )
    nn1.fit(Xtr, y_rssi_tr_s)
    log.info("  fit %.1fs, iters=%d", time.time() - t0, nn1.n_iter_)

    pred1_s = nn1.predict(Xte)
    pred1 = sy_r.inverse_transform(pred1_s.reshape(-1, 1)).ravel()
    err1 = pred1 - y_rssi_te
    nn1_rmse = float(np.sqrt(np.mean(err1**2)))
    nn1_mae = float(np.mean(np.abs(err1)))
    nn1_bias = float(np.mean(err1))

    # === Multi-output NN (rssi_residual + snr_db standardized) ===
    log.info("Training multi-output MLP...")
    Y_multi = np.column_stack([y_rssi_tr_s, y_snr_tr_s])
    t0 = time.time()
    nn2 = MLPRegressor(
        hidden_layer_sizes=(64, 32),
        activation="relu",
        solver="adam",
        learning_rate_init=1e-3,
        batch_size=128,
        alpha=1e-3,
        max_iter=500,
        early_stopping=True,
        validation_fraction=0.15,
        n_iter_no_change=20,
        random_state=42,
    )
    nn2.fit(Xtr, Y_multi)
    log.info("  fit %.1fs, iters=%d", time.time() - t0, nn2.n_iter_)

    pred2_s = nn2.predict(Xte)  # (n, 2)
    pred2_rssi = sy_r.inverse_transform(pred2_s[:, 0].reshape(-1, 1)).ravel()
    pred2_snr = sy_s.inverse_transform(pred2_s[:, 1].reshape(-1, 1)).ravel()
    err2 = pred2_rssi - y_rssi_te
    nn2_rmse = float(np.sqrt(np.mean(err2**2)))
    nn2_mae = float(np.mean(np.abs(err2)))
    nn2_bias = float(np.mean(err2))

    err_snr = pred2_snr - y_snr_te
    snr_rmse = float(np.sqrt(np.mean(err_snr**2)))
    snr_mae = float(np.mean(np.abs(err_snr)))

    # === XGBoost baseline reference ===
    log.info("Training XGBoost v0.5 reference...")
    import xgboost as xgb
    from sklearn.model_selection import StratifiedKFold

    sf_i = df_tr["sf"].astype(int).to_numpy()
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    tr_i, va_i = next(skf.split(df_tr, sf_i))
    xgb_m = xgb.XGBRegressor(
        tree_method="hist",
        n_estimators=2000,
        learning_rate=0.05,
        max_depth=4,
        min_child_weight=20,
        subsample=0.7,
        colsample_bytree=0.7,
        reg_alpha=1.0,
        reg_lambda=10.0,
        early_stopping_rounds=50,
        n_jobs=-1,
        random_state=42,
    )
    xgb_m.fit(
        df_tr.iloc[tr_i],
        y_rssi_tr[tr_i],
        eval_set=[(df_tr.iloc[va_i], y_rssi_tr[va_i])],
        verbose=False,
    )
    xgb_pred = xgb_m.predict(df_te)
    xgb_err = xgb_pred - y_rssi_te
    xgb_rmse = float(np.sqrt(np.mean(xgb_err**2)))
    xgb_mae = float(np.mean(np.abs(xgb_err)))
    xgb_bias = float(np.mean(xgb_err))

    print("\n" + "=" * 70)
    print(f"RESULTS (RSSI residual prediction, test n={len(y_rssi_te)})")
    print("=" * 70)
    print(f"  {'model':25s} {'RMSE':>6s} {'MAE':>6s} {'bias':>7s}")
    print(f"  {'XGBoost v0.5 (ref)':25s} {xgb_rmse:>6.2f} {xgb_mae:>6.2f} {xgb_bias:>+7.2f}")
    print(f"  {'NN single-output':25s} {nn1_rmse:>6.2f} {nn1_mae:>6.2f} {nn1_bias:>+7.2f}")
    print(f"  {'NN multi-output':25s} {nn2_rmse:>6.2f} {nn2_mae:>6.2f} {nn2_bias:>+7.2f}")
    print()
    print(f"Multi-output bonus: SNR RMSE={snr_rmse:.2f} MAE={snr_mae:.2f}")
    print(f"Δ multi vs single: {nn2_rmse - nn1_rmse:+.2f} dB RMSE")
    print(f"Δ multi vs XGB:    {nn2_rmse - xgb_rmse:+.2f} dB RMSE")


def main():
    if not CACHE_PATH.exists():
        log.info("Cache missing → building (will take ~5 min)...")
        build_cache()
    else:
        log.info("Reusing cache %s", CACHE_PATH)
    run_test()


if __name__ == "__main__":
    main()
