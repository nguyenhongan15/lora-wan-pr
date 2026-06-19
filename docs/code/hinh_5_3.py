"""Hinh 5.3 - Phan tang du lieu theo o luoi H3 (2D hex grid minh hoa).

Ve mot luoi luc giac va to mau:
  - Xanh la: o huan luyen (train)
  - Cam: o xac thuc (val)
  - Do: o kiem thu (test)
Khong dung thu vien h3 - chi minh hoa.

Output: docs/anh/hinh_5_3.png
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Patch, RegularPolygon

OUT = Path(__file__).resolve().parent.parent / "anh" / "hinh_5_3.png"
OUT.parent.mkdir(parents=True, exist_ok=True)

plt.rcParams["font.family"] = ["Segoe UI", "DejaVu Sans"]

fig, ax = plt.subplots(figsize=(12, 8))

R = 0.55
DX = R * np.sqrt(3)
DY = R * 1.5

rng = np.random.default_rng(7)
cells = []
for row in range(9):
    for col in range(13):
        x = col * DX + (DX / 2 if row % 2 else 0)
        y = row * DY
        cells.append((x, y, row, col))

n = len(cells)
labels = np.array(["train"] * n, dtype=object)
val_idx = rng.choice(n, size=int(n * 0.20), replace=False)
labels[val_idx] = "val"
remaining = [i for i in range(n) if i not in set(val_idx)]
test_idx = rng.choice(remaining, size=int(n * 0.10), replace=False)
labels[test_idx] = "test"

COLOR = {"train": "#9FCFAE", "val": "#F4C78C", "test": "#E59FB9"}
LABEL_VI = {"train": "Ô huấn luyện", "val": "Ô xác thực", "test": "Ô kiểm thử"}

for (x, y, _, _), lab in zip(cells, labels, strict=False):
    hex_p = RegularPolygon(
        (x, y),
        numVertices=6,
        radius=R,
        orientation=np.radians(30),
        facecolor=COLOR[lab],
        edgecolor="#1a3a72",
        linewidth=1.1,
        alpha=0.92,
    )
    ax.add_patch(hex_p)

ax.set_xlim(-DX, 13 * DX + DX)
ax.set_ylim(-DY, 9 * DY)
ax.set_aspect("equal")
ax.set_axis_off()

legend_items = [
    Patch(
        facecolor=COLOR[k],
        edgecolor="#1a3a72",
        label=f"{LABEL_VI[k]} ({int((labels == k).mean() * 100)} %)",
    )
    for k in ["train", "val", "test"]
]
ax.legend(
    handles=legend_items,
    loc="upper center",
    bbox_to_anchor=(0.5, -0.02),
    ncol=3,
    fontsize=12,
    frameon=False,
)

ax.text(
    0.5,
    1.02,
    "Mỗi ô lục giác ≈ 0,74 km² — Tập kiểm thử không trùng ô với tập huấn luyện",
    transform=ax.transAxes,
    ha="center",
    fontsize=10.5,
    color="#555",
    style="italic",
)

plt.tight_layout()
plt.savefig(OUT, dpi=180, bbox_inches="tight")
print(f"Saved: {OUT}")
