"""Hình 4.5 — Sơ đồ khối thuật toán dự đoán vùng phủ.

Tuân theo ký hiệu sơ đồ khối chuẩn (ISO 5807):
  * Bắt đầu / Kết thúc → hình bầu dục (oval)
  * Vào / Ra dữ liệu  → hình bình hành (parallelogram)
  * Xử lý / tính toán → hình chữ nhật (rectangle)
  * Quyết định        → hình thoi (diamond)
  * Mũi tên          → nối theo góc vuông (đường thẳng đứng/ngang)

Luồng:
  Bắt đầu → Yêu cầu dự đoán → Tầng 1 (P.1812) → [Mô hình học máy?]
                                                  ├─ Không → Trả Tầng 1 → Kết thúc
                                                  └─ Có    → Mô hình làm việc
                                                              → Trích đặc trưng
                                                              → Tổng hợp RSSI cuối
                                                              → Trả KQ dự đoán → Kết thúc
                                                  (lỗi, nét đứt) → Trả Tầng 1

Output: docs/anh/hinh_4_5.png
"""

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import Ellipse, FancyArrowPatch, FancyBboxPatch, Polygon

OUT = Path(__file__).resolve().parent.parent / "anh" / "hinh_4_5.png"
OUT.parent.mkdir(parents=True, exist_ok=True)

FILL = "#D9E2F3"
BORDER = "#2E5496"
LABEL_BG = "#EAF3DA"


def oval(ax, cx, cy, w, h, text, fontsize=13.5):
    """Hình bầu dục — Bắt đầu / Kết thúc."""
    ax.add_patch(Ellipse((cx, cy), w, h, facecolor=FILL, edgecolor=BORDER, linewidth=1.5, zorder=2))
    ax.text(
        cx,
        cy,
        text,
        ha="center",
        va="center",
        fontsize=fontsize,
        weight="bold",
        color="#000000",
        zorder=3,
    )


def rect(ax, x, y, w, h, text, fontsize=12.5):
    """Hình chữ nhật vuông góc — Xử lý."""
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="square,pad=0.02",
            linewidth=1.5,
            edgecolor=BORDER,
            facecolor=FILL,
            zorder=2,
        )
    )
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


def parallelogram(ax, cx, y, w, h, text, *, skew=0.5, fontsize=12.5):
    """Hình bình hành — Vào / Ra dữ liệu (đỉnh trên lệch phải)."""
    half_w, half_s = w / 2, skew / 2
    pts = [
        (cx - half_w + half_s, y),  # bottom-left
        (cx + half_w + half_s, y),  # bottom-right
        (cx + half_w - half_s, y + h),  # top-right
        (cx - half_w - half_s, y + h),  # top-left
    ]
    ax.add_patch(
        Polygon(pts, closed=True, facecolor=FILL, edgecolor=BORDER, linewidth=1.5, zorder=2)
    )
    ax.text(
        cx, y + h / 2, text, ha="center", va="center", fontsize=fontsize, color="#000000", zorder=3
    )


def diamond(ax, cx, cy, hw, hh, text, fontsize=12.5):
    """Hình thoi — Quyết định."""
    pts = [(cx, cy + hh), (cx + hw, cy), (cx, cy - hh), (cx - hw, cy)]
    ax.add_patch(
        Polygon(pts, closed=True, facecolor=FILL, edgecolor=BORDER, linewidth=1.5, zorder=2)
    )
    ax.text(cx, cy, text, ha="center", va="center", fontsize=fontsize, color="#000000", zorder=3)


def arrow(ax, p1, p2, *, dashed=False, lw=1.7, connectionstyle="arc3,rad=0"):
    """Mũi tên thẳng (mặc định) hoặc theo connectionstyle (cho góc vuông L-shape)."""
    arr = FancyArrowPatch(
        p1,
        p2,
        arrowstyle="->",
        mutation_scale=18,
        linewidth=lw,
        color=BORDER,
        linestyle="--" if dashed else "-",
        connectionstyle=connectionstyle,
        zorder=1,
    )
    ax.add_patch(arr)


def edge_label(ax, x, y, text, fontsize=11):
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


fig, ax = plt.subplots(figsize=(12, 16))
ax.set_xlim(0, 15)
ax.set_ylim(0, 19)
ax.set_aspect("equal")
ax.set_axis_off()

# ── Các khối ───────────────────────────────────────────────────────
CC = 7.0  # tâm cột giữa
RC = 12.0  # tâm cột phải
LC = 2.5  # tâm cột trái

# 1. Bắt đầu (oval)
START_CY = 17.7
oval(ax, CC, START_CY, 3.0, 1.0, "Bắt đầu")

# 2. Yêu cầu dự đoán (parallelogram)
IN_Y, IN_H = 15.7, 1.1
parallelogram(ax, CC, IN_Y, 4.2, IN_H, "Yêu cầu dự đoán")

# 3. Tầng 1 (rectangle)
S1_Y, S1_H = 13.5, 1.3
rect(ax, CC - 2.1, S1_Y, 4.2, S1_H, "Tầng 1\n(ITU-R P.1812)", fontsize=13)

# 4. Mô hình học máy hoạt động (diamond)
D_CY, D_HW, D_HH = 11.0, 2.6, 1.5
diamond(ax, CC, D_CY, D_HW, D_HH, "Mô hình học máy\nhoạt động", fontsize=12.5)

# 6. Trích đặc trưng (rectangle, cột phải)
B6_Y, B6_H = 6.4, 1.3
rect(ax, RC - 2.1, B6_Y, 4.2, B6_H, "Trích đặc trưng\n+ dự đoán hiệu chỉnh", fontsize=12)

# 7. Tổng hợp RSSI cuối (rectangle, cột phải)
B7_Y, B7_H = 4.3, 1.3
rect(ax, RC - 2.1, B7_Y, 4.2, B7_H, "Tổng hợp RSSI cuối\n+ chỉ số chất lượng", fontsize=12)

# 8. Trả kết quả dự đoán (parallelogram, cột phải)
B8_Y, B8_H = 2.2, 1.1
parallelogram(ax, RC, B8_Y, 4.2, B8_H, "Trả kết quả dự đoán")

# 9. Trả kết quả Tầng 1 (parallelogram, cột trái)
B4_Y, B4_H = 2.2, 1.1
parallelogram(ax, LC, B4_Y, 4.2, B4_H, "Trả kết quả Tầng 1")

# 10. Kết thúc (oval)
END_CY = 0.6
oval(ax, CC, END_CY, 3.0, 1.0, "Kết thúc")

# ── Mũi tên (góc vuông — L-shape) ──────────────────────────────────
# Bắt đầu → Yêu cầu (thẳng đứng)
arrow(ax, (CC, START_CY - 0.5), (CC, IN_Y + IN_H))
# Yêu cầu → Tầng 1 (thẳng đứng)
arrow(ax, (CC, IN_Y), (CC, S1_Y + S1_H))
# Tầng 1 → Diamond (thẳng đứng)
arrow(ax, (CC, S1_Y), (CC, D_CY + D_HH))

# Diamond Không → Trả Tầng 1 (L-shape: trái rồi xuống)
arrow(ax, (CC - D_HW, D_CY), (LC, B4_Y + B4_H), connectionstyle="angle,angleA=180,angleB=90,rad=0")
edge_label(ax, 3.4, 11.2, "Không")

# Diamond Có → Trích đặc trưng (L-shape: phải rồi xuống)
arrow(ax, (CC + D_HW, D_CY), (RC, B6_Y + B6_H), connectionstyle="angle,angleA=0,angleB=90,rad=0")
edge_label(ax, 10.6, 11.2, "Có")

# Trích đặc trưng → Tổng hợp (thẳng đứng)
arrow(ax, (RC, B6_Y), (RC, B7_Y + B7_H))
# Tổng hợp → Trả KQ dự đoán (thẳng đứng)
arrow(ax, (RC, B7_Y), (RC, B8_Y + B8_H))

# Trả KQ dự đoán → Kết thúc (L-shape: xuống rồi sang trái)
arrow(ax, (RC, B8_Y), (CC + 1.5, END_CY), connectionstyle="angle,angleA=-90,angleB=0,rad=0")
# Trả KQ Tầng 1 → Kết thúc (L-shape: xuống rồi sang phải)
arrow(ax, (LC, B4_Y), (CC - 1.5, END_CY), connectionstyle="angle,angleA=-90,angleB=180,rad=0")

plt.tight_layout()
plt.savefig(OUT, dpi=180, bbox_inches="tight")
print(f"Saved: {OUT}")
