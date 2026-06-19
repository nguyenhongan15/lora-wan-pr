"""Hình 4.4 — Pipeline Tầng 1 (lan truyền sóng theo Khuyến nghị ITU-R).

Bố cục dạng "rắn" (snake/U-shape) — sau khi bỏ ô P.2109:
  * Hàng trên (trái→phải):  Đầu vào → P.1812 → P.2108
  * Khúc quay (xuống):       P.2108 → Hiệu chỉnh nhiễu nền theo trạm
  * Hàng dưới (phải→trái):   Nhiễu nền → Cân đối đường truyền → Đầu ra

Output: docs/anh/hinh_4_4.png
"""

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

OUT = Path(__file__).resolve().parent.parent / "anh" / "hinh_4_4.png"
OUT.parent.mkdir(parents=True, exist_ok=True)

FILL = "#D9E2F3"
BORDER = "#2E5496"


def box(ax, x, y, w, h, text, fontsize=12):
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.04,rounding_size=0.15",
        linewidth=1.5,
        edgecolor=BORDER,
        facecolor=FILL,
        zorder=2,
    )
    ax.add_patch(patch)
    ax.text(
        x + w / 2,
        y + h / 2,
        text,
        ha="center",
        va="center",
        fontsize=fontsize,
        color="#000000",
        zorder=3,
    )


def arrow(ax, p1, p2, lw=1.8):
    arr = FancyArrowPatch(
        p1,
        p2,
        arrowstyle="->",
        mutation_scale=20,
        linewidth=lw,
        color=BORDER,
        zorder=1,
    )
    ax.add_patch(arr)


fig, ax = plt.subplots(figsize=(15, 7.5))
ax.set_xlim(0, 14.5)
ax.set_ylim(0, 7.2)
ax.set_axis_off()

# --- Hàng trên (trái → phải): Đầu vào → P.1812 → P.2108 ---
TOP_Y, H_TOP = 4.6, 1.7

IN_X, IN_W = 0.5, 4.0
P1_X, P1_W = 5.0, 4.0
P2_X, P2_W = 9.5, 4.0

box(
    ax,
    IN_X,
    TOP_Y,
    IN_W,
    H_TOP,
    "Đầu vào",
    fontsize=22,
)
box(
    ax,
    P1_X,
    TOP_Y,
    P1_W,
    H_TOP,
    "ITU-R P.1812\nTính suy hao đường truyền\ntheo địa hình",
    fontsize=18,
)
box(
    ax,
    P2_X,
    TOP_Y,
    P2_W,
    H_TOP,
    "ITU-R P.2108\nTính suy hao vật cản",
    fontsize=18,
)

# --- Hàng dưới (phải → trái): Nhiễu nền → Cân đối → Đầu ra ---
BOT_Y, H_BOT = 1.5, 1.7

OUT_X, OUT_W = 0.5, 4.0
LB_X, LB_W = 5.0, 4.0
NF_X, NF_W = 9.5, 4.0

box(
    ax,
    OUT_X,
    BOT_Y,
    OUT_W,
    H_BOT,
    "Đầu ra",
    fontsize=22,
)
box(
    ax,
    LB_X,
    BOT_Y,
    LB_W,
    H_BOT,
    "Cân đối đường truyền",
    fontsize=22,
)
box(
    ax,
    NF_X,
    BOT_Y,
    NF_W,
    H_BOT,
    "Hiệu chỉnh mức nhiễu nền\ntheo từng trạm thu",
    fontsize=18,
)

# --- Mũi tên ---
y_top = TOP_Y + H_TOP / 2
y_bot = BOT_Y + H_BOT / 2

# Hàng trên: trái → phải
arrow(ax, (IN_X + IN_W, y_top), (P1_X, y_top))
arrow(ax, (P1_X + P1_W, y_top), (P2_X, y_top))

# Khúc U-turn dọc: P.2108 (trên) → Nhiễu nền (dưới), cùng tâm x
turn_x = P2_X + P2_W / 2
arrow(ax, (turn_x, TOP_Y), (turn_x, BOT_Y + H_BOT))

# Hàng dưới: phải → trái (Nhiễu nền → Cân đối → Đầu ra)
arrow(ax, (NF_X, y_bot), (LB_X + LB_W, y_bot))
arrow(ax, (LB_X, y_bot), (OUT_X + OUT_W, y_bot))

plt.tight_layout()
plt.savefig(OUT, dpi=180, bbox_inches="tight")
print(f"Saved: {OUT}")
