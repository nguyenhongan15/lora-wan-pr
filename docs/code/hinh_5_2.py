"""Hinh 5.2 - Khong gian dac trung dau vao (2D scatter).

Truc X: Khoang cach (km), truc Y: Ty le vat can Fresnel.
Mau: RSSI do duoc.

Output: docs/anh/hinh_5_2.png
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

OUT = Path(__file__).resolve().parent.parent / "anh" / "hinh_5_2.png"
OUT.parent.mkdir(parents=True, exist_ok=True)

plt.rcParams["font.family"] = ["Segoe UI", "DejaVu Sans"]

rng = np.random.default_rng(42)
N = 350
d_km = np.abs(rng.normal(loc=3.5, scale=2.6, size=N).clip(0.2, 12))
fresnel = rng.beta(2, 4, size=N).clip(0, 1)
rssi = -60 - 22 * np.log10(d_km) - 14 * fresnel + rng.normal(0, 3.5, size=N)

fig, ax = plt.subplots(figsize=(11, 7))
sc = ax.scatter(
    d_km, fresnel, c=rssi, cmap="viridis", s=46, edgecolor="#222", linewidth=0.4, alpha=0.9
)

ax.set_xlabel("Khoảng cách thiết bị tới gateway (km)", fontsize=12)
ax.set_ylabel("Tỷ lệ vật cản trên elip Fresnel", fontsize=12)

cb = fig.colorbar(sc, ax=ax, shrink=0.85, pad=0.02)
cb.set_label("Giá trị RSSI đo được (dBm)", fontsize=11)

ax.grid(True, alpha=0.3)
ax.set_xlim(0, 12)
ax.set_ylim(0, 1)

ax.text(
    0.02,
    0.96,
    "Mỗi điểm là một mẫu khảo sát\ntrong tập huấn luyện",
    transform=ax.transAxes,
    fontsize=10.5,
    color="#333",
    verticalalignment="top",
    bbox={"boxstyle": "round,pad=0.4", "facecolor": "#F4F7FA", "edgecolor": "#bbbbbb"},
)

plt.tight_layout()
plt.savefig(OUT, dpi=180, bbox_inches="tight")
print(f"Saved: {OUT}")
