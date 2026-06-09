"""Eval Extra Trees on ts.survey_training Jan-Feb 2026 hold-out.

Computes the 20 ET features using the ported reference module
(`lora_ml_predict.processing.compute_link_features`) — i.e. real DEM + OSM
landuse lookup, matching training-time pipeline.

Compares against v0.6 XGBoost baseline (RMSE 10.58 dB, memory
project_ml_deferred) on the same hold-out window.

Usage:
    LORA_DB_URL=... \
    LORA_REFERENCE_DEM_DIRECTORY=E:/DATN/lora-data/dem \
    LORA_OSM_LANDUSE_DIRECTORY=E:/DATN/lora-coverage/data/osm \
    uv run --with scikit-learn --with "psycopg[binary]" --with rasterio \
        --with geopandas --with shapely \
        python scripts/eval_extra_trees_holdout.py
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "services" / "ml-service" / "src"))

from lora_ml_predict.processing import compute_link_features  # noqa: E402

MODEL_PATH = REPO_ROOT / "services" / "ml-service" / "data" / "extra_trees_model.joblib"
REPORT_DIR = REPO_ROOT / "reports" / "seven-train"

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

EASY_FEATURES = {
    "frequency",
    "spreading_factor",
    "log_distance",
    "delta_lat",
    "delta_lon",
    "angle",
    "gw_elevation",
}
HARD_FEATURES = [f for f in NUMERIC_FEATURES if f not in EASY_FEATURES]

V06_XGB_BASELINE_RMSE_DB = 10.58

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(a, 1.0)))


def fetch_rows(
    db_url: str,
    start: str,
    end: str,
    bbox: tuple[float, float, float, float],
    max_link_km: float,
) -> list[tuple]:
    import psycopg

    min_lat, max_lat, min_lon, max_lon = bbox
    sql = """
        SELECT t.timestamp,
               ST_Y(t.location::geometry) AS lat,
               ST_X(t.location::geometry) AS lon,
               t.rssi_dbm,
               t.spreading_factor,
               gw.code,
               gw.altitude_m,
               gw.antenna_height_m,
               gw.frequency_mhz,
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


def rows_to_features(rows: list[tuple], log: logging.Logger) -> pd.DataFrame:
    records = []
    skipped = 0
    for i, r in enumerate(rows):
        lat = float(r[1])
        lon = float(r[2])
        rssi = float(r[3])
        sf = int(r[4])
        gw_code = str(r[5])
        gw_ant_h_m = float(r[7]) if r[7] is not None else 15.0
        gw_freq_mhz = float(r[8])
        gw_lat = float(r[9])
        gw_lon = float(r[10])

        feats = compute_link_features(
            lat=lat,
            lon=lon,
            gw_lat=gw_lat,
            gw_lon=gw_lon,
            gw_ant_h_m=gw_ant_h_m,
            freq_hz=gw_freq_mhz * 1e6,
            sf=sf,
            gateway_code=gw_code,
        )
        if feats is None:
            skipped += 1
            continue
        feats["__rssi"] = rssi
        records.append(feats)
        if (i + 1) % 50 == 0:
            log.info("  computed %d / %d (skipped %d)", i + 1, len(rows), skipped)
    log.info("Total: %d kept, %d skipped (DEM lookup failed)", len(records), skipped)
    return pd.DataFrame(records)


def compute_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    err = y_true - y_pred
    return {
        "n": len(err),
        "rmse_db": float(np.sqrt(np.mean(err**2))),
        "mae_db": float(np.mean(np.abs(err))),
        "bias_db": float(np.mean(err)),
        "r2": float(1 - np.sum(err**2) / np.sum((y_true - y_true.mean()) ** 2)),
    }


def per_distance_bin_metrics(df: pd.DataFrame, y_pred: np.ndarray) -> list[dict]:
    bins = [(0.0, 2.0), (2.0, 5.0), (5.0, 10.0), (10.0, 50.0)]
    out = []
    log_d = df["log_distance"].to_numpy()
    dist_m = np.power(10.0, log_d)
    dist_km = dist_m / 1000.0
    y_true = df["__rssi"].to_numpy()
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
    p.add_argument("--start", default="2026-01-01")
    p.add_argument("--end", default="2026-02-28")
    p.add_argument("--bbox", choices=["danang", "haiphong", "vietnam"], default="danang")
    p.add_argument("--max-link-km", type=float, default=50.0)
    p.add_argument("--db-url", default=os.environ.get("LORA_DB_URL"))
    args = p.parse_args()

    bbox_presets = {
        "danang": (15.8, 16.3, 107.9, 108.5),
        "haiphong": (20.7, 21.0, 106.55, 106.85),
        "vietnam": (8.4, 23.4, 102.1, 109.5),
    }
    bbox = bbox_presets[args.bbox]

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    log = logging.getLogger("eval_holdout")

    if not args.db_url:
        raise SystemExit("LORA_DB_URL not set (env or --db-url)")
    if not MODEL_PATH.exists():
        raise SystemExit(f"Model not found at {MODEL_PATH}. Run train_extra_trees.py first.")
    if not os.environ.get("LORA_REFERENCE_DEM_DIRECTORY"):
        raise SystemExit("LORA_REFERENCE_DEM_DIRECTORY not set")
    if not os.environ.get("LORA_OSM_LANDUSE_DIRECTORY"):
        raise SystemExit("LORA_OSM_LANDUSE_DIRECTORY not set")

    log.info("Loading model from %s", MODEL_PATH)
    model = joblib.load(MODEL_PATH)

    log.info(
        "Query hold-out %s..%s bbox=%s (%s) max_d=%.0fkm",
        args.start,
        args.end,
        args.bbox,
        bbox,
        args.max_link_km,
    )
    rows = fetch_rows(args.db_url, args.start, args.end, bbox, args.max_link_km)
    log.info("Fetched %d rows", len(rows))
    if not rows:
        raise SystemExit("No rows in window — check bbox / dates")

    log.info("Computing features for %d links (DEM + OSM lookup per point)...", len(rows))
    df = rows_to_features(rows, log)
    log.info(
        "RSSI stats: mean=%.2f std=%.2f min=%.0f max=%.0f",
        df["__rssi"].mean(),
        df["__rssi"].std(),
        df["__rssi"].min(),
        df["__rssi"].max(),
    )

    log.info("Unique gateways in hold-out: %d", df["gateway"].nunique())

    X = df[ALL_FEATURES]
    y_true = df["__rssi"].to_numpy()

    log.info("Predicting %d rows...", len(X))
    y_pred = model.predict(X)
    overall = compute_metrics(y_true, y_pred)

    bins = per_distance_bin_metrics(df, y_pred)

    log.info("─" * 60)
    log.info("Extra Trees (real-features) on Jan-Feb 2026 Đà Nẵng hold-out:")
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

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORT_DIR / "holdout_eval.json"
    out_path.write_text(
        json.dumps(
            {
                "window": {"start": args.start, "end": args.end},
                "bbox_name": args.bbox,
                "bbox": list(bbox),
                "max_link_km": args.max_link_km,
                "feature_mode": "real-features (DEM + OSM landuse lookup via compute_link_features)",
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
