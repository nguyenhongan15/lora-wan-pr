"""Hình 4.12 — Luồng tác vụ nền (Quản trị → Hàng đợi → Tiến trình chạy nền).

Bố cục dạng cây trên-dưới:
  * Dịch vụ API / Quản trị → Hàng đợi tác vụ (Valkey) → Tiến trình chạy nền
  * Tiến trình chạy nền phân nhánh 3 tác vụ:
      - Train lại mô hình học máy → Dịch vụ học máy (Tải lại mô hình)
      - Vẽ lại bản đồ ước lượng
      - Đồng bộ nguồn dữ liệu → LPWANMapper (Kéo gói tin)

Output: docs/anh/hinh_4_12.png
"""

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import Ellipse, FancyArrowPatch, FancyBboxPatch

OUT = Path(__file__).resolve().parent.parent / "anh" / "hinh_4_12.png"
OUT.parent.mkdir(parents=True, exist_ok=True)

FILL = "#D9E2F3"
BORDER = "#2E5496"
ARROW_COLOR = "#1A3A6B"
LABEL_BG = "#EAF3DA"


def box(ax, cx, cy, w, h, text, *, fontsize=12):
    """Hộp chữ nhật bo nhẹ."""
    ax.add_patch(
        FancyBboxPatch(
            (cx - w / 2, cy - h / 2),
            w,
            h,
            boxstyle="round,pad=0.04,rounding_size=0.12",
            linewidth=1.5,
            edgecolor=BORDER,
            facecolor=FILL,
            zorder=2,
        )
    )
    ax.text(cx, cy, text, ha="center", va="center", fontsize=fontsize, color="#000000", zorder=3)


def cylinder(ax, cx, cy, w, h, text, *, fontsize=12):
    """Hình trụ — kho hàng đợi (broker)."""
    ellipse_h = h * 0.22
    body_top = cy + h / 2 - ellipse_h / 2
    body_bot = cy - h / 2 + ellipse_h / 2
    ax.add_patch(
        FancyBboxPatch(
            (cx - w / 2, body_bot),
            w,
            body_top - body_bot,
            boxstyle="square,pad=0",
            linewidth=1.5,
            edgecolor=BORDER,
            facecolor=FILL,
            zorder=2,
        )
    )
    ax.add_patch(
        Ellipse(
            (cx, body_top), w, ellipse_h, facecolor=FILL, edgecolor=BORDER, linewidth=1.5, zorder=3
        )
    )
    ax.add_patch(
        Ellipse(
            (cx, body_bot), w, ellipse_h, facecolor=FILL, edgecolor=BORDER, linewidth=1.5, zorder=2
        )
    )
    ax.text(cx, cy, text, ha="center", va="center", fontsize=fontsize, color="#000000", zorder=4)


def arrow(ax, p1, p2, *, connectionstyle="arc3,rad=0", lw=2.4):
    arr = FancyArrowPatch(
        p1,
        p2,
        arrowstyle="-|>,head_length=10,head_width=7",
        linewidth=lw,
        color=ARROW_COLOR,
        connectionstyle=connectionstyle,
        zorder=1.5,
    )
    ax.add_patch(arr)


def edge_label(ax, x, y, text, *, fontsize=10.5):
    ax.text(
        x,
        y,
        text,
        ha="center",
        va="center",
        fontsize=fontsize,
        color="#000000",
        bbox={"boxstyle": "round,pad=0.2", "facecolor": LABEL_BG, "edgecolor": "none"},
        zorder=4,
    )


fig, ax = plt.subplots(figsize=(14, 12))
ax.set_xlim(0, 14)
ax.set_ylim(0, 13.5)
ax.set_aspect("equal")
ax.set_axis_off()

# Cột giữa
CC = 7.0
LC = 2.7
RC = 11.3

# 1. Dịch vụ API / Quản trị
API_CY = 12.4
box(ax, CC, API_CY, 4.0, 1.0, "Dịch vụ API / Quản trị", fontsize=13)

# 2. Hàng đợi tác vụ (Valkey) — hình hộp 2D
BR_CY = 10.4
box(ax, CC, BR_CY, 2.6, 1.3, "Hàng đợi tác vụ\n(Valkey)", fontsize=12)

# 3. Tiến trình chạy nền
WK_CY = 8.0
box(ax, CC, WK_CY, 4.2, 1.3, "Tiến trình chạy nền\n(1 luồng)", fontsize=13)

# 4a. Train lại mô hình học máy
RT_CY = 5.0
box(
    ax,
    LC,
    RT_CY,
    4.2,
    2.0,
    "Train lại mô hình học máy\nXây CSV → Huấn luyện Extra Trees\n→ Hoán đổi mô hình",
    fontsize=11.5,
)

# 4b. Vẽ lại bản đồ ước lượng
RB_CY = 5.0
box(
    ax,
    CC,
    RB_CY,
    4.2,
    2.0,
    "Vẽ lại bản đồ ước lượng\n(P.1812 + DTM\n+ Nhiễu nền theo trạm\n+ Phủ khảo sát)",
    fontsize=11.5,
)

# 4c. Đồng bộ nguồn dữ liệu
SY_CY = 5.0
box(ax, RC, SY_CY, 4.2, 2.0, "Đồng bộ nguồn dữ liệu\n(định kỳ 20 giây)", fontsize=12)

# 5. Dịch vụ học máy
ML_CY = 1.5
box(ax, LC, ML_CY, 3.0, 1.0, "Dịch vụ học máy", fontsize=12.5)

# 6. LPWANMapper
SR_CY = 1.5
box(ax, RC, SR_CY, 3.4, 1.0, "LPWANMapper", fontsize=12.5)

# ── Mũi tên ────────────────────────────────────────────────────────
# API → Hàng đợi
arrow(ax, (CC, API_CY - 0.5), (CC, BR_CY + 0.65))
edge_label(ax, CC, 11.4, "Đẩy tác vụ")

# Hàng đợi → Tiến trình
arrow(ax, (CC, BR_CY - 0.65), (CC, WK_CY + 0.65))

# Tiến trình → 3 tác vụ
arrow(ax, (CC - 2.1, WK_CY), (LC, RT_CY + 1.0), connectionstyle="angle,angleA=180,angleB=90,rad=8")
arrow(ax, (CC, WK_CY - 0.65), (CC, RB_CY + 1.0))
arrow(ax, (CC + 2.1, WK_CY), (RC, SY_CY + 1.0), connectionstyle="angle,angleA=0,angleB=90,rad=8")

# Train → Dịch vụ học máy
arrow(ax, (LC, RT_CY - 1.0), (LC, ML_CY + 0.5))
edge_label(ax, LC, 2.8, "Tải lại mô hình")

# Đồng bộ → LPWANMapper
arrow(ax, (RC, SY_CY - 1.0), (RC, SR_CY + 0.5))
edge_label(ax, RC, 2.8, "Kéo gói tin")

plt.tight_layout()
plt.savefig(OUT, dpi=180, bbox_inches="tight")
print(f"Saved: {OUT}")
