"""Hình 4.4 — Pipeline Tầng 1 ITU-R P.1812 (layout snake/U-shape).

Hàng trên trái → phải: IN → P.1812 → P.2108 → P.2109
Quay đầu xuống: P.2109 → NF
Hàng dưới phải → trái: NF → LB → OUT

(Mermaid không honor `direction` trong subgraph, nên vẽ trực tiếp matplotlib.)

Output: docs/anh/hinh_4_4.png
"""

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

OUT = Path(__file__).resolve().parent.parent / "anh" / "hinh_4_4.png"
OUT.parent.mkdir(parents=True, exist_ok=True)

FILL = "#D9E2F3"
BORDER = "#2E5496"


def box(ax, x, y, w, h, text, fontsize=13):
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


fig, ax = plt.subplots(figsize=(17, 7))
ax.set_xlim(1.2, 16.8)
ax.set_ylim(0, 7)
ax.set_axis_off()

# --- Hàng trên (LTR): IN → P1812 → P2108 → P2109 ---
TOP_Y, H_TOP = 4.6, 1.5

IN_X, IN_W = 1.5, 4.0
P1_X, P1_W = 5.9, 3.0
P2_X, P2_W = 9.3, 3.0
P3_X, P3_W = 12.7, 3.8

box(ax, IN_X, TOP_Y, IN_W, H_TOP, "Đầu vào: (lat, lon, SF, gateway[])\n+ DEM + DSM + vùng khí hậu")
box(ax, P1_X, TOP_Y, P1_W, H_TOP, "ITU-R P.1812\npath loss (terrain)")
box(ax, P2_X, TOP_Y, P2_W, H_TOP, "P.2108 clutter\n(bỏ qua nếu có DSM)")
box(ax, P3_X, TOP_Y, P3_W, H_TOP, "P.2109 building entry loss\n(nếu environment = indoor)")

# --- Hàng dưới: OUT (trái), LB (giữa), NF (phải) — căn NF dưới P2109 ---
BOT_Y, H_BOT = 1.0, 1.8

OUT_X, OUT_W = 1.5, 4.0
LB_X, LB_W = 6.2, 5.5
NF_X, NF_W = 12.7, 3.8

box(
    ax,
    OUT_X,
    BOT_Y,
    OUT_W,
    H_BOT,
    "Đầu ra: gateway phục vụ tốt nhất\nRSSI/SNR/margin UL+DL\n+ nguyên nhân nghẽn",
)
box(
    ax,
    LB_X,
    BOT_Y,
    LB_W,
    H_BOT,
    "Link budget UL/DL\nRSSI = Tx + Gains − PL − BEL\nSNR = RSSI − NF · Margin = SNR − SF_limit",
)
box(
    ax,
    NF_X,
    BOT_Y,
    NF_W,
    H_BOT,
    "Hiệu chỉnh noise floor per-gateway\n(geo.gateways.noise_floor_dbm)",
)

# --- Mũi tên ---
y_top = TOP_Y + H_TOP / 2
y_bot = BOT_Y + H_BOT / 2

# Hàng trên: trái → phải
arrow(ax, (IN_X + IN_W, y_top), (P1_X, y_top))
arrow(ax, (P1_X + P1_W, y_top), (P2_X, y_top))
arrow(ax, (P2_X + P2_W, y_top), (P3_X, y_top))

# U-turn dọc: P2109 xuống NF (cùng tâm x)
turn_x = P3_X + P3_W / 2
arrow(ax, (turn_x, TOP_Y), (turn_x, BOT_Y + H_BOT))

# Hàng dưới: phải → trái (NF → LB → OUT)
arrow(ax, (NF_X, y_bot), (LB_X + LB_W, y_bot))
arrow(ax, (LB_X, y_bot), (OUT_X + OUT_W, y_bot))

plt.tight_layout()
plt.savefig(OUT, dpi=180, bbox_inches="tight")
print(f"Saved: {OUT}")
