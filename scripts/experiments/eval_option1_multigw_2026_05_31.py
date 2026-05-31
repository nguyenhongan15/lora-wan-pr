"""Option 1 simulation: với data hiện tại (~9% multi-gw packets), kiểm tra:

1. Bao nhiêu packet hold-out được ≥2 gateway nhận (multi-gw observation).
2. Trong số đó, Stage 1 best-pick có rơi trúng 1 gw đã nhận packet?
3. Nếu trúng → so sánh predict(best_gw) với measured RSSI ở chính best_gw đó.
   → đây là "Option 1 ideal" — train+serve cùng (point, gw) semantics.

So sánh với ACTUAL_GW (single-gw label hiện có).
"""

from __future__ import annotations

import math
import os
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import psycopg
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


def main():
    db_url = (os.environ.get("LORA_DB_URL") or os.environ["DATABASE_URL"]).replace(
        "postgresql+psycopg://", "postgresql://"
    )
    model = joblib.load("/tmp/stage2_xgb.joblib")

    backend = CrcCovlibBackend(
        dem_directory=Path(os.environ["LORA_DEM_DIRECTORY"]),
        surface_dem_directory=Path(os.environ["LORA_SURFACE_DEM_DIRECTORY"]),
        model_version="opt1",
        percent_time=50.0,
        percent_location=50.0,
    )
    stage1 = Stage1ItuModel(
        model_version="opt1",
        backend=backend,
        env_profile=resolve_environment_profile("suburban"),
    )

    # Bước 1: GROUP rows theo (timestamp, location) → tìm packet multi-gw
    sql_groups = """
        SELECT
            t.timestamp,
            ST_AsText(t.location::geometry) AS loc_key,
            ST_Y(t.location::geometry) AS lat,
            ST_X(t.location::geometry) AS lon,
            t.spreading_factor AS sf, t.frequency_mhz AS freq,
            ARRAY_AGG(t.serving_gateway_id) AS gw_ids,
            ARRAY_AGG(t.rssi_dbm) AS rssi_list,
            COUNT(*) AS n_obs
        FROM ts.survey_training t
        WHERE t.timestamp >= '2026-01-01' AND t.timestamp < '2026-03-01'
          AND t.serving_gateway_id IS NOT NULL
          AND ST_Y(t.location::geometry) BETWEEN 15.9 AND 16.2
          AND ST_X(t.location::geometry) BETWEEN 108.0 AND 108.4
        GROUP BY t.timestamp, t.location, t.spreading_factor, t.frequency_mhz
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
            cur.execute(sql_groups)
            groups = cur.fetchall()

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

    print(f"hold-out packets={len(groups)} ({len(gws)} gateway pool)")

    n_obs_per_pkt = [g["n_obs"] for g in groups]
    print(f"  single-gw: {sum(1 for n in n_obs_per_pkt if n == 1)}")
    print(f"  multi-gw : {sum(1 for n in n_obs_per_pkt if n >= 2)}")
    print(f"  obs distribution: max={max(n_obs_per_pkt)}, mean={np.mean(n_obs_per_pkt):.2f}")

    # Bước 2: Stage 1 best-pick → đối chiếu với gw_ids observed
    n_best_in_observed = 0
    n_best_outside = 0
    rows_best_in_obs = []
    rows_best_out_obs = []

    for i, g in enumerate(groups):
        if i % 100 == 0:
            print(f"  processed {i}/{len(groups)}")
        target = Target(
            latitude=float(g["lat"]),
            longitude=float(g["lon"]),
            spreading_factor=int(g["sf"]),
            frequency_mhz=float(g["freq"]),
        )
        observed_gw_ids = set(g["gw_ids"])
        observed_rssi = dict(zip(g["gw_ids"], g["rssi_list"], strict=True))

        # Stage 1 best-pick từ ALL candidate (≤30km)
        best_gw = None
        best_margin = float("-inf")
        best_pred = None
        for gw in gws.values():
            d = haversine_km(target.latitude, target.longitude, gw.latitude, gw.longitude)
            if d > 30.0:
                continue
            try:
                p = stage1.predict(target, gw)
            except Exception:
                continue
            m = min(p.uplink_margin_db, p.downlink_margin_db)
            if m > best_margin:
                best_margin = m
                best_gw = gw
                best_pred = p
        if best_gw is None:
            continue

        feat = pd.DataFrame([build_features(target, best_gw)])[TRAINING_FEATURE_COLS]
        residual = float(model.predict(feat)[0])
        final = best_pred.uplink_rssi_dbm + residual

        if best_gw.id in observed_gw_ids:
            n_best_in_observed += 1
            measured_at_best = float(observed_rssi[best_gw.id])
            rows_best_in_obs.append(
                {
                    "measured": measured_at_best,
                    "final": final,
                    "best_gw": best_gw.code,
                    "n_obs": int(g["n_obs"]),
                }
            )
        else:
            n_best_outside += 1
            # Vẫn tính: so sánh với best-RSSI gw đã nhận (proxy "actual" cho multi-gw)
            best_observed_gw_id = max(observed_rssi, key=observed_rssi.get)
            best_observed_rssi = float(observed_rssi[best_observed_gw_id])
            rows_best_out_obs.append(
                {
                    "measured_at_best_observed": best_observed_rssi,
                    "final_at_phy_best": final,
                    "best_gw_phy": best_gw.code,
                    "n_obs": int(g["n_obs"]),
                }
            )

    print("\n== Stage 1 best-pick coverage ==")
    print(
        f"  IN observed set : {n_best_in_observed} ({100 * n_best_in_observed / (n_best_in_observed + n_best_outside):.1f}%)"
    )
    print(f"  OUTSIDE         : {n_best_outside}")

    df_in = pd.DataFrame(rows_best_in_obs)
    if len(df_in):
        err = df_in["final"] - df_in["measured"]
        print(f"\n== Option 1 IDEAL (best_phy ∈ observed gws, n={len(df_in)}) ==")
        print(f"  bias = {err.mean():+.2f} dB")
        print(f"  RMSE = {np.sqrt((err**2).mean()):.2f} dB")
        print(f"  MAE  = {err.abs().mean():.2f} dB")

        # Theo n_obs
        for n_min in [1, 2, 3]:
            sub = df_in[df_in["n_obs"] >= n_min]
            if len(sub) == 0:
                continue
            e = sub["final"] - sub["measured"]
            print(
                f"    n_obs>={n_min}: n={len(sub)} bias={e.mean():+.2f} RMSE={np.sqrt((e**2).mean()):.2f}"
            )

    df_out = pd.DataFrame(rows_best_out_obs)
    if len(df_out):
        err = df_out["final_at_phy_best"] - df_out["measured_at_best_observed"]
        print(
            f"\n== Best_phy KHÔNG trong observed (n={len(df_out)}) — compare với best_observed_rssi =="
        )
        print(f"  bias = {err.mean():+.2f} dB")
        print(f"  RMSE = {np.sqrt((err**2).mean()):.2f} dB")

    df_in.to_csv("/tmp/eval_option1_in_obs.csv", index=False)
    df_out.to_csv("/tmp/eval_option1_out_obs.csv", index=False)
    print("\nCSV saved")


if __name__ == "__main__":
    main()
