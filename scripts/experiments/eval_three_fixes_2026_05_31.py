"""Test 3 candidate fixes for long-range RSSI under-prediction.

A. Stage 2 residual clip variants {none, ±10, ±15, ±20, ±25, ±30}.
B. Stage 1 config variants:
     B0: baseline (DSM + skip P.2108, location%=50)
     B1: DTM only (no surface DEM)
     B2: DSM + P.2108 ADDED back (sanity vs known bug)
     B3: DSM, location%=10 (less pessimistic)
     B4: DSM, location%=95 (worst-case design margin)
C. Post-hoc per-distance-bin offset ON TOP of Stage 2 (train/test split 70/30).

Reads N random rows from ts.survey_training (Đà Nẵng, d<50km), computes Stage 1
PL per variant, applies Stage 2 XGBoost residual per Option-A clip, reports
bias / RMSE per distance bin. No project files are modified.
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
import psycopg

REPO_ROOT = Path("/app")
sys.path.insert(0, str(REPO_ROOT / "services" / "api-service" / "src"))

DEM_DIR = os.environ.get("LORA_DEM_DIRECTORY", "/data/dem")
SURFACE_DEM_DIR = os.environ.get("LORA_SURFACE_DEM_DIRECTORY", "/data/dem-surface")
STAGE2_MODEL = Path(os.environ.get("STAGE2_MODEL", "/tmp/stage2_xgb.joblib"))

DEVICE_TX_DBM = 14.0
DEVICE_TX_GAIN = 0.0
DEVICE_HEIGHT_M = 1.5

P2108_MIN_DISTANCE_KM = 0.25

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


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _build_sim(gw: GwConfig, variant: str) -> Any:
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

    if variant in ("B0", "B2"):
        loc_pct = 50.0
        use_dsm = True
    elif variant == "B1":
        loc_pct = 50.0
        use_dsm = False
    elif variant == "B3":
        loc_pct = 10.0
        use_dsm = True
    elif variant == "B4":
        loc_pct = 95.0
        use_dsm = True
    else:
        raise ValueError(variant)

    sim.SetITURP1812LocationPercentage(loc_pct)
    if use_dsm:
        sim.SetITURP1812SurfaceProfileMethod(
            covlib.P1812SurfaceProfileMethod.P1812_USE_SURFACE_ELEV_DATA
        )
        sim.SetPrimarySurfaceElevDataSource(covlib.SurfaceElevDataSource.SURF_ELEV_GEOTIFF)
        sim.SetSurfaceElevDataSourceDirectory(
            covlib.SurfaceElevDataSource.SURF_ELEV_GEOTIFF, SURFACE_DEM_DIR
        )
    else:
        # No DSM → P.1812 will fall back to terrain only
        sim.SetITURP1812SurfaceProfileMethod(
            covlib.P1812SurfaceProfileMethod.P1812_DEFAULT_TO_ZERO_SURFACE_HEIGHT
        )

    sim.SetPrimaryTerrainElevDataSource(covlib.TerrainElevDataSource.TERR_ELEV_GEOTIFF)
    sim.SetTerrainElevDataSourceDirectory(covlib.TerrainElevDataSource.TERR_ELEV_GEOTIFF, DEM_DIR)
    sim.SetResultType(covlib.ResultType.PATH_LOSS_DB)
    sim.SetTerrainElevDataSamplingResolution(30)
    return sim, loc_pct


def _compute_pl_for_variant(
    rows_by_gw: dict[str, list[dict]],
    gw_cfg: dict[str, GwConfig],
    variant: str,
) -> dict[str, np.ndarray]:
    """Return {gw_code: pl_array aligned to rows_by_gw[gw_code]}."""
    from crc_covlib.helper import itur_p2108  # type: ignore[import-untyped]

    out: dict[str, np.ndarray] = {}
    t0 = time.time()
    for code, items in rows_by_gw.items():
        gw = gw_cfg[code]
        try:
            sim, loc_pct = _build_sim(gw, variant)
        except Exception as exc:
            print(f"  [{variant}/{code}] build_sim fail: {exc}")
            out[code] = np.full(len(items), np.nan)
            continue
        pls = np.full(len(items), np.nan, dtype=np.float64)
        freq_ghz = gw.freq_mhz / 1000.0
        for i, r in enumerate(items):
            try:
                pl = sim.GenerateReceptionPointResult(float(r["lat"]), float(r["lon"]))
            except Exception:
                continue
            if not math.isfinite(pl):
                continue
            if variant == "B2":
                # Re-add P.2108 clutter (old buggy double-count config) for d>=0.25km
                d_km = float(r["d_km"])
                if d_km >= P2108_MIN_DISTANCE_KM:
                    try:
                        clutter = itur_p2108.TerrestrialPathClutterLoss(freq_ghz, d_km, loc_pct)
                        pl = pl + clutter
                    except Exception:
                        pass
            pls[i] = pl
        out[code] = pls
    print(f"  variant {variant} done in {time.time() - t0:.1f}s")
    return out


def _pl_to_rssi(pl: np.ndarray, gw: GwConfig) -> np.ndarray:
    return DEVICE_TX_DBM + DEVICE_TX_GAIN + gw.rx_gain_dbi - pl


def _stage2_residual(features: np.ndarray, model: Any) -> np.ndarray:
    import pandas as pd

    df = pd.DataFrame(
        features,
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
    return np.asarray(model.predict(df), dtype=np.float64)


def _per_bin_stats(diff: np.ndarray, d_km: np.ndarray) -> list[dict]:
    out = []
    for label, lo, hi in BINS:
        m = (d_km >= lo) & (d_km < hi)
        n = int(m.sum())
        if n == 0:
            continue
        out.append(
            {
                "bin": label,
                "n": n,
                "bias": float(np.mean(diff[m])),
                "rmse": float(np.sqrt(np.mean(diff[m] ** 2))),
                "mae": float(np.mean(np.abs(diff[m]))),
            }
        )
    return out


def _overall_stats(diff: np.ndarray) -> tuple[float, float, float]:
    return (
        float(np.mean(np.abs(diff))),
        float(np.sqrt(np.mean(diff**2))),
        float(np.mean(diff)),
    )


def main() -> None:
    n_target = int(os.environ.get("N_SAMPLE", "1500"))
    dsn = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")

    print(f"=== Loading {n_target} random survey rows ===")
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(SQL, (n_target,))
        rows = cur.fetchall()
        cols = [d.name for d in cur.description]
    print(f"loaded n={len(rows)}")

    rows_by_gw: dict[str, list[dict]] = {}
    gw_cfg: dict[str, GwConfig] = {}
    for r in rows:
        d = dict(zip(cols, r, strict=True))
        code = d["code"]
        rows_by_gw.setdefault(code, []).append(d)
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

    # Build aligned arrays: measured, distance, features, gw_code-per-row
    measured: list[float] = []
    distances: list[float] = []
    features_rows: list[list[float]] = []
    gw_index: list[str] = []
    pos_in_gw: dict[str, int] = {}  # how many we've consumed from this gw
    row_to_gwpos: list[tuple[str, int]] = []
    for r in rows:
        d = dict(zip(cols, r, strict=True))
        code = d["code"]
        idx = pos_in_gw.get(code, 0)
        pos_in_gw[code] = idx + 1
        row_to_gwpos.append((code, idx))

        gw = gw_cfg[code]
        sf = float(d["sf"])
        d_km = float(d["d_km"])
        measured.append(float(d["rssi"]))
        distances.append(d_km)
        features_rows.append(
            [
                float(d["lat"]),
                float(d["lon"]),
                sf,
                gw.lat,
                gw.lon,
                d_km,
                math.log1p(d_km),
                gw.altitude_m + gw.ant_height_m,
            ]
        )
        gw_index.append(code)

    meas = np.asarray(measured, dtype=np.float64)
    d_km_arr = np.asarray(distances, dtype=np.float64)
    feat_arr = np.asarray(features_rows, dtype=np.float64)

    import joblib

    print(f"=== Loading Stage 2 model: {STAGE2_MODEL}")
    model = joblib.load(STAGE2_MODEL)
    residual_raw = _stage2_residual(feat_arr, model)

    # ── Test B: Stage 1 variants ───────────────────────────────────────────
    print("\n=== TEST B: Stage 1 config variants ===")
    variants = ["B0", "B1", "B2", "B3", "B4"]
    variant_label = {
        "B0": "DSM, skip P.2108, loc%=50 (current)",
        "B1": "DTM only (no DSM)",
        "B2": "DSM + P.2108 re-added (sanity)",
        "B3": "DSM, loc%=10 (less pessimistic)",
        "B4": "DSM, loc%=95 (design margin)",
    }
    stage1_per_variant: dict[str, np.ndarray] = {}
    for v in variants:
        print(f"\n-- {v}: {variant_label[v]}")
        pl_by_gw = _compute_pl_for_variant(rows_by_gw, gw_cfg, v)
        s1 = np.full(len(meas), np.nan)
        for i, (code, idx) in enumerate(row_to_gwpos):
            pl = pl_by_gw[code][idx]
            if math.isfinite(pl):
                gw = gw_cfg[code]
                s1[i] = DEVICE_TX_DBM + DEVICE_TX_GAIN + gw.rx_gain_dbi - pl
        valid = np.isfinite(s1)
        diff = s1[valid] - meas[valid]
        mae, rmse, bias = _overall_stats(diff)
        print(
            f"  Stage1 only  : n={int(valid.sum())} MAE={mae:.2f} RMSE={rmse:.2f} bias={bias:+.2f}"
        )
        per = _per_bin_stats(s1[valid] - meas[valid], d_km_arr[valid])
        for p in per:
            print(f"    {p['bin']:<12} n={p['n']:>4} bias={p['bias']:+7.2f} RMSE={p['rmse']:6.2f}")
        stage1_per_variant[v] = s1

    # ── Test A: Stage 2 clip variants on baseline (B0) ─────────────────────
    print("\n=== TEST A: Stage 2 residual clip variants (B0 as Stage 1) ===")
    clip_grid = [None, 10, 15, 20, 25, 30, 40]
    s1_base = stage1_per_variant["B0"]
    valid_b0 = np.isfinite(s1_base)
    res_b0 = residual_raw[valid_b0]
    s1_b0 = s1_base[valid_b0]
    meas_b0 = meas[valid_b0]
    d_b0 = d_km_arr[valid_b0]
    print(f"  n={int(valid_b0.sum())}")
    print(f"  {'clip':<8} {'MAE':>6} {'RMSE':>6} {'bias':>7} | per-bin RMSE")
    bin_labels = [b[0] for b in BINS]
    for clip in clip_grid:
        if clip is None:
            res_c = res_b0
            label = "none"
        else:
            res_c = np.clip(res_b0, -clip, clip)
            label = f"±{clip}"
        s2_c = s1_b0 + res_c
        diff = s2_c - meas_b0
        mae, rmse, bias = _overall_stats(diff)
        per = _per_bin_stats(diff, d_b0)
        per_by_label = {p["bin"]: p["rmse"] for p in per}
        per_str = " ".join(
            f"{lab}={per_by_label.get(lab, float('nan')):.1f}"
            for lab in bin_labels
            if lab in per_by_label
        )
        print(f"  {label:<8} {mae:6.2f} {rmse:6.2f} {bias:+7.2f} | {per_str}")

    # ── Test A on best Stage 1 variant ─────────────────────────────────────
    # Pick variant with lowest overall Stage1-RMSE then re-run clip sweep
    best_v = None
    best_rmse = float("inf")
    for v in variants:
        s1 = stage1_per_variant[v]
        valid = np.isfinite(s1)
        if not valid.any():
            continue
        rmse = float(np.sqrt(np.mean((s1[valid] - meas[valid]) ** 2)))
        if rmse < best_rmse:
            best_rmse, best_v = rmse, v
    print(f"\n=== TEST A on BEST Stage 1 variant ({best_v}, S1 RMSE={best_rmse:.2f}) ===")
    s1_best = stage1_per_variant[best_v]
    valid_best = np.isfinite(s1_best)
    s1_v = s1_best[valid_best]
    res_v = residual_raw[valid_best]
    meas_v = meas[valid_best]
    d_v = d_km_arr[valid_best]
    print(f"  {'clip':<8} {'MAE':>6} {'RMSE':>6} {'bias':>7} | per-bin RMSE")
    for clip in clip_grid:
        if clip is None:
            res_c = res_v
            label = "none"
        else:
            res_c = np.clip(res_v, -clip, clip)
            label = f"±{clip}"
        s2_c = s1_v + res_c
        diff = s2_c - meas_v
        mae, rmse, bias = _overall_stats(diff)
        per = _per_bin_stats(diff, d_v)
        per_by_label = {p["bin"]: p["rmse"] for p in per}
        per_str = " ".join(
            f"{lab}={per_by_label.get(lab, float('nan')):.1f}"
            for lab in bin_labels
            if lab in per_by_label
        )
        print(f"  {label:<8} {mae:6.2f} {rmse:6.2f} {bias:+7.2f} | {per_str}")

    # ── Test C: Post-hoc per-bin offset on Stage 2 (clip ±15, train/test) ──
    print("\n=== TEST C: Post-hoc per-bin offset on Stage 2 (B0 + clip±15) ===")
    s2_full = s1_base + np.clip(residual_raw, -15.0, 15.0)
    valid_c = valid_b0
    s2_c = s2_full[valid_c]
    meas_c = meas[valid_c]
    d_c = d_km_arr[valid_c]
    rng = np.random.default_rng(42)
    n = int(valid_c.sum())
    idx = np.arange(n)
    rng.shuffle(idx)
    cut = int(0.7 * n)
    tr_idx, te_idx = idx[:cut], idx[cut:]
    s2_tr = s2_c[tr_idx]
    meas_tr = meas_c[tr_idx]
    d_tr = d_c[tr_idx]
    s2_te = s2_c[te_idx]
    meas_te = meas_c[te_idx]
    d_te = d_c[te_idx]
    # Compute per-bin offset on train
    bin_offsets = {}
    for label, lo, hi in BINS:
        mtr = (d_tr >= lo) & (d_tr < hi)
        if mtr.sum() >= 5:
            bin_offsets[label] = float(np.mean(meas_tr[mtr] - s2_tr[mtr]))
        else:
            bin_offsets[label] = 0.0
    print(f"  per-bin offsets (meas - s2, train n={cut}):")
    for lab, off in bin_offsets.items():
        print(f"    {lab:<12} = {off:+.2f} dB")
    # Apply on test
    s2_te_adj = s2_te.copy()
    for label, lo, hi in BINS:
        mte = (d_te >= lo) & (d_te < hi)
        s2_te_adj[mte] += bin_offsets[label]
    diff_base = s2_te - meas_te
    diff_adj = s2_te_adj - meas_te
    print(f"\n  Test (n={len(te_idx)}) — Stage 2 only (clip ±15):")
    print(
        f"    overall MAE={np.mean(np.abs(diff_base)):.2f} RMSE={np.sqrt(np.mean(diff_base**2)):.2f} bias={np.mean(diff_base):+.2f}"
    )
    for p in _per_bin_stats(diff_base, d_te):
        print(f"    {p['bin']:<12} n={p['n']:>4} bias={p['bias']:+7.2f} RMSE={p['rmse']:6.2f}")
    print(f"\n  Test (n={len(te_idx)}) — Stage 2 + per-bin offset:")
    print(
        f"    overall MAE={np.mean(np.abs(diff_adj)):.2f} RMSE={np.sqrt(np.mean(diff_adj**2)):.2f} bias={np.mean(diff_adj):+.2f}"
    )
    for p in _per_bin_stats(diff_adj, d_te):
        print(f"    {p['bin']:<12} n={p['n']:>4} bias={p['bias']:+7.2f} RMSE={p['rmse']:6.2f}")

    # Also: same Test C but on top of BEST Stage 1 + no-clip Stage 2
    print("\n=== TEST C2: per-bin offset on Best-S1 + no-clip Stage 2 ===")
    s2_full_v = s1_best + residual_raw  # no clip
    valid_v = np.isfinite(s2_full_v)
    s2_v = s2_full_v[valid_v]
    meas_v = meas[valid_v]
    d_v = d_km_arr[valid_v]
    n = int(valid_v.sum())
    idx = np.arange(n)
    rng = np.random.default_rng(43)
    rng.shuffle(idx)
    cut = int(0.7 * n)
    tr_idx, te_idx = idx[:cut], idx[cut:]
    s2_tr = s2_v[tr_idx]
    meas_tr = meas_v[tr_idx]
    d_tr = d_v[tr_idx]
    s2_te = s2_v[te_idx]
    meas_te = meas_v[te_idx]
    d_te = d_v[te_idx]
    bin_offsets2 = {}
    for label, lo, hi in BINS:
        mtr = (d_tr >= lo) & (d_tr < hi)
        if mtr.sum() >= 5:
            bin_offsets2[label] = float(np.mean(meas_tr[mtr] - s2_tr[mtr]))
        else:
            bin_offsets2[label] = 0.0
    s2_te_adj = s2_te.copy()
    for label, lo, hi in BINS:
        mte = (d_te >= lo) & (d_te < hi)
        s2_te_adj[mte] += bin_offsets2[label]
    diff_base = s2_te - meas_te
    diff_adj = s2_te_adj - meas_te
    print(f"  Test (n={len(te_idx)}) — Best-S1 + no-clip Stage 2:")
    print(
        f"    overall MAE={np.mean(np.abs(diff_base)):.2f} RMSE={np.sqrt(np.mean(diff_base**2)):.2f} bias={np.mean(diff_base):+.2f}"
    )
    print("  Test — + per-bin offset:")
    print(
        f"    overall MAE={np.mean(np.abs(diff_adj)):.2f} RMSE={np.sqrt(np.mean(diff_adj**2)):.2f} bias={np.mean(diff_adj):+.2f}"
    )

    print("\n=== DONE ===")


if __name__ == "__main__":
    main()
