"""Hình 4.6 — So sánh sai số mô hình (Extra Trees vs XGBoost) + RMSE theo bin khoảng cách.

Số liệu lấy từ Bảng 4.4 và 4.5 (temporal hold-out Jan-Feb 2026, n=337, 4 gateway Đà Nẵng).
Nguồn: reports/seven-train/holdout_eval.json.

Output: docs/anh/hinh_4_6.png
"""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

OUT = Path(__file__).resolve().parent.parent / "anh" / "hinh_4_6.png"
OUT.parent.mkdir(parents=True, exist_ok=True)

# (a) ET vs XGBoost — Bảng 4.4
metrics = ["RMSE", "MAE", "Bias"]
et = [7.10, 4.98, 2.61]
xgb = [10.58, 7.80, 0.77]
x = np.arange(len(metrics))
w = 0.36

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.2))

b1 = ax1.bar(x - w / 2, et, w, label="Extra Trees", color="#2E5496")
b2 = ax1.bar(x + w / 2, xgb, w, label="XGBoost v0.6", color="#A6A6A6")
ax1.set_xticks(x)
ax1.set_xticklabels(metrics)
ax1.set_ylabel("dB")
ax1.set_title("(a) Extra Trees vs XGBoost\n(temporal hold-out, n=337)")
ax1.legend(loc="upper right")
ax1.grid(axis="y", ls=":", alpha=0.5)
for bars in (b1, b2):
    for bar in bars:
        h = bar.get_height()
        ax1.text(
            bar.get_x() + bar.get_width() / 2,
            h + 0.15,
            f"{h:.2f}",
            ha="center",
            va="bottom",
            fontsize=9,
        )

# (b) RMSE theo bin khoảng cách — Bảng 4.5
bins = ["0–2 km\n(n=244)", "2–5 km\n(n=45)", "5–10 km\n(n=48)"]
rmse = [8.21, 2.32, 2.44]
bars = ax2.bar(bins, rmse, color="#2E5496")
ax2.set_ylabel("RMSE (dB)")
ax2.set_title("(b) RMSE Extra Trees theo khoảng cách")
ax2.grid(axis="y", ls=":", alpha=0.5)
for bar, v in zip(bars, rmse, strict=True):
    ax2.text(
        bar.get_x() + bar.get_width() / 2,
        v + 0.1,
        f"{v:.2f}",
        ha="center",
        va="bottom",
        fontsize=10,
    )

plt.tight_layout()
plt.savefig(OUT, dpi=180, bbox_inches="tight")
print(f"Saved: {OUT}")
