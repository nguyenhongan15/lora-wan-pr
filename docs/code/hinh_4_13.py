"""Hình 4.13 — Luồng theo dõi trực tiếp điểm đo (cải tiến, qua LPWAN Mapper).

Mô hình PULL view-only: trình duyệt hỏi định kỳ → Dịch vụ API gọi adapter
LPWAN Mapper (cache phiên + đăng nhập lại nếu hết hạn) → lọc theo mốc thời
gian + tra UUID trạm thu từ CSDL → trả thẳng về trình duyệt (KHÔNG ghi DB).

Output: docs/anh/hinh_4_13.png
"""

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

OUT = Path(__file__).resolve().parent.parent / "anh" / "hinh_4_13.png"
OUT.parent.mkdir(parents=True, exist_ok=True)

FILL = "#D9E2F3"
BORDER = "#2E5496"
LABEL_BG = "#EAF3DA"
CUBE_FILL = "#F4F6F8"
CUBE_EDGE = "#2C3E50"


def box(ax, cx, cy, w, h, text, *, fontsize=12):
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


def ext_box(ax, cx, cy, w, h, text, *, fontsize=11.5):
    """Hộp 2D — nguồn ngoài hệ thống (màu xám trung tính)."""
    ax.add_patch(
        FancyBboxPatch(
            (cx - w / 2, cy - h / 2),
            w,
            h,
            boxstyle="round,pad=0.04,rounding_size=0.12",
            linewidth=1.5,
            edgecolor=CUBE_EDGE,
            facecolor=CUBE_FILL,
            zorder=2,
        )
    )
    ax.text(cx, cy, text, ha="center", va="center", fontsize=fontsize, color="#000000", zorder=3)


def arrow(ax, p1, p2, *, connectionstyle="arc3,rad=0", lw=1.7):
    ax.add_patch(
        FancyArrowPatch(
            p1,
            p2,
            arrowstyle="->",
            mutation_scale=18,
            linewidth=lw,
            color=BORDER,
            connectionstyle=connectionstyle,
            zorder=1,
        )
    )


def edge_label(ax, x, y, text, *, fontsize=10.5):
    ax.text(
        x,
        y,
        text,
        ha="center",
        va="center",
        fontsize=fontsize,
        color="#000000",
        bbox={"boxstyle": "round,pad=0.22", "facecolor": LABEL_BG, "edgecolor": "none"},
        zorder=4,
    )


fig, ax = plt.subplots(figsize=(13, 13))
ax.set_xlim(0, 13)
ax.set_ylim(0, 14.5)
ax.set_aspect("equal")
ax.set_axis_off()

CC = 6.5

# 1. Trình duyệt (đầu vào yêu cầu)
B1_CY = 13.3
box(ax, CC, B1_CY, 5.6, 1.0, "Bảng điều khiển khảo sát  (trình duyệt)", fontsize=13)

# 2. Dịch vụ API — pha yêu cầu (cache phiên đăng nhập)
B2_CY = 10.4
box(
    ax,
    CC,
    B2_CY,
    7.4,
    1.7,
    "Theo dõi trực tiếp\n"
    "Cache phiên đăng nhập trong bộ nhớ\n"
    "(đăng nhập lại nếu mã thông báo hết hạn)",
    fontsize=12,
)

# 3. Server lpwanmapper — cube 3D (external)
B3_CY = 7.3
ext_box(ax, CC, B3_CY, 4.6, 1.2, "Server lpwanmapper\n(api.lpwanmapper.com/data)", fontsize=12)

# 4. Dịch vụ API — pha xử lý phản hồi
B4_CY = 4.1
box(
    ax,
    CC,
    B4_CY,
    7.8,
    1.9,
    "Xử lý phản hồi\n"
    "Lọc gói tin theo mốc thời gian\n"
    "+ tra UUID trạm thu từ CSDL geo.gateways\n"
    "KHÔNG ghi cơ sở dữ liệu",
    fontsize=12,
)

# 5. Trả về trình duyệt (vẽ điểm đo)
B5_CY = 1.1
box(ax, CC, B5_CY, 5.6, 1.0, "Vẽ điểm đo lên bản đồ  (trình duyệt)", fontsize=13)

# ── Mũi tên + nhãn ─────────────────────────────────────────────────
# 1 → 2
arrow(ax, (CC, B1_CY - 0.5), (CC, B2_CY + 0.85))
edge_label(ax, CC, 12.0, "Hỏi định kỳ  (mặc định 15 giây, chỉnh được 5–600)")

# 2 → 3
arrow(ax, (CC, B2_CY - 0.85), (CC, B3_CY + 0.6))
edge_label(ax, CC, 8.8, "Yêu cầu /data  (kèm mã thông báo)")

# 3 → 4
arrow(ax, (CC, B3_CY - 0.6), (CC, B4_CY + 0.95))
edge_label(ax, CC, 5.7, "Trả về danh sách gói tin gần nhất")

# 4 → 5
arrow(ax, (CC, B4_CY - 0.95), (CC, B5_CY + 0.5))
edge_label(ax, CC, 2.3, "Trả JSON về trình duyệt")

# Side note: idle timeout
ax.text(
    12.7,
    10.4,
    "Tự dừng\nsau 15 phút\nkhông thao tác",
    ha="right",
    va="center",
    fontsize=10.5,
    style="italic",
    color="#555555",
    bbox={
        "boxstyle": "round,pad=0.3",
        "facecolor": "#FFFFFF",
        "edgecolor": "#999999",
        "linestyle": "--",
    },
)

plt.tight_layout()
plt.savefig(OUT, dpi=180, bbox_inches="tight")
print(f"Saved: {OUT}")
