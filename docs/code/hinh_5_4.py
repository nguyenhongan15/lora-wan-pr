"""Hinh 5.4 - Tach thanh 2 anh rieng:
  hinh_5_4a.png - RMSE / MAE tren 3 tap (huan luyen / xac thuc / kiem thu).
  hinh_5_4b.png - RMSE tap kiem thu chia theo khoang cach.

So lieu thuc tu reports/retrain-fa3ce80d.../summary.json
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

OUT_DIR = Path(__file__).resolve().parent.parent / "anh"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_A = OUT_DIR / "hinh_5_4a.png"
OUT_B = OUT_DIR / "hinh_5_4b.png"

plt.rcParams["font.family"] = ["Segoe UI", "DejaVu Sans"]

# ---------------------------------------------------------------
# Hinh 5.4a - RMSE / MAE tren 3 tap
# ---------------------------------------------------------------
splits = ["Huấn luyện", "Xác thực", "Kiểm thử"]
rmse = [4.07, 7.38, 6.32]
mae = [2.46, 5.50, 4.75]

fig1, ax1 = plt.subplots(figsize=(8, 6))

x = np.arange(len(splits))
w = 0.36
bars1 = ax1.bar(x - w / 2, rmse, w, color="#1a3a72", label="RMSE (dB)")
bars2 = ax1.bar(x + w / 2, mae, w, color="#F4C78C", edgecolor="#a8761a", label="MAE (dB)")

for b, v in zip(bars1, rmse, strict=False):
    ax1.text(
        b.get_x() + b.get_width() / 2, v + 0.15, f"{v:.2f}", ha="center", fontsize=12, weight="bold"
    )
for b, v in zip(bars2, mae, strict=False):
    ax1.text(b.get_x() + b.get_width() / 2, v + 0.15, f"{v:.2f}", ha="center", fontsize=12)

ax1.set_xticks(x)
ax1.set_xticklabels(splits, fontsize=13)
ax1.set_ylabel("Sai số (dB)", fontsize=13)
ax1.legend(fontsize=12)
ax1.grid(True, alpha=0.3, axis="y")
ax1.set_ylim(0, max(rmse) * 1.25)

plt.tight_layout()
plt.savefig(OUT_A, dpi=180, bbox_inches="tight")
plt.close(fig1)
print(f"Saved: {OUT_A}")

# ---------------------------------------------------------------
# Hinh 5.4b - RMSE tap kiem thu theo khoang cach
# ---------------------------------------------------------------
bin_labels = ["0 – 2 km", "2 – 5 km", "5 – 10 km", "10 – 50 km"]
bin_rmse = [7.11, 9.26, 3.77, 3.83]
bin_n = [862, 150, 276, 348]
bin_acc = [53.5, 20.7, 81.9, 81.3]  # do chinh xac +-5 dB (%)

fig2, ax2 = plt.subplots(figsize=(9, 6))
x_pos = np.arange(len(bin_labels))

bars3 = ax2.bar(
    x_pos, bin_rmse, color="#9FCFAE", edgecolor="#2f6b3d", linewidth=1.2, label="RMSE (dB)"
)
for b, v, n in zip(bars3, bin_rmse, bin_n, strict=False):
    ax2.text(
        b.get_x() + b.get_width() / 2, v + 0.2, f"{v:.2f} dB\n(n={n})", ha="center", fontsize=11
    )
ax2.set_ylabel("RMSE tập kiểm thử (dB)", fontsize=13, color="#2f6b3d")
ax2.set_xlabel("Khoảng cách thiết bị – gateway", fontsize=13)
ax2.set_xticks(x_pos)
ax2.set_xticklabels(bin_labels, fontsize=12)
ax2.tick_params(axis="y", labelcolor="#2f6b3d")
ax2.grid(True, alpha=0.3, axis="y")
ax2.set_ylim(0, max(bin_rmse) * 1.40)

# Truc phu - do chinh xac (%)
ax2b = ax2.twinx()
ax2b.plot(
    x_pos,
    bin_acc,
    color="#C44E4E",
    marker="o",
    markersize=11,
    linewidth=2.4,
    label="Độ chính xác ±5 dB (%)",
    zorder=5,
)
for xp, acc in zip(x_pos, bin_acc, strict=False):
    ax2b.text(
        xp, acc + 4.5, f"{acc:.1f}%", ha="center", fontsize=11.5, color="#C44E4E", weight="bold"
    )
ax2b.set_ylabel("Độ chính xác trong sai số ±5 dB (%)", fontsize=13, color="#C44E4E")
ax2b.tick_params(axis="y", labelcolor="#C44E4E")
ax2b.set_ylim(0, 110)

# Chu thich gop hai truc
lines1, labels1 = ax2.get_legend_handles_labels()
lines2, labels2 = ax2b.get_legend_handles_labels()
ax2.legend(lines1 + lines2, labels1 + labels2, loc="upper center", fontsize=11, frameon=True)

plt.tight_layout()
plt.savefig(OUT_B, dpi=180, bbox_inches="tight")
plt.close(fig2)
print(f"Saved: {OUT_B}")
