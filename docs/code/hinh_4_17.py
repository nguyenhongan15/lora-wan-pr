"""Hình 4.17 — Luồng dữ liệu cá nhân: user kéo về từ LPWAN Mapper, chưa đóng góp.

Mục đích: thể hiện giai đoạn user TỰ kéo gói tin về kho riêng (chưa đẩy lên
bản đồ chung). Ở chế độ cá nhân, user toàn quyền với dữ liệu của mình:
xem trên bản đồ riêng, xoá lô không mong muốn, giữ riêng tư, hoặc bấm
"Đóng góp" để chuyển sang luồng kiểm duyệt cộng đồng (Hình 4.16).

Output: docs/anh/hinh_4_17.png
"""

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

OUT = Path(__file__).resolve().parent.parent / "anh" / "hinh_4_17.png"
OUT.parent.mkdir(parents=True, exist_ok=True)

FILL = "#D9E2F3"
BORDER = "#2E5496"
LABEL_BG = "#EAF3DA"
REJECT_FILL = "#F8D7DA"
REJECT_BORDER = "#A12C2F"
HIGHLIGHT_FILL = "#FFF4D6"
HIGHLIGHT_BORDER = "#B8860B"
SERVER_FILL = "#F4F6F8"
SERVER_EDGE = "#2C3E50"
STORE_FILL = "#E6EEF7"
STORE_EDGE = "#2E5496"


def box(ax, cx, cy, w, h, text, *, fontsize=12, fill=FILL, border=BORDER):
    ax.add_patch(
        FancyBboxPatch(
            (cx - w / 2, cy - h / 2),
            w,
            h,
            boxstyle="round,pad=0.04,rounding_size=0.12",
            linewidth=1.5,
            edgecolor=border,
            facecolor=fill,
            zorder=2,
        )
    )
    ax.text(cx, cy, text, ha="center", va="center", fontsize=fontsize, color="#000000", zorder=3)


def arrow(ax, p1, p2, *, dashed=False, connectionstyle="arc3,rad=0", lw=1.6):
    ax.add_patch(
        FancyArrowPatch(
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


fig, ax = plt.subplots(figsize=(14, 16))
ax.set_xlim(0, 14)
ax.set_ylim(0, 18.5)
ax.set_aspect("equal")
ax.set_axis_off()

CC = 7.0

# 1. Server lpwanmapper — flat 2D box
B1_CY = 17.2
box(
    ax, CC, B1_CY, 4.2, 1.2, "Server lpwanmapper", fontsize=13, fill=SERVER_FILL, border=SERVER_EDGE
)

# 2. User bấm "Tải dữ liệu mới nhất"
B2_CY = 14.6
box(ax, CC, B2_CY, 5.4, 1.2, "Tải dữ liệu mới nhất", fontsize=13)

# 3. Đồng bộ gói tin
B3_CY = 12.0
box(ax, CC, B3_CY, 5.0, 1.2, "Đồng bộ gói tin", fontsize=13)

# 4. Bảng lưu tạm file (riêng của user) — flat 2D box
B4_CY = 9.2
box(
    ax,
    CC,
    B4_CY,
    6.0,
    1.6,
    "Bảng lưu tạm file\n(riêng của user, chưa đóng góp)",
    fontsize=12,
    fill=STORE_FILL,
    border=STORE_EDGE,
)

# 5. Chế độ cá nhân — Bản đồ "Của tôi"
B5_CY = 6.3
box(
    ax,
    CC,
    B5_CY,
    6.6,
    1.6,
    'Chế độ cá nhân  —  Bản đồ "Của tôi"\nUser toàn quyền với dữ liệu của mình',
    fontsize=12,
    fill=HIGHLIGHT_FILL,
    border=HIGHLIGHT_BORDER,
)

# 6. 3 lựa chọn của user
ACTION_CY = 2.8

# 6a. Đóng góp → luồng admin duyệt (Hình 4.16)
box(ax, 2.6, ACTION_CY, 4.0, 2.0, "Đóng góp\ncho bản đồ chung", fontsize=12)

# 6b. Xoá / chỉnh sửa
box(
    ax,
    7.0,
    ACTION_CY,
    3.8,
    2.0,
    "Xoá dữ liệu\nkhỏi hệ thống",
    fontsize=12,
    fill=REJECT_FILL,
    border=REJECT_BORDER,
)

# 6c. Giữ riêng tư
box(
    ax,
    11.2,
    ACTION_CY,
    4.0,
    2.0,
    'Giữ riêng tư\n(không thao tác)\nchỉ hiện trên bản đồ\n"Của tôi"',
    fontsize=11,
)

# ── Mũi tên ────────────────────────────────────────────────────────
# 1 → 2 (user kéo data)
arrow(ax, (CC, B1_CY - 0.6), (CC, B2_CY + 0.6))
edge_label(ax, CC, 15.95, "Kéo gói tin từ /data")

# 2 → 3
arrow(ax, (CC, B2_CY - 0.6), (CC, B3_CY + 0.6))

# 3 → 4
arrow(ax, (CC, B3_CY - 0.6), (CC, B4_CY + 0.8))

# 4 → 5 (data hiển thị trên bản đồ cá nhân)
arrow(ax, (CC, B4_CY - 0.8), (CC, B5_CY + 0.8))
edge_label(ax, CC, 7.75, "Hiển thị trên bản đồ cá nhân")

# 5 → 3 action boxes (user quyết định)
arrow(ax, (CC - 2.4, B5_CY - 0.8), (2.6, ACTION_CY + 1.0), connectionstyle="arc3,rad=-0.12")
arrow(ax, (CC, B5_CY - 0.8), (7.0, ACTION_CY + 1.0))
arrow(ax, (CC + 2.4, B5_CY - 0.8), (11.2, ACTION_CY + 1.0), connectionstyle="arc3,rad=0.12")

plt.tight_layout()
plt.savefig(OUT, dpi=180, bbox_inches="tight")
print(f"Saved: {OUT}")
