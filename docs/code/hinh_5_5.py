"""Hinh 5.5 - Kien truc 2 tang: Tang 1 (ITU-R P.1812) + Tang 2 (Extra Trees residual).

Cot trai: Tang 1 vat ly -> RSSI thuoc co so.
Cot phai: Tang 2 hoc may -> Delta hieu chinh.
Hop nhat: RSSI cuoi = RSSI Tang 1 + Delta.
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

OUT = Path(__file__).resolve().parent.parent / "anh" / "hinh_5_5.png"
OUT.parent.mkdir(parents=True, exist_ok=True)

plt.rcParams["font.family"] = ["Segoe UI", "DejaVu Sans"]

BORDER = "#1a3a72"
FILL1 = "#D9E2F3"  # tang 1 - xanh nhat
FILL2 = "#F4D8A8"  # tang 2 - cam nhat
FILL_OUT = "#9FCFAE"
SUB = "#EAF3DA"

fig, ax = plt.subplots(figsize=(13, 9))
ax.set_xlim(0, 13)
ax.set_ylim(0, 11)
ax.set_aspect("equal")
ax.set_axis_off()


def block(cx, cy, w, h, title, sub, *, fill=FILL1, weight="bold"):
    x, y = cx - w / 2, cy - h / 2
    ax.add_patch(
        FancyBboxPatch(
            (x, y), w, h, boxstyle="round,pad=0.05", facecolor=fill, edgecolor=BORDER, linewidth=1.8
        )
    )
    if sub:
        ax.text(
            cx, cy + 0.45, title, ha="center", va="center", fontsize=13, weight=weight, color=BORDER
        )
        ax.text(cx, cy - 0.55, sub, ha="center", va="center", fontsize=13, color="#222")
    else:
        ax.text(cx, cy, title, ha="center", va="center", fontsize=13, weight=weight, color=BORDER)


def arrow(p1, p2, label=None, dashed=False):
    style = "--" if dashed else "-"
    ax.add_patch(
        FancyArrowPatch(
            p1, p2, arrowstyle="->", mutation_scale=22, linewidth=2, color=BORDER, linestyle=style
        )
    )
    if label:
        mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
        ax.text(
            mx,
            my,
            label,
            fontsize=13,
            color="#444",
            bbox={"boxstyle": "round,pad=0.25", "facecolor": SUB, "edgecolor": "none"},
        )


# Header
ax.text(
    3.0,
    10.4,
    "Mô hình vật lý truyền sóng",
    ha="center",
    fontsize=13,
    weight="bold",
    color="#1a3a72",
)
ax.text(10.0, 10.4, "Mô hình học máy", ha="center", fontsize=13, weight="bold", color="#a8761a")

# Input chung
block(6.5, 9.4, 5.5, 1.0, "Yêu cầu dự đoán", "", fill="#F4F7FA", weight="bold")

# Cot trai - Tang 1
block(3.0, 7.5, 4.4, 1.3, "Mô hình ITU-R P.1812", "", fill=FILL1)
block(3.0, 5.4, 4.4, 1.3, "Bản đồ độ cao số (DEM)", "", fill=FILL1)
block(3.0, 3.3, 4.4, 1.3, "RSSI Mô hình ITU", "", fill=FILL1)

# Cot phai - Tang 2
block(10.0, 7.5, 4.4, 1.3, "Trích 21 đặc trưng", "", fill=FILL2)
block(10.0, 5.4, 4.4, 1.3, "Mô hình Extra Trees", "", fill=FILL2)
block(10.0, 3.3, 4.4, 1.3, "Δ hiệu chỉnh", "", fill=FILL2)

# Hop nhat
block(6.5, 1.3, 5.5, 1.2, "Kết quả dự đoán", "", fill=FILL_OUT)

# Mui ten doc - Tang 1
arrow((6.5 - 1.5, 9.4 - 0.5), (3.0, 7.5 + 0.65))
arrow((3.0, 7.5 - 0.65), (3.0, 5.4 + 0.65))
arrow((3.0, 5.4 - 0.65), (3.0, 3.3 + 0.65))

# Mui ten doc - Tang 2
arrow((6.5 + 1.5, 9.4 - 0.5), (10.0, 7.5 + 0.65))
arrow((10.0, 7.5 - 0.65), (10.0, 5.4 + 0.65))
arrow((10.0, 5.4 - 0.65), (10.0, 3.3 + 0.65))

# Hoi tu vao hop nhat
arrow((3.0, 3.3 - 0.65), (6.5 - 1.5, 1.3 + 0.6))
arrow((10.0, 3.3 - 0.65), (6.5 + 1.5, 1.3 + 0.6))

# Mui ten fallback Tang 2 -> bo qua, du phong
ax.text(
    11.5,
    4.4,
    "Nếu Tầng 2 lỗi:\nΔ = 0",
    fontsize=13,
    color="#a8761a",
    style="italic",
    bbox={
        "boxstyle": "round,pad=0.3",
        "facecolor": "#FBF1DE",
        "edgecolor": "#a8761a",
        "linewidth": 0.8,
    },
)

plt.tight_layout()
plt.savefig(OUT, dpi=180, bbox_inches="tight")
print(f"Saved: {OUT}")
