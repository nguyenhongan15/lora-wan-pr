"""Test 8 biến thể feature engineering cho Stage 2 XGBoost residual model.

Variants:
  - B    : baseline = v0.4 hiện tại (13 features kể cả derived).
  - A    : drop 5 zero-importance features (freq, gw_alt, gw_ant_h, gw_gain, gw_tx_p).
  - F    : fix `delta_alt_m` thành Δ thực = (gw_alt + gw_ant_h) - target_DTM_elev.
  - C    : thay (gw_lat, gw_lon) bằng `gateway_id` categorical.
  - AF, AC, FC, AFC : kết hợp.

Cùng hyperparam v0.4: tree_method=hist, n_est=2000, lr=0.05, depth=4,
mcw=20, subsample=0.7, colsample=0.7, reg_alpha=1.0, reg_lambda=10.0,
early_stopping=50, StratifiedKFold theo sf.

Chạy trong container api-service (cần crc-covlib runtime + DEM raster):
    docker cp scripts/experiments/test_feature_variants_2026_05_31.py \\
        lora-wan-api:/tmp/test_feats.py
    docker exec lora-wan-api python /tmp/test_feats.py
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import xgboost as xgb
from sklearn.model_selection import StratifiedKFold

CACHE_PATH = "/tmp/stage2_variants_cache.npz"
DEM_DIR = os.environ.get("LORA_DEM_DIRECTORY", "/data/dem")

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
ZERO_FEATS = ["frequency_mhz", "gw_alt", "gw_ant_h", "gw_gain", "gw_tx_p"]


def add_derived(X: np.ndarray) -> pd.DataFrame:
    df = pd.DataFrame(X, columns=FEATURE_COLS)
    lat1, lon1 = np.radians(df["lat"]), np.radians(df["lon"])
    lat2, lon2 = np.radians(df["gw_lat"]), np.radians(df["gw_lon"])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    df["distance_km"] = 2 * 6371.0088 * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))
    df["log_distance_km"] = np.log1p(df["distance_km"])
    df["delta_alt_m"] = df["gw_alt"] + df["gw_ant_h"]  # CŨ — misnamed
    return df


def sample_dtm_bulk(lats: np.ndarray, lons: np.ndarray, dem_dir: str) -> np.ndarray:
    """Sample DTM tại N điểm (lat, lon). Mở 1 tile bao toàn bộ điểm."""
    pts = list(zip(lons, lats, strict=True))
    for tif in Path(dem_dir).glob("*.tif"):
        with rasterio.open(tif) as src:
            b = src.bounds
            if all(b.left <= x <= b.right and b.bottom <= y <= b.top for x, y in pts):
                vals = list(src.sample(pts))
                return np.array([v[0] for v in vals], dtype=np.float64)
    raise RuntimeError("No DEM tile covers all points")


def build_gw_id_map(df_all: pd.DataFrame) -> dict:
    keys = list(zip(df_all["gw_lat"].round(6), df_all["gw_lon"].round(6), strict=True))
    unique = sorted(set(keys))
    return {k: i for i, k in enumerate(unique)}


def variant_cols(name: str) -> tuple[list[str], list[str]]:
    cols = [*FEATURE_COLS, "distance_km", "log_distance_km", "delta_alt_m"]
    cat_cols: list[str] = []
    if "A" in name:
        cols = [c for c in cols if c not in ZERO_FEATS]
    if "F" in name:
        cols = [c for c in cols if c != "delta_alt_m"] + ["delta_alt_m_real"]
    if "C" in name:
        cols = [c for c in cols if c not in ("gw_lat", "gw_lon")] + ["gateway_id"]
        cat_cols.append("gateway_id")
    return cols, cat_cols


def train_eval(
    name: str,
    df_train: pd.DataFrame,
    df_test: pd.DataFrame,
    y_train: np.ndarray,
    y_test: np.ndarray,
) -> dict:
    cols, cat_cols = variant_cols(name)
    Xtr = df_train[cols].copy()
    Xte = df_test[cols].copy()
    for c in cat_cols:
        Xtr[c] = Xtr[c].astype("category")
        Xte[c] = Xte[c].astype("category")

    sf_labels = df_train["sf"].astype(int).to_numpy()
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    tr_idx, va_idx = next(skf.split(Xtr, sf_labels))

    model = xgb.XGBRegressor(
        tree_method="hist",
        n_estimators=2000,
        learning_rate=0.05,
        max_depth=4,
        min_child_weight=20,
        subsample=0.7,
        colsample_bytree=0.7,
        reg_alpha=1.0,
        reg_lambda=10.0,
        early_stopping_rounds=50,
        n_jobs=-1,
        random_state=42,
        enable_categorical=bool(cat_cols),
    )
    model.fit(
        Xtr.iloc[tr_idx],
        y_train[tr_idx],
        eval_set=[(Xtr.iloc[va_idx], y_train[va_idx])],
        verbose=False,
    )
    pred = model.predict(Xte)
    err = y_test - pred

    dist = df_test["distance_km"].to_numpy()
    per_bin = {}
    for lo, hi, lbl in [(0, 2, "<2km"), (2, 5, "2-5km"), (5, 10, "5-10km")]:
        m = (dist >= lo) & (dist < hi)
        if m.sum() == 0:
            per_bin[lbl] = (0, 0.0, 0.0)
        else:
            e = err[m]
            per_bin[lbl] = (
                int(m.sum()),
                float(np.sqrt(np.mean(e**2))),
                float(np.mean(e)),
            )
    return {
        "name": name,
        "n_feat": len(cols),
        "best_iter": int(model.best_iteration),
        "rmse": float(np.sqrt(np.mean(err**2))),
        "mae": float(np.mean(np.abs(err))),
        "bias": float(np.mean(err)),
        "per_bin": per_bin,
    }


def main() -> None:
    print(f"Loading cache: {CACHE_PATH}")
    cache = np.load(CACHE_PATH)
    X_train, y_train = cache["X_train"], cache["y_train"]
    X_test, y_test = cache["X_test"], cache["y_test"]
    print(f"  train n={len(X_train)}, test n={len(X_test)}")

    df_train = add_derived(X_train)
    df_test = add_derived(X_test)

    print(f"Sampling DTM at target lat/lon from {DEM_DIR}...")
    train_elev = sample_dtm_bulk(df_train["lat"].to_numpy(), df_train["lon"].to_numpy(), DEM_DIR)
    test_elev = sample_dtm_bulk(df_test["lat"].to_numpy(), df_test["lon"].to_numpy(), DEM_DIR)
    # Real Δ: chiều cao antenna gw so với mặt đất target. Dương = antenna cao
    # hơn target (case phổ biến).
    df_train["delta_alt_m_real"] = df_train["gw_alt"] + df_train["gw_ant_h"] - train_elev
    df_test["delta_alt_m_real"] = df_test["gw_alt"] + df_test["gw_ant_h"] - test_elev
    print(
        f"  target_elev train: mean={train_elev.mean():.1f} std={train_elev.std():.1f}"
        f" | test: mean={test_elev.mean():.1f} std={test_elev.std():.1f}"
    )
    print(
        f"  delta_alt_m_real train: mean={df_train['delta_alt_m_real'].mean():.1f}"
        f" std={df_train['delta_alt_m_real'].std():.1f}"
    )

    df_all = pd.concat([df_train, df_test], ignore_index=True)
    gw_map = build_gw_id_map(df_all)
    print(f"Unique gateways in train+test: {len(gw_map)}")
    df_train["gateway_id"] = [
        gw_map[(round(la, 6), round(lo, 6))]
        for la, lo in zip(df_train["gw_lat"], df_train["gw_lon"], strict=True)
    ]
    df_test["gateway_id"] = [
        gw_map[(round(la, 6), round(lo, 6))]
        for la, lo in zip(df_test["gw_lat"], df_test["gw_lon"], strict=True)
    ]

    variants = ["B", "A", "F", "C", "AF", "AC", "FC", "AFC"]
    results = []
    print("\n" + "=" * 110)
    print(
        f"{'name':5} {'n_feat':>6} {'iter':>6} {'RMSE':>6} {'MAE':>6} {'bias':>7}  "
        f"<2km(n,RMSE,bias)  2-5km(n,RMSE,bias)  5-10km(n,RMSE,bias)"
    )
    print("=" * 110)
    for v in variants:
        r = train_eval(v, df_train, df_test, y_train, y_test)
        results.append(r)
        pb = r["per_bin"]
        print(
            f"{r['name']:5} {r['n_feat']:>6} {r['best_iter']:>6} "
            f"{r['rmse']:>6.2f} {r['mae']:>6.2f} {r['bias']:>+7.2f}  "
            f"({pb['<2km'][0]:>3},{pb['<2km'][1]:>5.2f},{pb['<2km'][2]:>+6.2f}) "
            f"({pb['2-5km'][0]:>3},{pb['2-5km'][1]:>5.2f},{pb['2-5km'][2]:>+6.2f}) "
            f"({pb['5-10km'][0]:>3},{pb['5-10km'][1]:>5.2f},{pb['5-10km'][2]:>+6.2f})"
        )

    best = min(results, key=lambda r: r["rmse"])
    print("\n" + "=" * 110)
    print(f"BEST RMSE: {best['name']} = {best['rmse']:.2f} dB")


if __name__ == "__main__":
    main()
