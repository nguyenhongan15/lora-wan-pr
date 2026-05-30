"""LOGO test: mô phỏng "thêm gateway mới" — gateway đó vắng mặt khi train.

So sánh 5 chiến lược trên 8 fold (mỗi fold hold-out 1 gateway):
  Stage1Only  : không Stage 2 (floor — chỉ ITU P.1812).
  Base        : v0.5 8 feature (giữ gw_lat, gw_lon).
  NoGW        : drop (gw_lat, gw_lon) → 6 feature, ép model generalize.
  DBB         : per-gw × per-bin median residual trừ trên train; predict gw mới
                = XGB output (không thêm correction vì gw mới không có bảng bias).
  NoGW+DBB    : kết hợp.

Hyperparam: tree_method=hist, n_est=2000, lr=0.05, depth=4, mcw=20,
subsample/colsample=0.7, reg_alpha=1.0, reg_lambda=10.0, early_stopping=50,
StratifiedKFold theo SF cho val split.

Chạy trong container api-service:
    docker cp scripts/experiments/test_gateway_generalization_2026_05_31.py \\
        lora-wan-api:/tmp/test_gw.py
    docker exec lora-wan-api python /tmp/test_gw.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.model_selection import StratifiedKFold

CACHE_PATH = "/tmp/stage2_variants_cache.npz"
RAW_COLS = [
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
BIN_EDGES = [0, 2, 5, 10, 100]
BIN_LABELS = ["<2km", "2-5km", "5-10km", ">=10km"]

V05_FEATS = [
    "lat",
    "lon",
    "sf",
    "gw_lat",
    "gw_lon",
    "distance_km",
    "log_distance_km",
    "delta_alt_m",
]
NOGW_FEATS = ["lat", "lon", "sf", "distance_km", "log_distance_km", "delta_alt_m"]

XGB_KW = {
    "tree_method": "hist",
    "n_estimators": 2000,
    "learning_rate": 0.05,
    "max_depth": 4,
    "min_child_weight": 20,
    "subsample": 0.7,
    "colsample_bytree": 0.7,
    "reg_alpha": 1.0,
    "reg_lambda": 10.0,
    "early_stopping_rounds": 50,
    "n_jobs": -1,
    "random_state": 42,
}


def add_derived(X: np.ndarray) -> pd.DataFrame:
    df = pd.DataFrame(X, columns=RAW_COLS)
    lat1, lon1 = np.radians(df["lat"]), np.radians(df["lon"])
    lat2, lon2 = np.radians(df["gw_lat"]), np.radians(df["gw_lon"])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    df["distance_km"] = 2 * 6371.0088 * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))
    df["log_distance_km"] = np.log1p(df["distance_km"])
    df["delta_alt_m"] = df["gw_alt"] + df["gw_ant_h"]
    return df


def bin_idx(d_km: np.ndarray) -> np.ndarray:
    return np.clip(np.digitize(d_km, BIN_EDGES) - 1, 0, len(BIN_LABELS) - 1)


def compute_dbb_table(df_train: pd.DataFrame, y_train: np.ndarray) -> dict:
    df = df_train.copy()
    df["y"] = y_train
    df["gw_key"] = list(zip(df["gw_lat"].round(6), df["gw_lon"].round(6), strict=True))
    df["bin"] = bin_idx(df["distance_km"].to_numpy())
    table = {}
    for (gw_key, b), grp in df.groupby(["gw_key", "bin"]):
        if len(grp) >= 5:
            table[(gw_key, b)] = float(grp["y"].median())
    return table


def apply_dbb(df: pd.DataFrame, dbb: dict) -> np.ndarray:
    gw_keys = list(zip(df["gw_lat"].round(6), df["gw_lon"].round(6), strict=True))
    bins = bin_idx(df["distance_km"].to_numpy())
    return np.array([dbb.get((gk, b), 0.0) for gk, b in zip(gw_keys, bins, strict=True)])


def fit_predict(feat_cols, df_tr, y_tr, df_te) -> np.ndarray:
    sf_int = df_tr["sf"].astype(int).to_numpy()
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    tr_i, va_i = next(skf.split(df_tr, sf_int))
    Xtr = df_tr[feat_cols].iloc[tr_i]
    Xva = df_tr[feat_cols].iloc[va_i]
    model = xgb.XGBRegressor(**XGB_KW)
    model.fit(Xtr, y_tr[tr_i], eval_set=[(Xva, y_tr[va_i])], verbose=False)
    return model.predict(df_te[feat_cols])


def eval_per_bin(y_true, y_pred, d_km):
    err = y_pred - y_true
    out = {"all": (len(err), float(np.sqrt(np.mean(err**2))), float(np.mean(err)))}
    for i, lbl in enumerate(BIN_LABELS):
        m = bin_idx(d_km) == i
        if m.sum() == 0:
            out[lbl] = (0, 0.0, 0.0)
        else:
            e = err[m]
            out[lbl] = (int(m.sum()), float(np.sqrt(np.mean(e**2))), float(np.mean(e)))
    return out


def main():
    print(f"Load: {CACHE_PATH}")
    c = np.load(CACHE_PATH)
    X = np.vstack([c["X_train"], c["X_test"]])
    y = np.concatenate([c["y_train"], c["y_test"]])
    print(f"Total rows: {len(X)}")
    df_all = add_derived(X)
    gw_keys = list(zip(df_all["gw_lat"].round(6), df_all["gw_lon"].round(6), strict=True))
    df_all["gw_key"] = gw_keys
    unique_gw = sorted(set(gw_keys))
    print(f"Unique gateways: {len(unique_gw)}")
    for gw in unique_gw:
        n = sum(1 for k in gw_keys if k == gw)
        print(f"  {gw}: n={n}")

    strategies = ["Stage1Only", "Base", "NoGW", "DBB", "NoGW+DBB"]
    agg = {s: [] for s in strategies}
    per_gw_rows = []

    for gw in unique_gw:
        m_test = df_all["gw_key"].apply(lambda x, gw=gw: x == gw).to_numpy()
        n_test = int(m_test.sum())
        if n_test < 30:
            print(f"\nSkip {gw}: n_test={n_test} < 30")
            continue
        df_tr = df_all[~m_test].drop(columns=["gw_key"]).reset_index(drop=True)
        df_te = df_all[m_test].drop(columns=["gw_key"]).reset_index(drop=True)
        y_tr = y[~m_test]
        y_te = y[m_test]
        d_te = df_te["distance_km"].to_numpy()

        results = {}

        # Stage1Only = predict 0 residual → err = -y_te
        results["Stage1Only"] = eval_per_bin(y_te, np.zeros_like(y_te), d_te)

        # Base v0.5
        pred = fit_predict(V05_FEATS, df_tr, y_tr, df_te)
        results["Base"] = eval_per_bin(y_te, pred, d_te)

        # NoGW
        pred = fit_predict(NOGW_FEATS, df_tr, y_tr, df_te)
        results["NoGW"] = eval_per_bin(y_te, pred, d_te)

        # DBB — trừ per-gw bin bias trên train; gw mới → adj=0
        dbb = compute_dbb_table(df_tr, y_tr)
        y_tr_corr = y_tr - apply_dbb(df_tr, dbb)
        pred = fit_predict(V05_FEATS, df_tr, y_tr_corr, df_te)
        results["DBB"] = eval_per_bin(y_te, pred, d_te)

        # NoGW+DBB
        pred = fit_predict(NOGW_FEATS, df_tr, y_tr_corr, df_te)
        results["NoGW+DBB"] = eval_per_bin(y_te, pred, d_te)

        print(f"\n=== Held-out GW {gw} (n_test={n_test}) ===")
        print(
            f"  {'strategy':12s} {'RMSE':>6s} {'bias':>7s}  "
            f"{'<2km':>14s} {'2-5km':>14s} {'5-10km':>14s}"
        )
        for s in strategies:
            r = results[s]
            all_ = r["all"]
            b1 = r["<2km"]
            b2 = r["2-5km"]
            b3 = r["5-10km"]
            print(
                f"  {s:12s} {all_[1]:>6.2f} {all_[2]:>+7.2f}  "
                f"({b1[0]:>3},{b1[1]:>5.2f}) ({b2[0]:>3},{b2[1]:>5.2f}) "
                f"({b3[0]:>3},{b3[1]:>5.2f})"
            )
            agg[s].append((n_test, all_[1], all_[2]))
            per_gw_rows.append(
                {"gw": gw, "strategy": s, "n": n_test, "rmse": all_[1], "bias": all_[2]}
            )

    print("\n" + "=" * 70)
    print("AGGREGATE — weighted mean (theo n_test) cross 8 hold-out gateways")
    print("=" * 70)
    print(f"  {'strategy':12s} {'wRMSE':>7s} {'wBias':>7s}")
    base_rmse = None
    for s in strategies:
        items = agg[s]
        if not items:
            continue
        ns = np.array([x[0] for x in items])
        rmses = np.array([x[1] for x in items])
        biases = np.array([x[2] for x in items])
        w = ns / ns.sum()
        wrmse = float(np.sqrt(np.sum(w * rmses**2)))
        wbias = float(np.sum(w * biases))
        if s == "Base":
            base_rmse = wrmse
        delta = ""
        if base_rmse is not None and s != "Base":
            delta = f"  Δ vs Base = {wrmse - base_rmse:+.2f} dB"
        print(f"  {s:12s} {wrmse:>7.2f} {wbias:>+7.2f}{delta}")


if __name__ == "__main__":
    main()
