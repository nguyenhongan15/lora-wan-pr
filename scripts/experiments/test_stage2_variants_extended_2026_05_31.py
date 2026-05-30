"""Mở rộng test: XGBoost vs sklearn MLP vs PyTorch MLP + stacking XGB→NN.

Variants (cùng feature set 8 col v0.5, cùng train/test cache):
  X0  XGBoost v0.5 ref (1 output: rssi_residual)
  X1  sklearn MLP single-output (64,32)            ← đã test, lặp lại để verify
  X2  sklearn MLP multi-output (64,32)             ← đã test, lặp lại
  X3  sklearn MLP single + XGB pred as feature (stacking)
  X4  sklearn MLP multi + XGB pred as feature (stacking)
  X5  PyTorch MLP (256-128-64) single-output, BN+dropout, custom loss
  X6  PyTorch MLP (256-128-64) multi-output, weighted loss (λ_snr ∈ {0.3, 1.0})
  X7  PyTorch stacking single (XGB pred as feature)
  X8  PyTorch stacking multi (XGB pred as feature + multi-output)

Tất cả eval RMSE/MAE/bias trên rssi_residual của 337 row hold-out.

Chạy:
    docker cp scripts/experiments/test_stage2_variants_extended_2026_05_31.py \\
        lora-wan-api:/tmp/test_ext.py
    docker exec lora-wan-api python /tmp/test_ext.py
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import xgboost as xgb
from sklearn.model_selection import StratifiedKFold
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler
from torch import nn

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("ext")

CACHE_PATH = Path("/tmp/stage2_multi_cache.npz")
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
FEATS = ["lat", "lon", "sf", "gw_lat", "gw_lon", "distance_km", "log_distance_km", "delta_alt_m"]

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


def add_derived(X):
    df = pd.DataFrame(X, columns=RAW_COLS)
    lat1, lon1 = np.radians(df.lat), np.radians(df.lon)
    lat2, lon2 = np.radians(df.gw_lat), np.radians(df.gw_lon)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    df["distance_km"] = 2 * 6371.0088 * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))
    df["log_distance_km"] = np.log1p(df.distance_km)
    df["delta_alt_m"] = df.gw_alt + df.gw_ant_h
    return df


def metrics(pred, y_true):
    err = pred - y_true
    return (float(np.sqrt(np.mean(err**2))), float(np.mean(np.abs(err))), float(np.mean(err)))


def train_xgb(df_tr, y_tr, df_te):
    sf_i = df_tr["sf"].astype(int).to_numpy()
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    tr_i, va_i = next(skf.split(df_tr, sf_i))
    m = xgb.XGBRegressor(**XGB_KW)
    m.fit(df_tr.iloc[tr_i], y_tr[tr_i], eval_set=[(df_tr.iloc[va_i], y_tr[va_i])], verbose=False)
    return m.predict(df_te), m.predict(df_tr)  # test_pred, train_pred (for stacking)


def train_sklearn_mlp(Xtr, ytr, Xte, hidden=(64, 32)):
    sx = StandardScaler().fit(Xtr)
    sy = StandardScaler().fit(
        ytr.reshape(-1, ytr.shape[1] if ytr.ndim > 1 else 1) if ytr.ndim > 1 else ytr.reshape(-1, 1)
    )
    ytr_s = sy.transform(
        ytr.reshape(-1, ytr.shape[1] if ytr.ndim > 1 else 1) if ytr.ndim > 1 else ytr.reshape(-1, 1)
    )
    if ytr.ndim == 1:
        ytr_s = ytr_s.ravel()
    nn_ = MLPRegressor(
        hidden_layer_sizes=hidden,
        activation="relu",
        solver="adam",
        learning_rate_init=1e-3,
        batch_size=128,
        alpha=1e-3,
        max_iter=500,
        early_stopping=True,
        validation_fraction=0.15,
        n_iter_no_change=20,
        random_state=42,
    )
    nn_.fit(sx.transform(Xtr), ytr_s)
    pred_s = nn_.predict(sx.transform(Xte))
    if pred_s.ndim == 1:
        pred = sy.inverse_transform(pred_s.reshape(-1, 1)).ravel()
    else:
        pred = sy.inverse_transform(pred_s)
    return pred, nn_.n_iter_


class TorchMLP(nn.Module):
    def __init__(self, in_dim, out_dim, hidden=(256, 128, 64), dropout=0.2):
        super().__init__()
        layers = []
        prev = in_dim
        for h in hidden:
            layers += [nn.Linear(prev, h), nn.BatchNorm1d(h), nn.ReLU(), nn.Dropout(dropout)]
            prev = h
        layers.append(nn.Linear(prev, out_dim))
        self.net = nn.Sequential(*layers)

    def forward(self, x):
        return self.net(x)


def train_torch(
    Xtr,
    ytr,
    Xte,
    hidden=(256, 128, 64),
    epochs=300,
    lr=1e-3,
    weight_decay=1e-3,
    dropout=0.2,
    batch_size=128,
    patience=30,
    loss_weights=None,
):
    torch.manual_seed(42)
    sx = StandardScaler().fit(Xtr)
    if ytr.ndim == 1:
        ytr = ytr.reshape(-1, 1)
    sy = StandardScaler().fit(ytr)
    Xtr_s = sx.transform(Xtr).astype(np.float32)
    ytr_s = sy.transform(ytr).astype(np.float32)
    Xte_s = sx.transform(Xte).astype(np.float32)

    # 85/15 train/val split
    n = len(Xtr_s)
    rng = np.random.RandomState(42)
    idx = rng.permutation(n)
    n_val = int(0.15 * n)
    val_i, tr_i = idx[:n_val], idx[n_val:]
    Xt, yt = Xtr_s[tr_i], ytr_s[tr_i]
    Xv, yv = Xtr_s[val_i], ytr_s[val_i]

    out_dim = ytr_s.shape[1]
    model = TorchMLP(Xtr_s.shape[1], out_dim, hidden=hidden, dropout=dropout)
    opt = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=weight_decay)
    Xv_t = torch.from_numpy(Xv)
    yv_t = torch.from_numpy(yv)
    if loss_weights is None:
        loss_weights = np.ones(out_dim, dtype=np.float32)
    lw = torch.from_numpy(np.asarray(loss_weights, dtype=np.float32))

    def weighted_mse(pred, target):
        return ((pred - target) ** 2 * lw).mean()

    best_val = float("inf")
    best_state = None
    no_improve = 0
    Xt_t = torch.from_numpy(Xt)
    yt_t = torch.from_numpy(yt)

    epoch = 0
    for epoch in range(epochs):  # noqa: B007  — epoch used after loop for return value
        model.train()
        perm = torch.randperm(len(Xt_t))
        for s in range(0, len(perm), batch_size):
            b = perm[s : s + batch_size]
            pred = model(Xt_t[b])
            loss = weighted_mse(pred, yt_t[b])
            opt.zero_grad()
            loss.backward()
            opt.step()
        model.eval()
        with torch.no_grad():
            val_loss = weighted_mse(model(Xv_t), yv_t).item()
        if val_loss < best_val - 1e-4:
            best_val = val_loss
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
            no_improve = 0
        else:
            no_improve += 1
            if no_improve >= patience:
                break

    if best_state is not None:
        model.load_state_dict(best_state)
    model.eval()
    with torch.no_grad():
        pred_s = model(torch.from_numpy(Xte_s)).numpy()
    pred = sy.inverse_transform(pred_s)
    if pred.shape[1] == 1:
        pred = pred.ravel()
    return pred, epoch + 1


def main():
    c = np.load(CACHE_PATH)
    Xtr_raw, Xte_raw = c["X_train"], c["X_test"]
    y_r_tr, y_r_te = c["y_rssi_train"], c["y_rssi_test"]
    y_s_tr = c["y_snr_train"]
    log.info("train=%d test=%d", len(Xtr_raw), len(Xte_raw))

    df_tr = add_derived(Xtr_raw)[FEATS]
    df_te = add_derived(Xte_raw)[FEATS]
    Xtr_np = df_tr.to_numpy()
    Xte_np = df_te.to_numpy()

    results = []

    # === X0: XGBoost v0.5 ===
    log.info("X0 XGBoost ref")
    t0 = time.time()
    xgb_te_pred, xgb_tr_pred = train_xgb(df_tr, y_r_tr, df_te)
    r, m, b = metrics(xgb_te_pred, y_r_te)
    results.append(("X0 XGBoost v0.5", r, m, b, time.time() - t0))

    # === X1: sklearn MLP single ===
    log.info("X1 sklearn MLP single")
    t0 = time.time()
    p, _ = train_sklearn_mlp(Xtr_np, y_r_tr, Xte_np, hidden=(64, 32))
    results.append(("X1 sklearn MLP single", *metrics(p, y_r_te), time.time() - t0))

    # === X2: sklearn MLP multi ===
    log.info("X2 sklearn MLP multi")
    t0 = time.time()
    Y_multi = np.column_stack([y_r_tr, y_s_tr])
    p_multi, _ = train_sklearn_mlp(Xtr_np, Y_multi, Xte_np, hidden=(64, 32))
    results.append(("X2 sklearn MLP multi", *metrics(p_multi[:, 0], y_r_te), time.time() - t0))

    # === X3: sklearn MLP single + XGB stacking ===
    log.info("X3 sklearn MLP single + XGB stacking")
    t0 = time.time()
    Xtr_stack = np.column_stack([Xtr_np, xgb_tr_pred])
    Xte_stack = np.column_stack([Xte_np, xgb_te_pred])
    p, _ = train_sklearn_mlp(Xtr_stack, y_r_tr, Xte_stack, hidden=(64, 32))
    results.append(("X3 sklearn stack single", *metrics(p, y_r_te), time.time() - t0))

    # === X4: sklearn MLP multi + XGB stacking ===
    log.info("X4 sklearn MLP multi + XGB stacking")
    t0 = time.time()
    p_multi, _ = train_sklearn_mlp(Xtr_stack, Y_multi, Xte_stack, hidden=(64, 32))
    results.append(("X4 sklearn stack multi", *metrics(p_multi[:, 0], y_r_te), time.time() - t0))

    # === X5: PyTorch MLP single, 256-128-64 ===
    log.info("X5 PyTorch MLP single (256-128-64)")
    t0 = time.time()
    p, ep = train_torch(Xtr_np, y_r_tr, Xte_np)
    results.append((f"X5 PyTorch single (ep={ep})", *metrics(p, y_r_te), time.time() - t0))

    # === X6: PyTorch MLP multi, weighted ===
    for w_snr in [0.3, 1.0]:
        log.info("X6 PyTorch MLP multi (256-128-64), λ_snr=%.1f", w_snr)
        t0 = time.time()
        p, ep = train_torch(Xtr_np, Y_multi, Xte_np, loss_weights=[1.0, w_snr])
        results.append(
            (
                f"X6 PyTorch multi λ_snr={w_snr} (ep={ep})",
                *metrics(p[:, 0], y_r_te),
                time.time() - t0,
            )
        )

    # === X7: PyTorch stacking single ===
    log.info("X7 PyTorch stacking single")
    t0 = time.time()
    p, ep = train_torch(Xtr_stack, y_r_tr, Xte_stack)
    results.append((f"X7 PyTorch stack single (ep={ep})", *metrics(p, y_r_te), time.time() - t0))

    # === X8: PyTorch stacking multi ===
    log.info("X8 PyTorch stacking multi")
    t0 = time.time()
    p, ep = train_torch(Xtr_stack, Y_multi, Xte_stack, loss_weights=[1.0, 0.3])
    results.append(
        (f"X8 PyTorch stack multi (ep={ep})", *metrics(p[:, 0], y_r_te), time.time() - t0)
    )

    print("\n" + "=" * 78)
    print(f"RESULTS — RSSI residual on test n={len(y_r_te)} (Đà Nẵng Jan-Feb 2026)")
    print("=" * 78)
    print(f"  {'model':38s} {'RMSE':>6s} {'MAE':>6s} {'bias':>7s} {'time_s':>7s}")
    for name, r, m, b, t in results:
        print(f"  {name:38s} {r:>6.2f} {m:>6.2f} {b:>+7.2f} {t:>7.1f}")

    xgb_rmse = results[0][1]
    print()
    print(f"Reference: XGBoost v0.5 = {xgb_rmse:.2f} dB RMSE")
    print(f"{'Best non-XGB':38s}: ", end="")
    best = min(results[1:], key=lambda x: x[1])
    print(f"{best[0]} = {best[1]:.2f} dB (Δ = {best[1] - xgb_rmse:+.2f} dB vs XGB)")


if __name__ == "__main__":
    main()
