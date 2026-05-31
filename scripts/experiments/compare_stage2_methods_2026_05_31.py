"""Compare 5 Stage 2 calibration methods cho heatmap RSSI composite.

Methods:
  M1: Pure physics (Stage 1 only, no Stage 2)
  M2: XGBoost no clip
  M3: XGBoost + clip residual ±15 dB
  M4: XGBoost + clip residual ±10 dB
  M5: Distance-binned bias (lookup từ train residuals, 4 bins)

Eval: 30 random holdout rows (Jan-Feb 2026, Đà Nẵng), per-row compute Stage 1
via Stage1ItuModel (api-service container), apply mỗi method → compute RMSE/MAE/bias.

CHẠY: docker exec -e PYTHONPATH=/install -w /app lora-wan-api uv run python scripts/experiments/compare_stage2_methods_2026_05_31.py
"""

from __future__ import annotations

import math
import os
import random
import sys
from pathlib import Path

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_API_SRC = _REPO_ROOT / "services" / "api-service" / "src"
if _API_SRC.is_dir() and str(_API_SRC) not in sys.path:
    sys.path.insert(0, str(_API_SRC))


N_TEST_ROWS = 30
N_TRAIN_ROWS_FOR_BIAS = 200
SEED = 42

DIST_BINS = [(0.0, 2.0), (2.0, 5.0), (5.0, 10.0), (10.0, 50.0)]
DIST_LABELS = ["<2km", "2-5km", "5-10km", "10-50km"]


def get_db_url() -> str:
    url = os.environ.get("LORA_DB_URL") or os.environ.get("DATABASE_URL", "")
    # Strip SQLAlchemy driver prefix nếu có
    return url.replace("postgresql+psycopg://", "postgresql://")


def fetch_rows(start: str, end: str, limit: int):
    import psycopg

    sql = """
        SELECT t.timestamp,
               ST_Y(t.location::geometry) AS lat,
               ST_X(t.location::geometry) AS lon,
               t.rssi_dbm, t.snr_db, t.spreading_factor,
               t.serving_gateway_id,
               gw.code, gw.name, gw.altitude_m, gw.antenna_height_m,
               gw.antenna_gain_dbi, gw.tx_power_dbm, gw.frequency_mhz,
               ST_Y(gw.location::geometry) AS gw_lat,
               ST_X(gw.location::geometry) AS gw_lon
        FROM ts.survey_training t
        JOIN geo.gateways gw ON gw.id = t.serving_gateway_id
        WHERE t.timestamp >= %s::date AND t.timestamp <= %s::date
          AND ST_Y(t.location::geometry) BETWEEN 15.8 AND 16.3
          AND ST_X(t.location::geometry) BETWEEN 107.9 AND 108.5
          AND t.serving_gateway_id IS NOT NULL
          AND ST_DistanceSphere(t.location::geometry, gw.location::geometry) < 50000
        ORDER BY random()
        LIMIT %s
    """
    with psycopg.connect(get_db_url()) as c, c.cursor() as cur:
        cur.execute(sql, (start, end, limit))
        return cur.fetchall()


def build_stage1():
    from lora_coverage_api.application.itu.model import Stage1ItuModel
    from lora_coverage_api.application.path_loss import resolve_environment_profile
    from lora_coverage_api.infrastructure.itu.crc_covlib_backend import CrcCovlibBackend

    dem_dir = Path(os.environ["LORA_DEM_DIRECTORY"])
    surf_raw = os.environ.get("LORA_SURFACE_DEM_DIRECTORY", "")
    surf_dir = Path(surf_raw) if surf_raw else None
    env_name = os.environ.get("LORA_ENV_PROFILE", "suburban")

    backend = CrcCovlibBackend(
        dem_directory=dem_dir,
        surface_dem_directory=surf_dir,
        model_version="test-compare-stage2",
        percent_time=50.0,
        percent_location=50.0,
    )
    return Stage1ItuModel(
        model_version="test-compare-stage2",
        backend=backend,
        env_profile=resolve_environment_profile(env_name),
    )


def compute_stage1_residuals(rows, stage1):
    """Per row: predict stage1 RSSI, return (features_df, measured, stage1_pred, distance_km)."""
    from lora_coverage_api.domain.coverage import Gateway, GatewayId, Target

    feats = []
    measured = []
    stage1_preds = []
    distances = []
    n_err = 0
    for i, r in enumerate(rows):
        try:
            target = Target(
                latitude=float(r[1]),
                longitude=float(r[2]),
                spreading_factor=int(r[5]),
                frequency_mhz=float(r[13]),
            )
            gw = Gateway(
                id=GatewayId(r[6]),
                code=str(r[7]),
                name=str(r[8]),
                latitude=float(r[14]),
                longitude=float(r[15]),
                altitude_m=float(r[9]),
                antenna_height_m=float(r[10]),
                antenna_gain_dbi=float(r[11]),
                tx_power_dbm=float(r[12]),
                frequency_mhz=float(r[13]),
            )
            pred = stage1.predict(target, gw)
            stage1_preds.append(pred.uplink_rssi_dbm)
            measured.append(float(r[3]))
            R = 6371.0
            dlat = math.radians(target.latitude - gw.latitude)
            dlon = math.radians(target.longitude - gw.longitude)
            a = (
                math.sin(dlat / 2) ** 2
                + math.cos(math.radians(gw.latitude))
                * math.cos(math.radians(target.latitude))
                * math.sin(dlon / 2) ** 2
            )
            dist_km = 2 * R * math.asin(math.sqrt(a))
            distances.append(dist_km)
            feats.append(
                {
                    "lat": target.latitude,
                    "lon": target.longitude,
                    "sf": float(target.spreading_factor),
                    "gw_lat": gw.latitude,
                    "gw_lon": gw.longitude,
                    "distance_km": dist_km,
                    "log_distance_km": math.log10(max(dist_km, 0.001)),
                    "delta_alt_m": gw.altitude_m,
                }
            )
        except Exception as e:
            n_err += 1
            if n_err <= 3:
                print(f"  row {i} err: {e!r}", flush=True)
        if (i + 1) % 10 == 0:
            print(f"  stage1: {i + 1}/{len(rows)} ({n_err} err)", flush=True)
    return feats, measured, stage1_preds, distances


def stats(y_true, y_pred, label=""):
    err = [p - t for p, t in zip(y_pred, y_true, strict=True)]
    n = len(err)
    mae = sum(abs(e) for e in err) / n
    rmse = math.sqrt(sum(e * e for e in err) / n)
    bias = sum(err) / n
    return {"n": n, "mae": mae, "rmse": rmse, "bias": bias, "label": label}


def main():
    random.seed(SEED)
    print(
        f"=== Compare 5 Stage 2 methods (n_test={N_TEST_ROWS}, n_train_for_bias={N_TRAIN_ROWS_FOR_BIAS}) ==="
    )

    print("\n[1] Fetch holdout rows (Jan-Feb 2026)...")
    test_rows = fetch_rows("2026-01-01", "2026-02-28", N_TEST_ROWS)
    print(f"  fetched {len(test_rows)}")

    print("\n[2] Fetch train rows (Nov-Dec 2025) for bias table...")
    train_rows = fetch_rows("2025-11-19", "2025-12-31", N_TRAIN_ROWS_FOR_BIAS)
    print(f"  fetched {len(train_rows)}")

    print("\n[3] Build Stage 1 model...")
    stage1 = build_stage1()

    print("\n[4] Compute Stage 1 on TEST holdout...")
    test_feats, test_meas, test_s1, test_dist = compute_stage1_residuals(test_rows, stage1)
    print(f"  done: {len(test_feats)} usable test rows")

    print("\n[5] Compute Stage 1 on TRAIN (build bias table)...")
    train_feats, train_meas, train_s1, train_dist = compute_stage1_residuals(train_rows, stage1)
    print(f"  done: {len(train_feats)} usable train rows")

    train_residuals = [m - s for m, s in zip(train_meas, train_s1, strict=True)]

    print("\n[6] Build distance-binned bias table from train residuals:")
    bias_table = []
    for lo, hi in DIST_BINS:
        residuals_in_bin = [
            r for r, d in zip(train_residuals, train_dist, strict=True) if lo <= d < hi
        ]
        if residuals_in_bin:
            mean = sum(residuals_in_bin) / len(residuals_in_bin)
        else:
            mean = 0.0
        bias_table.append((lo, hi, mean, len(residuals_in_bin)))
        print(f"  {lo:.0f}-{hi:.0f} km: mean_residual={mean:+.2f} dB (n={len(residuals_in_bin)})")

    def bias_lookup(d_km):
        for lo, hi, mean, _ in bias_table:
            if lo <= d_km < hi:
                return mean
        return 0.0

    print("\n[7] Load XGBoost model...")
    import joblib
    import pandas as pd

    candidates = [
        "/tmp/stage2_xgb.joblib",
        "/app-shared/ml/stage2_xgb.joblib",
        "/app/data/stage2_xgb.joblib",
        "/app/services/ml-service/data/stage2_xgb.joblib",
    ]
    model_path = next((p for p in candidates if Path(p).exists()), candidates[0])
    print(f"  loading {model_path}")
    m = joblib.load(model_path)

    df_test = pd.DataFrame(test_feats)[
        ["lat", "lon", "sf", "gw_lat", "gw_lon", "distance_km", "log_distance_km", "delta_alt_m"]
    ]
    xgb_pred = m.predict(df_test)

    print("\n[8] Evaluate 5 methods:")
    methods = {
        "M1_pure_physics": list(test_s1),
        "M2_xgb_noclip": [s1 + x for s1, x in zip(test_s1, xgb_pred, strict=True)],
        "M3_xgb_clip15": [
            s1 + np.clip(x, -15, 15) for s1, x in zip(test_s1, xgb_pred, strict=True)
        ],
        "M4_xgb_clip10": [
            s1 + np.clip(x, -10, 10) for s1, x in zip(test_s1, xgb_pred, strict=True)
        ],
        "M5_dist_bin_bias": [s1 + bias_lookup(d) for s1, d in zip(test_s1, test_dist, strict=True)],
    }

    print(f"\n{'Method':<22} {'n':>4} {'MAE':>7} {'RMSE':>7} {'bias':>7}")
    print("-" * 60)
    all_stats = {}
    for name, preds in methods.items():
        s = stats(test_meas, preds, name)
        all_stats[name] = s
        print(f"{name:<22} {s['n']:>4} {s['mae']:>7.2f} {s['rmse']:>7.2f} {s['bias']:>+7.2f}")

    print("\nPer distance bin RMSE:")
    print(f"{'Method':<22} " + " ".join(f"{lbl:>10}" for lbl in DIST_LABELS))
    for name, preds in methods.items():
        cells = []
        for lo, hi in DIST_BINS:
            in_bin = [
                (t, p) for t, p, d in zip(test_meas, preds, test_dist, strict=True) if lo <= d < hi
            ]
            if in_bin:
                rmse = math.sqrt(sum((p - t) ** 2 for t, p in in_bin) / len(in_bin))
                cells.append(f"{rmse:>6.2f}(n{len(in_bin)})")
            else:
                cells.append("       n/a")
        print(f"{name:<22} " + " ".join(cells))


if __name__ == "__main__":
    main()
