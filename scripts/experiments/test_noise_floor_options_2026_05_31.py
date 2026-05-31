"""Test fix #3: so sánh các option noise floor trên 337 row holdout.

Phương pháp:
  1. Load 337 holdout (Jan-Feb 2026, Đà Nẵng, SF12 only).
  2. Stage 1 predict per row (P.1812+DSM, no P.2108 — production sau fix #1).
  3. Stage 2 XGB v0.6 batch-predict residual.
  4. final_predicted_ul_rssi = stage1_ul_rssi + residual.
  5. Per option, predicted_snr = final_rssi - NF_option.
  6. Compare bias/RMSE vs measured gateway SNR.
  7. Count classify() changes (status: STRONG/MARGINAL/WEAK/NO_COVERAGE).

Options:
  - CURRENT: NF = -117 (global constant)
  - A: NF = -104 (median observed from train window)
  - B: NF = per-gateway (computed from train window Nov-Dec 2025, leak-free)
  - C: NF = -104 (same as A for UL — DL would differ but we only have UL data)

NF per-gateway từ train window:
  7276ff002e0507da: -104.77 (n=606)
  7276ff002e06029f: -103.44 (n=197)
  7276ff002e061f5b: -99.29  (n=2014)
  7276ff002e062cf2: -105.13 (n=1359)
  a840411eebb44150: -100.39 (n=70)
  a84041ffff1ec39f: -98.94  (n=104)
  ac1f09fffe00ab25: -110.62 (n=111)
  ac1f09fffe0fd629: -106.71 (n=4735)

Gateway nào không có trong table → fallback NF = -104 (Option A default).
"""

from __future__ import annotations

import json
import logging
import math
import os
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_API_SRC = _REPO_ROOT / "services" / "api-service" / "src"
if str(_API_SRC) not in sys.path:
    sys.path.insert(0, str(_API_SRC))

log = logging.getLogger(__name__)


# Inferred từ train window Nov-Dec 2025 only (leak-free)
PER_GW_NF: dict[str, float] = {
    "7276ff002e0507da": -104.77,
    "7276ff002e06029f": -103.44,
    "7276ff002e061f5b": -99.29,
    "7276ff002e062cf2": -105.13,
    "a840411eebb44150": -100.39,
    "a84041ffff1ec39f": -98.94,
    "ac1f09fffe00ab25": -110.62,
    "ac1f09fffe0fd629": -106.71,
}
PER_GW_NF_FALLBACK = -104.0  # median fallback for unseen gateways

# Constants từ path_loss.py
SF_SNR_LIMITS = {7: -7.5, 8: -10.0, 9: -12.5, 10: -15.0, 11: -17.5, 12: -20.0}


def classify(rssi_dbm: float, snr_db: float, sf: int) -> str:
    """Copy of classify() từ path_loss.py để tránh phụ thuộc."""
    sf_limit = SF_SNR_LIMITS[sf]
    if rssi_dbm >= -100.0 and snr_db >= 5.0:
        return "STRONG"
    if snr_db >= sf_limit and rssi_dbm >= -120.0:
        return "MARGINAL" if snr_db < 5.0 else "STRONG"
    if snr_db >= SF_SNR_LIMITS[12]:
        return "WEAK"
    return "NO_COVERAGE"


def recommend_sf(snr_db: float) -> int:
    for sf in (7, 8, 9, 10, 11, 12):
        if snr_db >= SF_SNR_LIMITS[sf] + 3.0:
            return sf
    return 12


@dataclass(frozen=True, slots=True)
class _Bucket:
    name: str
    n: int
    bias_db: float
    sigma_db: float
    rmse_db: float
    mae_db: float


def _stats(arr: np.ndarray, name: str) -> _Bucket:
    if arr.size == 0:
        return _Bucket(name=name, n=0, bias_db=0.0, sigma_db=0.0, rmse_db=0.0, mae_db=0.0)
    return _Bucket(
        name=name,
        n=int(arr.size),
        bias_db=float(np.mean(arr)),
        sigma_db=float(np.std(arr, ddof=1)) if arr.size > 1 else 0.0,
        rmse_db=float(np.sqrt(np.mean(arr**2))),
        mae_db=float(np.mean(np.abs(arr))),
    )


def _fetch_holdout(db_url: str):
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
        FROM ts.survey_training t JOIN geo.gateways gw ON gw.id = t.serving_gateway_id
        WHERE t.timestamp >= '2026-01-01'::date AND t.timestamp <= '2026-02-28'::date
          AND ST_Y(t.location::geometry) BETWEEN 15.8 AND 16.3
          AND ST_X(t.location::geometry) BETWEEN 107.9 AND 108.5
          AND t.serving_gateway_id IS NOT NULL
          AND t.snr_db IS NOT NULL AND t.rssi_dbm IS NOT NULL
    """
    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchall()


def _haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s — %(message)s")

    import joblib
    import pandas as pd
    from lora_coverage_api.application.itu.backend import GeoPoint, LinkGeometry
    from lora_coverage_api.infrastructure.itu.crc_covlib_backend import CrcCovlibBackend

    db_url = os.environ["LORA_DB_URL"]
    dem_directory = Path(os.environ["LORA_DEM_DIRECTORY"])
    surf = os.environ["LORA_SURFACE_DEM_DIRECTORY"]
    surface_dem_directory = Path(surf)
    model_path = Path(
        os.environ.get("LORA_ML_MODEL_PATH", "services/ml-service/data/stage2_xgb.joblib")
    )

    backend = CrcCovlibBackend(
        dem_directory=dem_directory,
        surface_dem_directory=surface_dem_directory,
        model_version="nf-test",
    )

    log.info("Loading Stage 2 model from %s", model_path)
    model = joblib.load(model_path)

    rows = _fetch_holdout(db_url)
    log.info("Fetched %d holdout rows (Jan-Feb 2026, SF12 only)", len(rows))

    DEVICE_TX_POWER_DBM = 14.0
    DEVICE_TX_GAIN_DBI = 2.15

    # Pre-compute Stage 1 + features for all rows
    stage1_rssi_list: list[float] = []
    feats: list[dict] = []
    meta: list[dict] = []
    n_errors = 0

    for i, r in enumerate(rows):
        try:
            tgt_lat, tgt_lon = float(r[1]), float(r[2])
            measured_rssi = float(r[3])
            measured_snr = float(r[4])
            sf = int(r[5])
            gw_code = str(r[7])
            gw_alt = float(r[9])
            gw_ant_h = float(r[10])
            gw_gain = float(r[11])
            freq = float(r[13])
            gw_lat, gw_lon = float(r[14]), float(r[15])

            link = LinkGeometry(
                tx=GeoPoint(gw_lat, gw_lon),
                rx=GeoPoint(tgt_lat, tgt_lon),
                tx_antenna_height_m=gw_ant_h,
                rx_antenna_height_m=1.5,
                freq_mhz=freq,
            )
            pl_db = backend.basic_transmission_loss_db(link)
            ul_rssi = DEVICE_TX_POWER_DBM + DEVICE_TX_GAIN_DBI + gw_gain - pl_db
            stage1_rssi_list.append(ul_rssi)

            d_km = _haversine_km(tgt_lat, tgt_lon, gw_lat, gw_lon)
            feats.append(
                {
                    "lat": tgt_lat,
                    "lon": tgt_lon,
                    "sf": float(sf),
                    "gw_lat": gw_lat,
                    "gw_lon": gw_lon,
                    "distance_km": d_km,
                    "log_distance_km": math.log1p(d_km),
                    "delta_alt_m": gw_alt + gw_ant_h,
                }
            )
            meta.append(
                {
                    "measured_rssi": measured_rssi,
                    "measured_snr": measured_snr,
                    "sf": sf,
                    "gw_code": gw_code,
                    "distance_km": d_km,
                }
            )
            if (i + 1) % 100 == 0:
                log.info("  ... Stage 1 %d/%d", i + 1, len(rows))
        except Exception as e:
            n_errors += 1
            if n_errors <= 3:
                log.warning("Row error: %r", e)

    # Stage 2 batch predict
    feat_cols = [
        "lat",
        "lon",
        "sf",
        "gw_lat",
        "gw_lon",
        "distance_km",
        "log_distance_km",
        "delta_alt_m",
    ]
    df = pd.DataFrame(feats)[feat_cols]
    residuals = model.predict(df)
    log.info(
        "Stage 2 residual stats: mean=%+.2f std=%.2f min=%+.2f max=%+.2f",
        residuals.mean(),
        residuals.std(),
        residuals.min(),
        residuals.max(),
    )

    # Final predicted RSSI
    s1 = np.asarray(stage1_rssi_list)
    final_rssi = s1 + residuals
    measured_rssi_arr = np.asarray([m["measured_rssi"] for m in meta])
    measured_snr_arr = np.asarray([m["measured_snr"] for m in meta])
    sf_arr = np.asarray([m["sf"] for m in meta])
    gw_codes = [m["gw_code"] for m in meta]

    # Sanity: RSSI bias post-fix#1 + v0.6 should be near zero
    rssi_bias = measured_rssi_arr - final_rssi
    log.info(
        "RSSI bias check: mean=%+.2f std=%.2f RMSE=%.2f",
        rssi_bias.mean(),
        rssi_bias.std(ddof=1),
        np.sqrt((rssi_bias**2).mean()),
    )

    # Compute predicted SNR for each option
    nf_options: dict[str, np.ndarray] = {
        "CURRENT (-117)": np.full_like(final_rssi, -117.0),
        "A (-104 global)": np.full_like(final_rssi, -104.0),
        "B (per-gateway)": np.array([PER_GW_NF.get(c, PER_GW_NF_FALLBACK) for c in gw_codes]),
        "C (-104 UL only)": np.full_like(final_rssi, -104.0),  # same as A for UL holdout
    }

    # Also: bias per gateway code to inspect spread
    print("\n=== SNR comparison vs measured (UL gateway SNR) ===\n")
    results = {}
    for name, nf_arr in nf_options.items():
        pred_snr = final_rssi - nf_arr  # snr = rssi - noise_floor (NF in dBm, snr = rssi + |NF|)
        diff = measured_snr_arr - pred_snr  # residual_snr
        overall = _stats(diff, name)
        results[name] = asdict(overall)
        print(
            f"  {name:<22s}  bias={overall.bias_db:+6.2f}  std={overall.sigma_db:5.2f}  "
            f"RMSE={overall.rmse_db:5.2f}  MAE={overall.mae_db:5.2f}"
        )

    # Classify status counts per option
    print("\n=== classify() status distribution (CURRENT vs OPTION B per-gw) ===")
    cur_statuses = []
    optB_statuses = []
    optA_statuses = []
    meas_status_proxy = []  # baseline using measured rssi & snr
    for i in range(len(final_rssi)):
        sf = int(sf_arr[i])
        cur_statuses.append(classify(final_rssi[i], final_rssi[i] - (-117.0), sf))
        optA_statuses.append(classify(final_rssi[i], final_rssi[i] - (-104.0), sf))
        nfb = PER_GW_NF.get(gw_codes[i], PER_GW_NF_FALLBACK)
        optB_statuses.append(classify(final_rssi[i], final_rssi[i] - nfb, sf))
        meas_status_proxy.append(classify(measured_rssi_arr[i], measured_snr_arr[i], sf))

    def _dist(lst):
        return dict(Counter(lst))

    print(f"  CURRENT (-117): {_dist(cur_statuses)}")
    print(f"  A (-104 global): {_dist(optA_statuses)}")
    print(f"  B (per-gateway): {_dist(optB_statuses)}")
    print(f"  TRUTH (measured): {_dist(meas_status_proxy)}")

    # Accuracy vs truth
    def _accuracy(pred, truth):
        return sum(1 for p, t in zip(pred, truth, strict=True) if p == t) / len(pred)

    print("\n  Classification accuracy vs measured:")
    print(f"    CURRENT:       {_accuracy(cur_statuses, meas_status_proxy) * 100:5.1f}%")
    print(f"    A (-104):      {_accuracy(optA_statuses, meas_status_proxy) * 100:5.1f}%")
    print(f"    B (per-gw):    {_accuracy(optB_statuses, meas_status_proxy) * 100:5.1f}%")

    # recommend_sf comparison
    print("\n=== recommend_sf() distribution ===")
    cur_sfs = [recommend_sf(final_rssi[i] - (-117.0)) for i in range(len(final_rssi))]
    optA_sfs = [recommend_sf(final_rssi[i] - (-104.0)) for i in range(len(final_rssi))]
    optB_sfs = [
        recommend_sf(final_rssi[i] - PER_GW_NF.get(gw_codes[i], PER_GW_NF_FALLBACK))
        for i in range(len(final_rssi))
    ]
    truth_sfs = [recommend_sf(measured_snr_arr[i]) for i in range(len(final_rssi))]
    print(f"  CURRENT:       {_dist(cur_sfs)}")
    print(f"  A (-104):      {_dist(optA_sfs)}")
    print(f"  B (per-gw):    {_dist(optB_sfs)}")
    print(f"  TRUTH:         {_dist(truth_sfs)}")
    print("  recommend_sf accuracy:")
    print(f"    CURRENT:       {_accuracy(cur_sfs, truth_sfs) * 100:5.1f}%")
    print(f"    A (-104):      {_accuracy(optA_sfs, truth_sfs) * 100:5.1f}%")
    print(f"    B (per-gw):    {_accuracy(optB_sfs, truth_sfs) * 100:5.1f}%")

    # JSON summary
    print("\n=== JSON summary ===")
    summary = {
        "n_samples": len(final_rssi),
        "rssi_bias_check": {
            "mean": float(rssi_bias.mean()),
            "rmse": float(np.sqrt((rssi_bias**2).mean())),
        },
        "stage2_residual": {
            "mean": float(residuals.mean()),
            "min": float(residuals.min()),
            "max": float(residuals.max()),
        },
        "snr_bias_by_option": results,
        "classify_accuracy_pct": {
            "current": _accuracy(cur_statuses, meas_status_proxy) * 100,
            "A_global_104": _accuracy(optA_statuses, meas_status_proxy) * 100,
            "B_per_gw": _accuracy(optB_statuses, meas_status_proxy) * 100,
        },
        "recommend_sf_accuracy_pct": {
            "current": _accuracy(cur_sfs, truth_sfs) * 100,
            "A_global_104": _accuracy(optA_sfs, truth_sfs) * 100,
            "B_per_gw": _accuracy(optB_sfs, truth_sfs) * 100,
        },
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
