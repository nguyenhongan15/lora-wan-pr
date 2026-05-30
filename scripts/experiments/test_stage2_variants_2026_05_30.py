"""So sánh 4 cấu hình Stage 2 trên cùng tập huấn luyện + tập kiểm chứng độc lập.

Cấu hình:
  B   = baseline (giống train_residual_model.py mặc định)
  H1  = B + monotone_constraints[-1] cho distance_km, log_distance_km
  H2  = B + min_child_weight=20, reg_lambda=10, stratified split theo SF
  H12 = H1 + H2

Output: bảng so sánh RMSE/MAE/bias tổng thể và theo bin khoảng cách.

Chạy trong container api-service (cần crc-covlib + Stage 1 module). Phải
pip install xgboost joblib pandas trước.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parent.parent
_API_SRC = _REPO_ROOT / "services" / "api-service" / "src"
if _API_SRC.is_dir() and str(_API_SRC) not in sys.path:
    sys.path.insert(0, str(_API_SRC))

log = logging.getLogger("test_variants")

_BBOX = (15.8, 16.3, 107.9, 108.5)

FEATURE_COLS = [
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


def _fetch_rows(db_url, bbox, start, end, max_link_km):
    import psycopg

    min_lat, max_lat, min_lon, max_lon = bbox
    sql = """
        SELECT t.timestamp, ST_Y(t.location::geometry) AS lat,
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
          AND ST_Y(t.location::geometry) BETWEEN %s AND %s
          AND ST_X(t.location::geometry) BETWEEN %s AND %s
          AND t.serving_gateway_id IS NOT NULL
          AND ST_DistanceSphere(t.location::geometry, gw.location::geometry) < %s
    """
    params = [start, end, min_lat, max_lat, min_lon, max_lon, max_link_km * 1000.0]
    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def _build_dataset(rows, stage1, label):
    from lora_coverage_api.domain.coverage import Gateway, GatewayId, Target

    feats, residuals = [], []
    n_err = 0
    log_every = max(1, len(rows) // 10)
    for idx, r in enumerate(rows):
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
            residuals.append(float(r[3]) - pred.uplink_rssi_dbm)
            feats.append(
                [
                    target.latitude,
                    target.longitude,
                    float(target.spreading_factor),
                    target.frequency_mhz,
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
                log.warning("[%s] row %d err: %r", label, idx, e)
        if (idx + 1) % log_every == 0:
            log.info("[%s] %d/%d", label, idx + 1, len(rows))
    return np.asarray(feats, dtype=np.float64), np.asarray(residuals, dtype=np.float64)


def _build_stage1():
    import os

    from lora_coverage_api.application.itu.model import Stage1ItuModel
    from lora_coverage_api.application.path_loss import resolve_environment_profile
    from lora_coverage_api.infrastructure.itu.crc_covlib_backend import CrcCovlibBackend

    env = os.environ
    dem_dir = Path(env["LORA_DEM_DIRECTORY"])
    surf_raw = env.get("LORA_SURFACE_DEM_DIRECTORY", "")
    surf_dir = Path(surf_raw) if surf_raw else None
    backend = CrcCovlibBackend(
        dem_directory=dem_dir,
        surface_dem_directory=surf_dir,
        model_version="variant-test",
        percent_time=float(env.get("LORA_ITU_PERCENT_TIME", "50.0")),
        percent_location=float(env.get("LORA_ITU_PERCENT_LOCATION", "50.0")),
    )
    return Stage1ItuModel(
        model_version="variant-test",
        backend=backend,
        env_profile=resolve_environment_profile(env.get("LORA_ENV_PROFILE", "suburban")),
    )


def _add_derived(x):
    import pandas as pd

    df = pd.DataFrame(x, columns=FEATURE_COLS)
    lat1, lon1 = np.radians(df["lat"]), np.radians(df["lon"])
    lat2, lon2 = np.radians(df["gw_lat"]), np.radians(df["gw_lon"])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    df["distance_km"] = 2 * 6371.0088 * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))
    df["log_distance_km"] = np.log1p(df["distance_km"])
    df["delta_alt_m"] = df["gw_alt"] + df["gw_ant_h"]
    return df


def _stats(y_true, y_pred):
    err = y_true - y_pred
    return {
        "n": int(err.size),
        "bias": float(np.mean(err)),
        "rmse": float(np.sqrt(np.mean(err**2))),
        "mae": float(np.mean(np.abs(err))),
    }


def _stats_by_distance(df, y_true, y_pred):
    bins = [(-1, 2, "<2km"), (2, 5, "2-5km"), (5, 10, "5-10km"), (10, 999, ">=10km")]
    out = {}
    for lo, hi, label in bins:
        mask = (df["distance_km"].values >= lo) & (df["distance_km"].values < hi)
        if mask.sum() == 0:
            continue
        out[label] = _stats(y_true[mask], y_pred[mask])
    return out


def _train_variant(df_train_full, y_train, df_val_test, name, variant):
    import xgboost as xgb
    from sklearn.model_selection import StratifiedKFold, train_test_split

    monotone = variant.get("monotone", False)
    stratify_sf = variant.get("stratify_sf", False)
    mcw = variant.get("min_child_weight", 10)
    rlambda = variant.get("reg_lambda", 2.0)
    max_depth = variant.get("max_depth", 4)

    feature_names = list(df_train_full.columns)
    if monotone:
        mc = [(-1 if c in ("distance_km", "log_distance_km") else 0) for c in feature_names]
        monotone_str = "(" + ",".join(str(x) for x in mc) + ")"
    else:
        monotone_str = None

    if stratify_sf:
        sf_labels = df_train_full["sf"].astype(int).values
        skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
        train_idx, val_idx = next(skf.split(df_train_full, sf_labels))
        df_tr = df_train_full.iloc[train_idx].reset_index(drop=True)
        df_va = df_train_full.iloc[val_idx].reset_index(drop=True)
        y_tr = y_train[train_idx]
        y_va = y_train[val_idx]
    else:
        df_tr, df_va, y_tr, y_va = train_test_split(
            df_train_full, y_train, test_size=0.2, random_state=42
        )

    params = {
        "tree_method": "hist",
        "n_estimators": 2000,
        "learning_rate": 0.05,
        "max_depth": max_depth,
        "min_child_weight": mcw,
        "subsample": 0.7,
        "colsample_bytree": 0.7,
        "reg_alpha": 1.0,
        "reg_lambda": rlambda,
        "early_stopping_rounds": 50,
        "n_jobs": -1,
        "random_state": 42,
    }
    if monotone_str:
        params["monotone_constraints"] = monotone_str

    model = xgb.XGBRegressor(**params)
    model.fit(df_tr, y_tr, eval_set=[(df_va, y_va)], verbose=False)
    log.info("[%s] best_iter=%d / %d", name, model.best_iteration, params["n_estimators"])
    return model


def main() -> int:
    import os

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache-path", default="/tmp/stage2_variants_cache.npz")
    ap.add_argument("--out-json", default="/tmp/stage2_variants_results.json")
    args = ap.parse_args()

    cache = Path(args.cache_path)
    if cache.exists():
        log.info("Loading cache: %s", cache)
        z = np.load(cache)
        x_train, y_train = z["X_train"], z["y_train"]
        x_test, y_test = z["X_test"], z["y_test"]
    else:
        raw_url = os.environ.get("LORA_DB_URL") or os.environ["DATABASE_URL"]
        # psycopg3 không nhận prefix postgresql+psycopg://, strip phần SQLAlchemy.
        db_url = raw_url.replace("postgresql+psycopg://", "postgresql://", 1)
        train_rows = _fetch_rows(db_url, _BBOX, "2025-11-19", "2025-12-31", 50.0)
        test_rows = _fetch_rows(db_url, _BBOX, "2026-01-01", "2026-02-28", 50.0)
        log.info("Train rows=%d, test rows=%d", len(train_rows), len(test_rows))
        stage1 = _build_stage1()
        log.info("Computing Stage 1 baseline (train)...")
        x_train, y_train = _build_dataset(train_rows, stage1, "train")
        log.info("Computing Stage 1 baseline (test)...")
        x_test, y_test = _build_dataset(test_rows, stage1, "test")
        np.savez(cache, X_train=x_train, y_train=y_train, X_test=x_test, y_test=y_test)
        log.info("Cached → %s", cache)

    df_train = _add_derived(x_train)
    df_test = _add_derived(x_test)
    log.info("Train n=%d, test n=%d (after add_derived)", len(df_train), len(df_test))

    variants = {
        "B (gốc)": {},
        "H1 (đơn điệu)": {"monotone": True},
        "H2 (điều chuẩn + phân tầng)": {
            "min_child_weight": 20,
            "reg_lambda": 10.0,
            "stratify_sf": True,
        },
        "H1+H2 (kết hợp)": {
            "monotone": True,
            "min_child_weight": 20,
            "reg_lambda": 10.0,
            "stratify_sf": True,
        },
    }

    results = {}
    for name, var in variants.items():
        log.info("=== Training %s ===", name)
        model = _train_variant(df_train, y_train, df_test, name, var)
        train_pred = model.predict(df_train)
        test_pred = model.predict(df_test)
        overall = _stats(y_test, test_pred)
        by_dist = _stats_by_distance(df_test, y_test, test_pred)
        train_overall = _stats(y_train, train_pred)
        results[name] = {
            "overall": overall,
            "by_distance": by_dist,
            "train_overall": train_overall,
        }

    log.info("\n%s\n", json.dumps(results, indent=2))
    Path(args.out_json).write_text(json.dumps(results, indent=2))

    print("\n" + "=" * 100)
    print(f"{'Variant':<32} {'set':<8} {'n':>5} {'RMSE':>7} {'MAE':>7} {'bias':>7}")
    print("=" * 100)
    for name, r in results.items():
        ov = r["overall"]
        tr = r["train_overall"]
        print(
            f"{name:<32} {'TRAIN':<8} {tr['n']:>5} {tr['rmse']:>7.2f} {tr['mae']:>7.2f} {tr['bias']:>+7.2f}"
        )
        print(
            f"{name:<32} {'TEST':<8} {ov['n']:>5} {ov['rmse']:>7.2f} {ov['mae']:>7.2f} {ov['bias']:>+7.2f}"
        )
        for label in ["<2km", "2-5km", "5-10km", ">=10km"]:
            if label in r["by_distance"]:
                d = r["by_distance"][label]
                print(
                    f"  └─ {label:<27} {'TEST':<8} {d['n']:>5} {d['rmse']:>7.2f} {d['mae']:>7.2f} {d['bias']:>+7.2f}"
                )
        print("-" * 100)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
