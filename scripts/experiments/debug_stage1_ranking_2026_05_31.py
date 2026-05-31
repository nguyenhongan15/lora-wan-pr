"""Debug Stage 1 ranking — tại sao 61% rows best-pick KHÔNG khớp actual_gw?

Cho mỗi hold-out row:
  - Liệt kê top-5 candidate gws (theo distance) + PL + min(UL,DL) margin.
  - Highlight: actual_gw (survey) và best_gw_phy (Stage 1 chọn).
  - Phân loại failure modes.
"""

from __future__ import annotations

import math
import os
from pathlib import Path

import pandas as pd
import psycopg
from lora_coverage_api.application.itu.model import Stage1ItuModel
from lora_coverage_api.application.path_loss import resolve_environment_profile
from lora_coverage_api.domain.coverage import Gateway, GatewayId, Target
from lora_coverage_api.infrastructure.itu.crc_covlib_backend import CrcCovlibBackend


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def main():
    db_url = (os.environ.get("LORA_DB_URL") or os.environ["DATABASE_URL"]).replace(
        "postgresql+psycopg://", "postgresql://"
    )
    backend = CrcCovlibBackend(
        dem_directory=Path(os.environ["LORA_DEM_DIRECTORY"]),
        surface_dem_directory=Path(os.environ["LORA_SURFACE_DEM_DIRECTORY"]),
        model_version="dbg",
        percent_time=50.0,
        percent_location=50.0,
    )
    stage1 = Stage1ItuModel(
        model_version="dbg",
        backend=backend,
        env_profile=resolve_environment_profile("suburban"),
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

    # Mô phỏng find_serving_candidates: nearest 5 within 30km
    diag_rows = []
    for i, r in enumerate(rows):
        if i % 50 == 0:
            print(f"  {i}/{len(rows)}")
        target = Target(
            latitude=float(r["lat"]),
            longitude=float(r["lon"]),
            spreading_factor=int(r["sf"]),
            frequency_mhz=float(r["freq"]),
        )
        actual_gw = gws.get(r["actual_gw_id"])
        if actual_gw is None:
            continue

        all_with_dist = []
        for gw in gws.values():
            d = haversine_km(target.latitude, target.longitude, gw.latitude, gw.longitude)
            if d <= 30.0:
                all_with_dist.append((d, gw))
        all_with_dist.sort(key=lambda x: x[0])
        top5 = all_with_dist[:5]  # mô phỏng limit=5

        d_actual = haversine_km(
            target.latitude, target.longitude, actual_gw.latitude, actual_gw.longitude
        )
        actual_rank_in_all = next(
            (i for i, (_, g) in enumerate(all_with_dist) if g.id == actual_gw.id), -1
        )
        actual_in_top5 = any(g.id == actual_gw.id for _, g in top5)

        # Stage 1 trên top5
        best_gw = None
        best_margin = float("-inf")
        best_pl = None
        best_d = None
        ranking = []
        for d, gw in top5:
            try:
                p = stage1.predict(target, gw)
            except Exception:
                continue
            m = min(p.uplink_margin_db, p.downlink_margin_db)
            ranking.append(
                {
                    "code": gw.code,
                    "d_km": d,
                    "pl_db": p.path_loss_db,
                    "margin": m,
                    "ul_rssi": p.uplink_rssi_dbm,
                }
            )
            if m > best_margin:
                best_margin = m
                best_gw = gw
                best_pl = p.path_loss_db
                best_d = d
        if best_gw is None:
            continue

        diag_rows.append(
            {
                "hid": str(r["hid"]),
                "lat": float(r["lat"]),
                "lon": float(r["lon"]),
                "sf": int(r["sf"]),
                "measured_rssi": float(r["measured_rssi"]),
                "actual_gw": actual_gw.code,
                "actual_d_km": d_actual,
                "actual_rank_dist": actual_rank_in_all,
                "actual_in_top5": actual_in_top5,
                "best_gw": best_gw.code,
                "best_d_km": best_d,
                "best_pl_db": best_pl,
                "match": actual_gw.id == best_gw.id,
                "ranking": "; ".join(
                    f"{x['code'][:8]}(d={x['d_km']:.1f},PL={x['pl_db']:.1f},m={x['margin']:.1f})"
                    for x in ranking
                ),
            }
        )

    df = pd.DataFrame(diag_rows)
    print(f"\nn={len(df)}")
    print(f"match rate: {df['match'].mean():.1%}")
    print(f"actual_in_top5: {df['actual_in_top5'].mean():.1%}")

    # Phân tích actual_rank
    print("\n== Actual_gw rank (theo distance) ==")
    rank_dist = df["actual_rank_dist"].value_counts().sort_index()
    for rk, cnt in rank_dist.items():
        print(f"  rank {rk}: {cnt}")

    # Mismatch failure modes
    mm = df[~df["match"]]
    print(f"\n== Mismatch (n={len(mm)}) ==")
    print(f"  actual NOT in top5: {(~mm['actual_in_top5']).sum()}")
    in_top5_but_lost = mm[mm["actual_in_top5"]]
    print(f"  actual in top5 nhưng thua margin: {len(in_top5_but_lost)}")
    if len(in_top5_but_lost):
        delta_d = in_top5_but_lost["actual_d_km"] - in_top5_but_lost["best_d_km"]
        print(f"    median Δd (actual - best) = {delta_d.median():+.2f} km")
        print(f"    actual luôn xa hơn best? {(delta_d > 0).mean():.1%}")

    # Pathological cases: best_d > 10km
    bad = df[df["best_d_km"] > 10]
    print(f"\n== Pathological best_d > 10km (n={len(bad)}) ==")
    for _, row in bad.head(10).iterrows():
        print(
            f"  hid={row['hid'][:8]} | actual={row['actual_gw'][:8]}(d={row['actual_d_km']:.1f}km) → best={row['best_gw'][:8]}(d={row['best_d_km']:.1f}km, PL={row['best_pl_db']:.1f})"
        )
        print(f"    top5: {row['ranking']}")

    df.to_csv("/tmp/stage1_ranking_debug.csv", index=False)
    print("\nSaved /tmp/stage1_ranking_debug.csv")


if __name__ == "__main__":
    main()
