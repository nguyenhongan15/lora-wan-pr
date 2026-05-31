"""Stage1-only vs Stage1+Stage2 vs measured RSSI — per-survey-point eval.

For each row in ts.survey_training (Đà Nẵng, d<50km, with valid serving_gateway):
  * Compute Stage 1 RSSI using ITU-R P.1812 + DSM (crc-covlib backend).
  * Apply Stage 2 XGBoost residual clipped ±15 dB on top.
  * Compare both predicted RSSI series to measured rssi_dbm.

Aggregate bias / MAE / RMSE by distance bin to localise which stage causes
under-prediction at long range (>5 km), which we observe on the composite map.

Run inside lora-wan-api container (DEM + crc-covlib + xgboost available).
"""

from __future__ import annotations

import math
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path("/app")
sys.path.insert(0, str(REPO_ROOT / "services" / "api-service" / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import psycopg  # noqa: E402

# ── crc-covlib setup (per gateway) ───────────────────────────────────────
DEM_DIR = os.environ.get("LORA_DEM_DIRECTORY", "/data/dem")
SURFACE_DEM_DIR = os.environ.get("LORA_SURFACE_DEM_DIRECTORY", "/data/dsm")
STAGE2_MODEL = Path(os.environ.get("STAGE2_MODEL", "/tmp/stage2_xgb.joblib"))

DEVICE_TX_DBM = 14.0
DEVICE_TX_GAIN = 0.0
DEVICE_HEIGHT_M = 1.5
RESIDUAL_CLIP_DB = 15.0


@dataclass(frozen=True)
class GwConfig:
    code: str
    lat: float
    lon: float
    altitude_m: float
    ant_height_m: float
    rx_gain_dbi: float
    tx_power_dbm: float
    freq_mhz: float


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _build_sim(gw: GwConfig) -> Any:
    from crc_covlib import simulation as covlib  # type: ignore[import-untyped]

    eirp_dbm = gw.tx_power_dbm + 2.15
    eirp_w = 10.0 ** ((eirp_dbm - 30.0) / 10.0)
    sim = covlib.Simulation()
    sim.SetTransmitterLocation(gw.lat, gw.lon)
    sim.SetTransmitterHeight(gw.ant_height_m)
    sim.SetTransmitterFrequency(gw.freq_mhz)
    sim.SetTransmitterPower(eirp_w, covlib.PowerType.EIRP)
    sim.SetReceiverHeightAboveGround(DEVICE_HEIGHT_M)
    sim.SetPropagationModel(covlib.PropagationModel.ITU_R_P_1812)
    sim.SetITURP1812TimePercentage(50.0)
    sim.SetITURP1812LocationPercentage(50.0)
    sim.SetITURP1812SurfaceProfileMethod(
        covlib.P1812SurfaceProfileMethod.P1812_USE_SURFACE_ELEV_DATA
    )
    sim.SetPrimaryTerrainElevDataSource(covlib.TerrainElevDataSource.TERR_ELEV_GEOTIFF)
    sim.SetTerrainElevDataSourceDirectory(covlib.TerrainElevDataSource.TERR_ELEV_GEOTIFF, DEM_DIR)
    sim.SetPrimarySurfaceElevDataSource(covlib.SurfaceElevDataSource.SURF_ELEV_GEOTIFF)
    sim.SetSurfaceElevDataSourceDirectory(
        covlib.SurfaceElevDataSource.SURF_ELEV_GEOTIFF, SURFACE_DEM_DIR
    )
    sim.SetResultType(covlib.ResultType.PATH_LOSS_DB)
    sim.SetTerrainElevDataSamplingResolution(30)
    return sim


SQL = """
WITH gw AS (
  SELECT id, code, ST_X(location::geometry) AS lon, ST_Y(location::geometry) AS lat,
         altitude_m, antenna_height_m, rx_antenna_gain_dbi, tx_power_dbm, frequency_mhz
  FROM geo.gateways
)
SELECT g.code, g.lat AS gw_lat, g.lon AS gw_lon,
       COALESCE(g.altitude_m, 0.0) AS gw_alt,
       COALESCE(g.antenna_height_m, 10.0) AS gw_h,
       COALESCE(g.rx_antenna_gain_dbi, 3.0) AS gw_rxg,
       COALESCE(g.tx_power_dbm, 14.0) AS gw_tx,
       COALESCE(g.frequency_mhz, 923.0) AS gw_freq,
       ST_Y(s.location::geometry) AS lat,
       ST_X(s.location::geometry) AS lon,
       s.rssi_dbm AS rssi,
       s.spreading_factor AS sf,
       ST_DistanceSphere(
         s.location::geometry,
         ST_SetSRID(ST_MakePoint(g.lon, g.lat), 4326)
       ) / 1000.0 AS d_km
FROM ts.survey_training s
JOIN gw g ON g.id = s.serving_gateway_id
WHERE s.spreading_factor IS NOT NULL
  AND ST_Y(s.location::geometry) BETWEEN 15.8 AND 16.3
  AND ST_X(s.location::geometry) BETWEEN 107.9 AND 108.5
  AND ST_DistanceSphere(
        s.location::geometry,
        ST_SetSRID(ST_MakePoint(g.lon, g.lat), 4326)
      ) / 1000.0 < 50
ORDER BY random()
LIMIT %s;
"""


BINS = [
    ("<0.25km", 0.0, 0.25),
    ("0.25-0.5km", 0.25, 0.50),
    ("0.5-1km", 0.50, 1.00),
    ("1-2km", 1.00, 2.00),
    ("2-5km", 2.00, 5.00),
    ("5-10km", 5.00, 10.0),
    ("10-20km", 10.0, 20.0),
    (">20km", 20.0, 1e9),
]


def _agg(diffs: list[float]) -> dict[str, float] | None:
    if not diffs:
        return None
    arr = np.array(diffs, dtype=np.float64)
    return {
        "n": int(arr.size),
        "mae": float(np.mean(np.abs(arr))),
        "rmse": float(np.sqrt(np.mean(arr * arr))),
        "bias": float(np.mean(arr)),
        "p50": float(np.median(arr)),
    }


def main() -> None:
    n_target = int(os.environ.get("N_SAMPLE", "1500"))
    dsn = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")

    print(f"== Loading {n_target} random survey rows ==")
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(SQL, (n_target,))
        rows = cur.fetchall()
        cols = [d.name for d in cur.description]
    print(f"loaded n={len(rows)}")

    # Group by gateway
    by_gw: dict[str, list[dict]] = {}
    gw_cfg: dict[str, GwConfig] = {}
    for r in rows:
        d = dict(zip(cols, r, strict=True))
        code = d["code"]
        by_gw.setdefault(code, []).append(d)
        if code not in gw_cfg:
            gw_cfg[code] = GwConfig(
                code=code,
                lat=float(d["gw_lat"]),
                lon=float(d["gw_lon"]),
                altitude_m=float(d["gw_alt"]),
                ant_height_m=float(d["gw_h"]),
                rx_gain_dbi=float(d["gw_rxg"]),
                tx_power_dbm=float(d["gw_tx"]),
                freq_mhz=float(d["gw_freq"]),
            )

    import joblib

    print(f"== Loading Stage 2 model: {STAGE2_MODEL}")
    model = joblib.load(STAGE2_MODEL)

    stage1_pred: list[float] = []
    stage2_pred: list[float] = []
    measured: list[float] = []
    distances: list[float] = []

    t0 = time.time()
    n_done = 0
    for code, items in by_gw.items():
        gw = gw_cfg[code]
        try:
            sim = _build_sim(gw)
        except Exception as exc:
            print(f"[{code}] build_sim fail: {exc}")
            continue

        # Build features per row, predict Stage 1 PL, then Stage 2 residual
        feats: list[list[float]] = []
        s1_rssi_per_row: list[float] = []
        meas_per_row: list[float] = []
        d_per_row: list[float] = []

        for r in items:
            lat = float(r["lat"])
            lon = float(r["lon"])
            sf = int(r["sf"])
            d_km = float(r["d_km"])
            rssi = float(r["rssi"])
            try:
                pl = sim.GenerateReceptionPointResult(lat, lon)
            except Exception:
                pl = float("nan")
            if not math.isfinite(pl):
                continue

            s1_ul = DEVICE_TX_DBM + DEVICE_TX_GAIN + gw.rx_gain_dbi - pl
            s1_rssi_per_row.append(s1_ul)
            feats.append(
                [
                    lat,
                    lon,
                    float(sf),
                    gw.lat,
                    gw.lon,
                    d_km,
                    math.log1p(d_km),
                    gw.altitude_m + gw.ant_height_m,
                ]
            )
            meas_per_row.append(rssi)
            d_per_row.append(d_km)

        if not feats:
            continue

        import pandas as pd

        df = pd.DataFrame(
            feats,
            columns=[
                "lat",
                "lon",
                "sf",
                "gw_lat",
                "gw_lon",
                "distance_km",
                "log_distance_km",
                "delta_alt_m",
            ],
        )
        residual = np.asarray(model.predict(df), dtype=np.float64)
        residual_clipped = np.clip(residual, -RESIDUAL_CLIP_DB, RESIDUAL_CLIP_DB)
        s1_arr = np.asarray(s1_rssi_per_row, dtype=np.float64)
        s2_arr = s1_arr + residual_clipped

        stage1_pred.extend(s1_arr.tolist())
        stage2_pred.extend(s2_arr.tolist())
        measured.extend(meas_per_row)
        distances.extend(d_per_row)

        n_done += len(feats)
        elapsed = time.time() - t0
        print(
            f"  [{code}] +{len(feats)} rows, total={n_done}, "
            f"elapsed={elapsed:.1f}s ({elapsed / max(n_done, 1) * 1000:.1f} ms/row)"
        )

    s1 = np.asarray(stage1_pred)
    s2 = np.asarray(stage2_pred)
    meas = np.asarray(measured)
    d = np.asarray(distances)
    d1 = s1 - meas
    d2 = s2 - meas

    print(f"\n== OVERALL (n={len(meas)}) ==")
    print(
        f"  Stage1 : MAE={np.mean(np.abs(d1)):.2f}  RMSE={np.sqrt(np.mean(d1**2)):.2f}  bias={np.mean(d1):+.2f}"
    )
    print(
        f"  Stage2 : MAE={np.mean(np.abs(d2)):.2f}  RMSE={np.sqrt(np.mean(d2**2)):.2f}  bias={np.mean(d2):+.2f}"
    )

    print("\n== PER-DISTANCE BIN ==")
    print(
        f"  {'bin':<12} {'n':>5} {'meas_p50':>9} | {'s1_p50':>7} {'s1_bias':>8} {'s1_rmse':>8} | {'s2_p50':>7} {'s2_bias':>8} {'s2_rmse':>8}"
    )
    for label, lo, hi in BINS:
        m = (d >= lo) & (d < hi)
        n = int(m.sum())
        if n == 0:
            continue
        meas_b = meas[m]
        d1b = d1[m]
        d2b = d2[m]
        s1b = s1[m]
        s2b = s2[m]
        print(
            f"  {label:<12} {n:>5} {np.median(meas_b):>9.1f} | "
            f"{np.median(s1b):>7.1f} {np.mean(d1b):>+8.2f} {np.sqrt(np.mean(d1b**2)):>8.2f} | "
            f"{np.median(s2b):>7.1f} {np.mean(d2b):>+8.2f} {np.sqrt(np.mean(d2b**2)):>8.2f}"
        )

    # Where each prediction would fall in our 4-bin scheme (vs measured)
    def _bin(r: float) -> str:
        if r >= -100:
            return "strong"
        if r >= -110:
            return "good"
        if r >= -120:
            return "marg"
        if r >= -140:
            return "weak"
        return "none"

    from collections import Counter

    cm = Counter(_bin(r) for r in meas)
    c1 = Counter(_bin(r) for r in s1)
    c2 = Counter(_bin(r) for r in s2)
    print("\n== Distribution across visible bins ==")
    print(f"  {'bin':<8} {'meas%':>8} {'stage1%':>8} {'stage2%':>8}")
    for b in ["strong", "good", "marg", "weak", "none"]:
        n_total = len(meas)
        print(
            f"  {b:<8} {cm[b] * 100 / n_total:>7.1f}% {c1[b] * 100 / n_total:>7.1f}% {c2[b] * 100 / n_total:>7.1f}%"
        )


if __name__ == "__main__":
    main()
