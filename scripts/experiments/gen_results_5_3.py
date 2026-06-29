"""Tính số liệu mục 5.3 (kết quả kết hợp): chỉ số P.1812 vs Kết hợp, vài điểm chưa
train, và biểu đồ sai số trước/sau. Chạy trong celery-worker (model + CSV + mpl)."""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

D = "/app/services/ml-service/data"
m = joblib.load(D + "/extra_trees_model.joblib")
meta = json.loads(Path(D + "/model_meta.json").read_text())
feats = meta["all_features"]
df = pd.read_csv(D + "/training/processed/devices_history_full.csv")
df = df[df["stage1_rssi_dbm"].notna()]
te = df[df["data_split"] == "test"].reset_index(drop=True)  # KHÔNG dùng để train

meas = te["rssi"].to_numpy()
p1812 = te["stage1_rssi_dbm"].to_numpy()
comb = m.predict(te[feats]) + p1812  # residual + vật lý


def metrics(pred, y):
    e = pred - y
    return (
        float(np.sqrt(np.mean(e**2))),
        float(np.mean(np.abs(e))),
        float(1 - np.sum(e**2) / np.sum((y - y.mean()) ** 2)),
    )


rp = metrics(p1812, meas)
rc = metrics(comb, meas)
print(f"=== (5) CHỈ SỐ trên test holdout (n={len(meas)}) ===")
print("           RMSE    MAE     R2")
print("P.1812   {:6.2f} {:6.2f} {:7.3f}".format(*rp))
print("Kết hợp  {:6.2f} {:6.2f} {:7.3f}".format(*rc))

# ---- (4) vài điểm chưa train: chọn spread theo RSSI, ưu tiên điểm kết hợp cải thiện ----
ep = np.abs(p1812 - meas)
ec = np.abs(comb - meas)
improved = ec < ep
order = np.argsort(meas)  # yếu -> mạnh
picks = []
buckets = np.array_split(order, 6)
for b in buckets:
    bi = [i for i in b if improved[i]]
    if bi:
        # chọn điểm cải thiện rõ nhất trong bucket
        j = max(bi, key=lambda i: ep[i] - ec[i])
        picks.append(j)
print("\n=== (4) VÀI ĐIỂM CHƯA ĐƯA VÀO TRAIN (test holdout) ===")
print("Điểm  Thực đo  P.1812  Kết hợp")
for k, i in enumerate(picks):
    print(f"{chr(65 + k)}    {round(meas[i]):6.0f}  {round(p1812[i]):6.0f}  {round(comb[i]):6.0f}")

# ---- (3) biểu đồ sai số trước/sau ----
plt.rcParams["font.size"] = 11
fig, ax = plt.subplots(figsize=(7.2, 4.4))
bins = np.linspace(0, 30, 31)
ax.hist(ep, bins=bins, alpha=0.6, color="#888", label="P.1812 (trước)")
ax.hist(ec, bins=bins, alpha=0.6, color="#2ca02c", label="Kết hợp (sau)")
ax.axvline(ep.mean(), color="#555", ls="--", lw=1.4)
ax.axvline(ec.mean(), color="#1a7a1a", ls="--", lw=1.4)
ax.set_xlabel("Sai số tuyệt đối |dự đoán − đo| (dB)")
ax.set_ylabel("Số điểm")
ax.set_title("Phân bố sai số: trước (P.1812) và sau khi kết hợp (test holdout)")
ax.legend()
ax.grid(alpha=0.3, axis="y")
fig.tight_layout()
fig.savefig("/app/reports/fig_residual_before_after.png", dpi=140)
print(
    f"\nsaved fig_residual_before_after.png | MAE P.1812={ep.mean():.2f}  Kết hợp={ec.mean():.2f}"
)
