"""Test ALL fix options (D/E/F/G) vs production. Phase 1 per-point + Phase 2 grid (3 gws).

Configs:
  - current_DSM         : production (DSM, loc%=10, no residual clip, no PL cap)
  - E25/E35/E45         : current + cap PL @ FSL_freespace + N dB
  - F_DTM               : skip surface DEM (DTM only)
  - G_clip5/10          : symmetric residual clip ±5 / ±10 dB
  - G_asym3 / asym5     : asymmetric residual floor (allow large + boost, limit pull-down)
  - D5/D7               : median filter 5x5 / 7x7 trên PL grid (Phase 2 only)

Phase 2: chạy trên 3 gateway (1 outdoor LOS, 1 outdoor poor coverage, 1 indoor) để bao quát.
"""

from __future__ import annotations

import math
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import psycopg

REPO_ROOT = Path("/app")
sys.path.insert(0, str(REPO_ROOT / "services" / "api-service" / "src"))

DEM_DIR = os.environ.get("LORA_DEM_DIRECTORY", "/data/dem")
SURFACE_DEM_DIR = os.environ.get("LORA_SURFACE_DEM_DIRECTORY", "/data/dem-surface")
STAGE2_MODEL = Path(os.environ.get("STAGE2_MODEL", "/tmp/stage2_xgb.joblib"))

DEVICE_TX_DBM = 14.0
DEVICE_TX_GAIN = 0.0
DEVICE_HEIGHT_M = 1.5
LOC_PCT = 10.0
N_SAMPLES = 500
FREQ_MHZ = 923.0


def _haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def fsl_db(d_km, f_mhz=FREQ_MHZ):
    if d_km < 0.001:
        d_km = 0.001
    return 20 * math.log10(d_km) + 20 * math.log10(f_mhz) + 32.45


def build_sim(gw_row, loc_pct, use_dsm: bool):
    from crc_covlib import simulation as covlib

    _code, lat, lon, _ant_g, tx, h, _alt, freq = gw_row
    eirp_dbm = float(tx) + 2.15
    eirp_w = 10.0 ** ((eirp_dbm - 30.0) / 10.0)
    sim = covlib.Simulation()
    sim.SetTransmitterLocation(float(lat), float(lon))
    sim.SetTransmitterHeight(float(h))
    sim.SetTransmitterFrequency(float(freq))
    sim.SetTransmitterPower(eirp_w, covlib.PowerType.EIRP)
    sim.SetReceiverHeightAboveGround(DEVICE_HEIGHT_M)
    sim.SetPropagationModel(covlib.PropagationModel.ITU_R_P_1812)
    sim.SetITURP1812TimePercentage(50.0)
    sim.SetITURP1812LocationPercentage(loc_pct)
    sim.SetPrimaryTerrainElevDataSource(covlib.TerrainElevDataSource.TERR_ELEV_GEOTIFF)
    sim.SetTerrainElevDataSourceDirectory(covlib.TerrainElevDataSource.TERR_ELEV_GEOTIFF, DEM_DIR)
    if use_dsm:
        sim.SetITURP1812SurfaceProfileMethod(
            covlib.P1812SurfaceProfileMethod.P1812_USE_SURFACE_ELEV_DATA
        )
        sim.SetPrimarySurfaceElevDataSource(covlib.SurfaceElevDataSource.SURF_ELEV_GEOTIFF)
        sim.SetSurfaceElevDataSourceDirectory(
            covlib.SurfaceElevDataSource.SURF_ELEV_GEOTIFF, SURFACE_DEM_DIR
        )
    sim.SetResultType(covlib.ResultType.PATH_LOSS_DB)
    sim.SetTerrainElevDataSamplingResolution(30)
    return sim


def load_survey(n=N_SAMPLES):
    dsn = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(dsn) as c, c.cursor() as cur:
        cur.execute(
            """
            SELECT s.id,
                   ST_Y(s.location::geometry) AS lat,
                   ST_X(s.location::geometry) AS lon,
                   s.rssi_dbm, s.spreading_factor AS sf, g.code AS gw_code,
                   ST_Y(g.location::geometry) AS gw_lat,
                   ST_X(g.location::geometry) AS gw_lon,
                   COALESCE(g.antenna_gain_dbi, 5.0) AS gw_rx_gain,
                   COALESCE(g.antenna_height_m, 10.0) AS gw_h,
                   COALESCE(g.altitude_m, 0.0) AS gw_alt,
                   COALESCE(g.tx_power_dbm, 14.0) AS gw_tx,
                   COALESCE(g.frequency_mhz, 923.0) AS gw_freq
            FROM ts.survey_training s
            JOIN geo.gateways g ON g.id = s.serving_gateway_id
            WHERE s.timestamp >= '2026-01-01' AND s.timestamp < '2026-03-01'
              AND s.rssi_dbm IS NOT NULL
              AND ST_DistanceSphere(s.location::geometry, g.location::geometry) < 50000
            ORDER BY random()
            LIMIT %s
        """,
            (n,),
        )
        return cur.fetchall()


def share_bins(rssi_flat):
    v = rssi_flat[np.isfinite(rssi_flat)]
    n = len(v)
    if n == 0:
        return [0.0] * 5
    b1 = int(np.sum(v >= -100))
    b2 = int(np.sum((v >= -110) & (v < -100)))
    b3 = int(np.sum((v >= -120) & (v < -110)))
    b4 = int(np.sum((v >= -140) & (v < -120)))
    b5 = int(np.sum(v < -140))
    return [100 * b1 / n, 100 * b2 / n, 100 * b3 / n, 100 * b4 / n, 100 * b5 / n]


def clip_sym(x, lo_hi):
    return np.clip(x, -lo_hi, lo_hi)


def clip_floor(x, lo, hi=None):
    if hi is None:
        return np.maximum(x, lo)
    return np.clip(x, lo, hi)


def make_predictors():
    """Return dict of (config_name, fn(pl_raw, residual, fsl) -> rssi_pred)."""

    # All configs share: rssi = TX + 0 + rx_gain - pl_eff + residual_eff
    # Currying with rx_gain happens per call; here we just transform pl & residual.
    def _curry(transform_pl, transform_res):
        def f(pl_raw, residual, fsl, rx_gain):
            pl_eff = transform_pl(pl_raw, fsl)
            res_eff = transform_res(residual)
            return DEVICE_TX_DBM + DEVICE_TX_GAIN + rx_gain - pl_eff + res_eff

        return f

    def id_pl(pl, fsl):
        return pl

    def id_res(r):
        return r

    def cap_pl(margin):
        return lambda pl, fsl: np.minimum(pl, fsl + margin)

    def clip_res_sym(v):
        return lambda r: np.clip(r, -v, v)

    def clip_res_floor(lo, hi=None):
        return lambda r: np.clip(r, lo, hi if hi is not None else np.inf)

    cfgs = {
        "current_DSM": _curry(id_pl, id_res),
        "E25_cap+25": _curry(cap_pl(25), id_res),
        "E35_cap+35": _curry(cap_pl(35), id_res),
        "E45_cap+45": _curry(cap_pl(45), id_res),
        "G_clip±5": _curry(id_pl, clip_res_sym(5)),
        "G_clip±10": _curry(id_pl, clip_res_sym(10)),
        "G_asym[-3,+∞)": _curry(id_pl, clip_res_floor(-3.0)),
        "G_asym[-5,+∞)": _curry(id_pl, clip_res_floor(-5.0)),
        "G_asym[-3,+15]": _curry(id_pl, clip_res_floor(-3.0, 15.0)),
        # F handled separately because it uses DTM (different PL)
    }
    return cfgs


def main():
    import joblib
    import pandas as pd

    print(f"== Phase 1: per-survey-point eval (target N={N_SAMPLES}) ==\n")
    rows = load_survey()
    print(f"Loaded {len(rows)} survey rows.\n")
    by_gw = defaultdict(list)
    for r in rows:
        by_gw[r[5]].append(r)
    print(f"Spread over {len(by_gw)} gateways: {list(by_gw.keys())}")

    model = joblib.load(STAGE2_MODEL)
    print(f"Loaded Stage 2 model: {STAGE2_MODEL}\n")

    gw_rows = {}
    for code, plist in by_gw.items():
        s = plist[0]
        gw_rows[code] = (code, s[6], s[7], s[8], s[11], s[9], s[10], s[12])

    cfgs = make_predictors()

    # Add F (DTM-only) as a separate predictor — applied with DTM PL.
    def f_fn(pl_dtm, residual, fsl, rx_gain):
        return DEVICE_TX_DBM + DEVICE_TX_GAIN + rx_gain - pl_dtm + residual

    results = {name: [] for name in cfgs}
    results["F_DTM_only"] = []

    t0 = time.time()
    n_done = 0
    for code, plist in by_gw.items():
        gw = gw_rows[code]
        try:
            sim_dsm = build_sim(gw, LOC_PCT, use_dsm=True)
            sim_dtm = build_sim(gw, LOC_PCT, use_dsm=False)
        except Exception as e:
            print(f"  build_sim FAIL for {code}: {e}")
            continue
        gw_rx_gain = float(gw[3])
        for r in plist:
            _id, lat, lon, rssi, sf, _, gw_lat, gw_lon, _, gw_h, gw_alt, _, _ = r
            try:
                pl_dsm = sim_dsm.GenerateReceptionPointResult(lat, lon)
                pl_dtm = sim_dtm.GenerateReceptionPointResult(lat, lon)
            except Exception:
                continue
            if not math.isfinite(pl_dsm) or not math.isfinite(pl_dtm):
                continue
            d_km = _haversine_km(gw_lat, gw_lon, lat, lon)
            fsl = fsl_db(d_km)
            df_pt = pd.DataFrame(
                [
                    {
                        "lat": lat,
                        "lon": lon,
                        "sf": float(sf),
                        "gw_lat": gw_lat,
                        "gw_lon": gw_lon,
                        "distance_km": d_km,
                        "log_distance_km": math.log1p(d_km),
                        "delta_alt_m": float(gw_alt) + float(gw_h),
                    }
                ]
            )
            res = float(model.predict(df_pt)[0])
            for name, fn in cfgs.items():
                pred = float(fn(pl_dsm, res, fsl, gw_rx_gain))
                results[name].append((float(rssi), pred, d_km))
            results["F_DTM_only"].append(
                (float(rssi), float(f_fn(pl_dtm, res, fsl, gw_rx_gain)), d_km)
            )
            n_done += 1
        print(f"  gw {code}: cum {n_done} pts in {time.time() - t0:.0f}s")

    print(f"\nTotal valid pts: {n_done}, elapsed {time.time() - t0:.0f}s\n")
    print(f"{'config':<18} {'n':>5} {'RMSE':>6} {'MAE':>6} {'bias':>7}")
    for name, pairs in results.items():
        if not pairs:
            continue
        errs = np.array([p - m for m, p, _ in pairs])
        rmse = float(np.sqrt(np.mean(errs**2)))
        mae = float(np.mean(np.abs(errs)))
        bias = float(np.mean(errs))
        print(f"{name:<18} {len(pairs):>5d} {rmse:>6.2f} {mae:>6.2f} {bias:>+7.2f}")

    bins_d = [(0, 0.5), (0.5, 2), (2, 5), (5, 10), (10, 50)]
    print("\nRMSE per distance bin:")
    print(f"{'config':<18} " + " ".join(f"{b[0]}-{b[1]}km".rjust(11) for b in bins_d))
    for name, pairs in results.items():
        cells = []
        for lo, hi in bins_d:
            sub = [p - m for m, p, d in pairs if lo <= d < hi]
            if sub:
                cells.append(f"{np.sqrt(np.mean(np.array(sub) ** 2)):.1f}(n={len(sub)})")
            else:
                cells.append("—")
        print(f"{name:<18} " + " ".join(c.rjust(11) for c in cells))

    # ============== Phase 2: 5km × 5km grid for 3 gateways ==============
    print("\n\n== Phase 2: 5km × 5km grid for 3 gateways, area share per bin ==\n")
    from scipy.ndimage import median_filter

    # Pick 3 representative gateways from full DB (not just survey-covered ones).
    dsn = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(dsn) as c, c.cursor() as cur:
        cur.execute("""
            SELECT code, ST_Y(location::geometry), ST_X(location::geometry),
                   COALESCE(antenna_gain_dbi, 5.0), COALESCE(tx_power_dbm, 14.0),
                   COALESCE(antenna_height_m, 10.0), COALESCE(altitude_m, 0.0),
                   COALESCE(frequency_mhz, 923.0)
            FROM geo.gateways
            WHERE code IN ('ac1f09fffe00ab20','7276ff002e0507da','a84041ffff1ee248')
            ORDER BY code
        """)
        gw_db = {r[0]: r for r in cur.fetchall()}

    def apply_median(pl, size):
        valid_mask = np.isfinite(pl)
        fill = float(np.nanmedian(pl))
        filled = np.where(valid_mask, pl, fill)
        smoothed = median_filter(filled, size=size, mode="nearest")
        return np.where(valid_mask, smoothed, np.nan)

    for code in ("ac1f09fffe00ab20", "7276ff002e0507da", "a84041ffff1ee248"):
        if code not in gw_db:
            print(f"  skip {code} (not in DB)")
            continue
        gw = gw_db[code]
        print(f"\n--- Grid for gw {code} @ ({gw[1]:.5f}, {gw[2]:.5f}) ---")
        try:
            sim_dsm = build_sim(gw, LOC_PCT, use_dsm=True)
            sim_dtm = build_sim(gw, LOC_PCT, use_dsm=False)
        except Exception as e:
            print(f"  build_sim fail: {e}")
            continue
        g_lat, g_lon = gw[1], gw[2]
        rx_gain = float(gw[3])
        n_side = 50
        step_m = 100.0
        step_lat = step_m / 1000.0 / 111.0
        step_lon = step_m / 1000.0 / (111.0 * math.cos(math.radians(g_lat)))
        pl_dsm = np.full((n_side, n_side), np.nan, dtype=np.float32)
        pl_dtm = np.full((n_side, n_side), np.nan, dtype=np.float32)
        fsl_g = np.full((n_side, n_side), np.nan, dtype=np.float32)
        feat_rows = []
        t1 = time.time()
        for i in range(n_side):
            for j in range(n_side):
                lat = g_lat + (i - n_side / 2) * step_lat
                lon = g_lon + (j - n_side / 2) * step_lon
                try:
                    p1 = sim_dsm.GenerateReceptionPointResult(lat, lon)
                    p2 = sim_dtm.GenerateReceptionPointResult(lat, lon)
                except Exception:
                    p1, p2 = math.nan, math.nan
                if math.isfinite(p1) and p1 > 0:
                    pl_dsm[i, j] = p1
                if math.isfinite(p2) and p2 > 0:
                    pl_dtm[i, j] = p2
                d_km = _haversine_km(g_lat, g_lon, lat, lon)
                fsl_g[i, j] = fsl_db(d_km)
                feat_rows.append(
                    {
                        "lat": lat,
                        "lon": lon,
                        "sf": 10.0,
                        "gw_lat": g_lat,
                        "gw_lon": g_lon,
                        "distance_km": d_km,
                        "log_distance_km": math.log1p(d_km),
                        "delta_alt_m": float(gw[6]) + float(gw[5]),
                    }
                )
        df_grid = pd.DataFrame(feat_rows)
        residual = model.predict(df_grid).reshape(n_side, n_side).astype(np.float32)
        print(
            f"  Sim done in {time.time() - t1:.0f}s; residual min/mean/max: "
            f"{residual.min():.1f}/{residual.mean():.1f}/{residual.max():.1f}"
        )

        def rssi_for(pl_grid, transform_res=lambda r: r, rx_gain=rx_gain, residual=residual):
            s1 = DEVICE_TX_DBM + DEVICE_TX_GAIN + rx_gain - pl_grid
            return s1 + transform_res(residual)

        configs = {
            "Current (DSM,no filt)": rssi_for(pl_dsm),
            "D5 (DSM,med 5x5)": rssi_for(apply_median(pl_dsm, 5)),
            "D7 (DSM,med 7x7)": rssi_for(apply_median(pl_dsm, 7)),
            "E25 (cap+25)": rssi_for(np.minimum(pl_dsm, fsl_g + 25.0)),
            "E35 (cap+35)": rssi_for(np.minimum(pl_dsm, fsl_g + 35.0)),
            "G clip±5": rssi_for(pl_dsm, lambda r: np.clip(r, -5, 5)),
            "G clip±10": rssi_for(pl_dsm, lambda r: np.clip(r, -10, 10)),
            "G asym[-3,+∞)": rssi_for(pl_dsm, lambda r: np.maximum(r, -3.0)),
            "G asym[-5,+∞)": rssi_for(pl_dsm, lambda r: np.maximum(r, -5.0)),
            "G[-3,+15]+D5": rssi_for(apply_median(pl_dsm, 5), lambda r: np.clip(r, -3, 15)),
            "F (DTM only)": rssi_for(pl_dtm),
        }
        print(f"  {'config':<23} {'strong':>8} {'good':>7} {'marg':>7} {'weak':>7} {'<-140':>8}")
        print("  " + "-" * 71)
        for name, rssi in configs.items():
            s = share_bins(rssi.ravel())
            print(
                f"  {name:<23} {s[0]:>7.1f}% {s[1]:>6.1f}% {s[2]:>6.1f}% {s[3]:>6.1f}% {s[4]:>7.1f}%"
            )

    print("\n=== Notes ===")
    print(
        "strong = ≥−100, good = −100..−110, marg = −110..−120, weak = −120..−140, <−140 = không phủ"
    )
    print("Phase 1: độ chính xác per-point. Phase 2: phân bố diện tích quanh từng gw.")


if __name__ == "__main__":
    main()
