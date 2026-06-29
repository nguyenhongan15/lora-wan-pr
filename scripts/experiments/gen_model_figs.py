"""Sinh biểu đồ đánh giá model đang deploy (pred-vs-measured, error-vs-distance).

Chạy trong celery-worker (có model + CSV + matplotlib):
    docker compose exec -T celery-worker python /app/scripts/experiments/gen_model_figs.py
"""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

DATA = Path("/app/services/ml-service/data")
CSV = DATA / "training/processed/devices_history_full.csv"
OUT = Path("/app/reports")

model = joblib.load(DATA / "extra_trees_model.joblib")
meta = json.loads((DATA / "model_meta.json").read_text())
feats = meta["all_features"]
residual = meta.get("target_kind") == "residual"

df = pd.read_csv(CSV)
df = df[df["stage1_rssi_dbm"].notna()]
test = df[df["data_split"] == "test"].reset_index(drop=True)
pred = model.predict(test[feats])
pred_rssi = pred + test["stage1_rssi_dbm"].to_numpy() if residual else pred
actual = test["rssi"].to_numpy()
err = pred_rssi - actual
rmse = float(np.sqrt(np.mean(err**2)))
r2 = float(1 - np.sum(err**2) / np.sum((actual - actual.mean()) ** 2))
dist_km = test["distance"].to_numpy() / 1000.0

# Fig 1: predicted vs measured
fig, ax = plt.subplots(figsize=(6, 6))
ax.scatter(actual, pred_rssi, s=8, alpha=0.35, color="#1f77b4")
lo, hi = min(actual.min(), pred_rssi.min()), max(actual.max(), pred_rssi.max())
ax.plot([lo, hi], [lo, hi], "r--", lw=1.5, label="y = x (lý tưởng)")
ax.set_xlabel("RSSI đo thực (dBm)")
ax.set_ylabel("RSSI dự đoán (dBm)")
ax.set_title(f"Dự đoán vs Đo thực (test holdout, n={len(actual)})\nRMSE={rmse:.2f} dB, R²={r2:.3f}")
ax.legend(loc="upper left")
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(OUT / "fig_pred_vs_measured.png", dpi=140)
print(f"saved fig_pred_vs_measured.png  rmse={rmse:.2f} r2={r2:.3f} n={len(actual)}")

# Fig 2: error vs distance (binned mean ± std)
bins = [0, 0.5, 1, 2, 5, 10, 50]
labels = ["0-0.5", "0.5-1", "1-2", "2-5", "5-10", "10-50"]
means, stds, ns = [], [], []
for i in range(len(bins) - 1):
    m = (dist_km >= bins[i]) & (dist_km < bins[i + 1])
    if m.any():
        means.append(float(np.mean(err[m])))
        stds.append(float(np.std(err[m])))
        ns.append(int(m.sum()))
    else:
        means.append(0.0)
        stds.append(0.0)
        ns.append(0)
fig, ax = plt.subplots(figsize=(7, 4.5))
x = np.arange(len(labels))
ax.bar(x, means, yerr=stds, capsize=4, color="#2ca02c", alpha=0.75)
ax.axhline(0, color="k", lw=0.8)
for i, n in enumerate(ns):
    ax.text(i + 0.22, means[i], f"n={n}", ha="left", va="bottom", fontsize=8)
ax.set_xticks(x)
ax.set_xticklabels(labels)
ax.set_xlabel("Khoảng cách thiết bị–gateway (km)")
ax.set_ylabel("Sai số dự đoán (dB)  [dự đoán − đo]")
ax.grid(alpha=0.3, axis="y")
fig.tight_layout()
fig.savefig(OUT / "fig_error_vs_distance.png", dpi=140)
print("saved fig_error_vs_distance.png")
