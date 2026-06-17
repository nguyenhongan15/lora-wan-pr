"""Hình 4.7 — Phân tích bias Extra Trees theo khoảng cách (temporal hold-out).

Nguồn dữ liệu: reports/seven-train/holdout_eval.json (n = 337, 4 gateway Đà Nẵng,
hold-out Jan-Feb 2026). Trực quan hoá hiện tượng over-predict ở bin gần và
under-predict nhẹ ở bin xa, đối chiếu bias trung bình toàn cục.

Output: docs/anh/hinh_4_7.png
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
EVAL = ROOT / "reports" / "seven-train" / "holdout_eval.json"
OUT = Path(__file__).resolve().parent.parent / "anh" / "hinh_4_7.png"
OUT.parent.mkdir(parents=True, exist_ok=True)

data = json.loads(EVAL.read_text(encoding="utf-8"))
overall = data["overall"]
bins = data["per_distance_bin"]

labels = [f"{b['bin_km']} km\nn = {b['n']}" for b in bins]
bias = [b["bias_db"] for b in bins]
rmse = [b["rmse_db"] for b in bins]

BLUE = "#2E5496"
GRAY = "#A6A6A6"

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.5, 4.5))

# Panel (a): Bias theo bin khoảng cách
colors = [BLUE if v >= 0 else "#C00000" for v in bias]
bars = ax1.bar(labels, bias, color=colors, edgecolor="#1F3864", linewidth=0.8)
ax1.axhline(0, color="#000000", linewidth=0.8)
ax1.axhline(
    overall["bias_db"],
    color="#7F7F7F",
    linestyle="--",
    linewidth=1.2,
    label=f"Bias toàn cục = {overall['bias_db']:+.2f} dB",
)
ax1.set_ylabel("Bias = mean(pred − meas) [dB]")
ax1.set_title("(a) Bias Extra Trees theo khoảng cách (n = 337)")
ax1.grid(axis="y", ls=":", alpha=0.5)
ax1.legend(loc="upper right", fontsize=9)
for bar, v in zip(bars, bias, strict=True):
    y_offset = 0.18 if v >= 0 else -0.32
    ax1.text(
        bar.get_x() + bar.get_width() / 2,
        v + y_offset,
        f"{v:+.2f}",
        ha="center",
        va="bottom" if v >= 0 else "top",
        fontsize=10,
        fontweight="bold",
    )

# Panel (b): Đối sánh RMSE từng bin với RMSE toàn cục
x = np.arange(len(labels))
ax2.bar(x, rmse, color=BLUE, edgecolor="#1F3864", linewidth=0.8)
ax2.axhline(
    overall["rmse_db"],
    color="#7F7F7F",
    linestyle="--",
    linewidth=1.2,
    label=f"RMSE toàn cục = {overall['rmse_db']:.2f} dB",
)
ax2.set_xticks(x)
ax2.set_xticklabels(labels)
ax2.set_ylabel("RMSE [dB]")
ax2.set_title(f"(b) RMSE theo khoảng cách · R² = {overall['r2']:.3f}")
ax2.grid(axis="y", ls=":", alpha=0.5)
ax2.legend(loc="upper right", fontsize=9)
for xi, v in zip(x, rmse, strict=True):
    ax2.text(xi, v + 0.15, f"{v:.2f}", ha="center", va="bottom", fontsize=10)

fig.suptitle(
    "Phân tích sai số Extra Trees · temporal hold-out Jan–Feb 2026 · Đà Nẵng",
    fontsize=12,
    y=1.02,
)
plt.tight_layout()
plt.savefig(OUT, dpi=180, bbox_inches="tight")
print(f"Saved: {OUT}")
