"""So sánh Stage 1+Stage 2 với 2 cách chọn gateway trên hold-out:
  (A) actual_gw   = gateway nhận packet thực tế (theo survey)
  (B) best_gw_phy = gateway Stage 1 chọn (max min(UL,DL) margin)

Cùng v0.6 joblib. Cùng 337 row hold-out (Jan-Feb 2026, Đà Nẵng).
Mục đích: định lượng gap do gateway-choice mismatch.
"""

from __future__ import annotations

import math
import os
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import psycopg

# lora_coverage_api installed at /install/lib/python3.12/site-packages — already on path
from lora_coverage_api.application.itu.model import Stage1ItuModel
from lora_coverage_api.application.path_loss import resolve_environment_profile
from lora_coverage_api.domain.coverage import Gateway, GatewayId, Target
from lora_coverage_api.infrastructure.itu.crc_covlib_backend import CrcCovlibBackend

TRAINING_FEATURE_COLS = [
    "lat",
    "lon",
    "sf",
    "gw_lat",
    "gw_lon",
    "distance_km",
    "log_distance_km",
    "delta_alt_m",
]


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def build_features(target, gw):
    d = haversine_km(target.latitude, target.longitude, gw.latitude, gw.longitude)
    return {
        "lat": target.latitude,
        "lon": target.longitude,
        "sf": float(target.spreading_factor),
        "gw_lat": gw.latitude,
        "gw_lon": gw.longitude,
        "distance_km": d,
        "log_distance_km": math.log1p(d),
        "delta_alt_m": gw.altitude_m + gw.antenna_height_m,
    }


def gw_from_row(r):
    return Gateway(
        id=GatewayId(r["gw_id"]),
        code=r["gw_code"],
        name=r["gw_name"],
        latitude=float(r["gw_lat"]),
        longitude=float(r["gw_lon"]),
        altitude_m=float(r["gw_alt"]),
        antenna_height_m=float(r["gw_ant_h"]),
        antenna_gain_dbi=float(r["gw_gain"]),
        tx_power_dbm=float(r["gw_tx"]),
        frequency_mhz=float(r["gw_freq"]),
        rx_antenna_gain_dbi=float(r["gw_rx_gain"]) if r["gw_rx_gain"] is not None else None,
        rx_sensitivity_dbm=float(r["gw_rx_sens"]) if r["gw_rx_sens"] is not None else None,
        noise_floor_dbm=float(r["gw_nf"]) if r["gw_nf"] is not None else None,
    )


def main():
    db_url = (os.environ.get("LORA_DB_URL") or os.environ["DATABASE_URL"]).replace(
        "postgresql+psycopg://", "postgresql://"
    )
    joblib_path = "/tmp/stage2_xgb.joblib"
    model = joblib.load(joblib_path)
    print(f"Loaded {joblib_path}")

    dem_dir = Path(os.environ["LORA_DEM_DIRECTORY"])
    surf_raw = os.environ.get("LORA_SURFACE_DEM_DIRECTORY", "")
    surf_dir = Path(surf_raw) if surf_raw else None
    backend = CrcCovlibBackend(
        dem_directory=dem_dir,
        surface_dem_directory=surf_dir,
        model_version="eval-actual-vs-best",
        percent_time=float(os.environ.get("LORA_ITU_PERCENT_TIME", "50")),
        percent_location=float(os.environ.get("LORA_ITU_PERCENT_LOCATION", "50")),
    )
    stage1 = Stage1ItuModel(
        model_version="eval-actual-vs-best",
        backend=backend,
        env_profile=resolve_environment_profile(os.environ.get("LORA_ENV_PROFILE", "suburban")),
    )

    sql_holdout = """
        SELECT t.id AS hid, t.timestamp,
               ST_Y(t.location::geometry) AS lat, ST_X(t.location::geometry) AS lon,
               t.rssi_dbm AS measured_rssi, t.spreading_factor AS sf, t.frequency_mhz AS freq,
               t.serving_gateway_id AS actual_gw_id
        FROM ts.survey_training t
        WHERE t.timestamp >= '2026-01-01' AND t.timestamp < '2026-03-01'
          AND t.serving_gateway_id IS NOT NULL
          AND ST_Y(t.location::geometry) BETWEEN 15.9 AND 16.2
          AND ST_X(t.location::geometry) BETWEEN 108.0 AND 108.4
    """

    sql_gw = """
        SELECT id, code, name, ST_Y(location::geometry) AS lat,
               ST_X(location::geometry) AS lon, altitude_m, antenna_height_m,
               antenna_gain_dbi, tx_power_dbm, frequency_mhz,
               rx_antenna_gain_dbi, rx_sensitivity_dbm, noise_floor_dbm
        FROM geo.gateways WHERE is_public = true
    """

    with psycopg.connect(db_url) as conn:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(sql_gw)
            gw_rows = cur.fetchall()
            cur.execute(sql_holdout)
            rows = cur.fetchall()

    gws = {}
    for g in gw_rows:
        gws[g["id"]] = Gateway(
            id=GatewayId(g["id"]),
            code=g["code"],
            name=g["name"],
            latitude=float(g["lat"]),
            longitude=float(g["lon"]),
            altitude_m=float(g["altitude_m"]),
            antenna_height_m=float(g["antenna_height_m"]),
            antenna_gain_dbi=float(g["antenna_gain_dbi"]),
            tx_power_dbm=float(g["tx_power_dbm"]),
            frequency_mhz=float(g["frequency_mhz"]),
            rx_antenna_gain_dbi=float(g["rx_antenna_gain_dbi"])
            if g["rx_antenna_gain_dbi"] is not None
            else None,
            rx_sensitivity_dbm=float(g["rx_sensitivity_dbm"])
            if g["rx_sensitivity_dbm"] is not None
            else None,
            noise_floor_dbm=float(g["noise_floor_dbm"])
            if g["noise_floor_dbm"] is not None
            else None,
        )
    print(f"Loaded {len(gws)} gateways, {len(rows)} hold-out rows")

    # Per-row eval
    results = []
    for i, r in enumerate(rows):
        if i % 25 == 0:
            print(f"  {i}/{len(rows)}")
        target = Target(
            latitude=float(r["lat"]),
            longitude=float(r["lon"]),
            spreading_factor=int(r["sf"]),
            frequency_mhz=float(r["freq"]),
        )
        measured = float(r["measured_rssi"])
        actual_gw = gws.get(r["actual_gw_id"])
        if actual_gw is None:
            continue

        # Tìm best_gw_phy: predict trên mọi gw < 30km, chọn max(min(UL,DL margin))
        candidates = [
            g
            for g in gws.values()
            if haversine_km(target.latitude, target.longitude, g.latitude, g.longitude) < 30.0
        ]
        best_gw = None
        best_margin = float("-inf")
        best_pred = None
        for g in candidates:
            try:
                p = stage1.predict(target, g)
            except Exception:
                continue
            m = min(p.uplink_margin_db, p.downlink_margin_db)
            if m > best_margin:
                best_margin = m
                best_gw = g
                best_pred = p
        if best_gw is None:
            continue

        # Stage 1 predict cho actual_gw
        try:
            actual_pred = stage1.predict(target, actual_gw)
        except Exception:
            continue

        # Stage 2 residual
        feat_actual = pd.DataFrame([build_features(target, actual_gw)])[TRAINING_FEATURE_COLS]
        feat_best = pd.DataFrame([build_features(target, best_gw)])[TRAINING_FEATURE_COLS]
        res_actual = float(model.predict(feat_actual)[0])
        res_best = float(model.predict(feat_best)[0])

        final_actual = actual_pred.uplink_rssi_dbm + res_actual
        final_best = best_pred.uplink_rssi_dbm + res_best
        d_actual_km = haversine_km(
            target.latitude, target.longitude, actual_gw.latitude, actual_gw.longitude
        )
        d_best_km = haversine_km(
            target.latitude, target.longitude, best_gw.latitude, best_gw.longitude
        )

        results.append(
            {
                "measured": measured,
                "final_actual": final_actual,
                "final_best": final_best,
                "stage1_actual": actual_pred.uplink_rssi_dbm,
                "stage1_best": best_pred.uplink_rssi_dbm,
                "res_actual": res_actual,
                "res_best": res_best,
                "actual_gw": actual_gw.code,
                "best_gw": best_gw.code,
                "match": actual_gw.id == best_gw.id,
                "d_actual_km": d_actual_km,
                "d_best_km": d_best_km,
                "sf": int(r["sf"]),
            }
        )

    df = pd.DataFrame(results)
    print(f"\nn={len(df)}, match_rate={df['match'].mean():.1%}")

    for label, col in [
        ("ACTUAL_GW (Option 3)", "final_actual"),
        ("BEST_GW_PHY (API current)", "final_best"),
    ]:
        err = df[col] - df["measured"]
        print(f"\n== {label} ==")
        print(f"  bias = {err.mean():+.2f} dB")
        print(f"  RMSE = {np.sqrt((err**2).mean()):.2f} dB")
        print(f"  MAE  = {err.abs().mean():.2f} dB")

    # Per-bin (theo d_actual_km cho ACTUAL, d_best_km cho BEST)
    print("\n== Per distance bin ==")
    bins = [(0, 2, "<2km"), (2, 5, "2-5km"), (5, 10, "5-10km"), (10, 50, "10-50km")]
    for lo, hi, lbl in bins:
        m_act = (df["d_actual_km"] >= lo) & (df["d_actual_km"] < hi)
        m_best = (df["d_best_km"] >= lo) & (df["d_best_km"] < hi)
        if m_act.sum() == 0 and m_best.sum() == 0:
            continue
        e_act = df.loc[m_act, "final_actual"] - df.loc[m_act, "measured"]
        e_best = df.loc[m_best, "final_best"] - df.loc[m_best, "measured"]
        print(
            f"  {lbl:>8s}: ACTUAL n={m_act.sum():3d} bias={e_act.mean():+.2f} RMSE={np.sqrt((e_act**2).mean()):.2f}"
            f"  | BEST n={m_best.sum():3d} bias={e_best.mean():+.2f} RMSE={np.sqrt((e_best**2).mean()):.2f}"
        )

    # Mismatch slice
    mm = df[~df["match"]]
    print(f"\n== Mismatch only (n={len(mm)}) ==")
    for label, col in [("ACTUAL_GW", "final_actual"), ("BEST_GW_PHY", "final_best")]:
        err = mm[col] - mm["measured"]
        print(f"  {label}: bias={err.mean():+.2f} RMSE={np.sqrt((err**2).mean()):.2f}")

    df.to_csv("/tmp/eval_actual_vs_best.csv", index=False)
    print("\nCSV saved /tmp/eval_actual_vs_best.csv")


if __name__ == "__main__":
    main()
