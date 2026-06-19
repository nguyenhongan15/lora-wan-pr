"""Hình 4.16 — Luồng kiểm duyệt lô dữ liệu khảo sát (cải tiến, qua LPWAN Mapper).

Bám baseline architecture: nguồn duy nhất là Server lpwanmapper, mọi trạm thu
đã đăng ký upstream → không có khái niệm "trạm lạ chờ duyệt". Quản trị viên
chỉ có 2 lựa chọn: duyệt cả lô hoặc từ chối cả lô.

Luồng:
  Server lpwanmapper → Đồng bộ → Bảng kiểm dịch điểm đo (theo lô)
   → Quản trị viên duyệt: {Duyệt cả lô → Bảng dữ liệu khảo sát; Từ chối cả lô}
   → Đặt lại mốc dựng bản đồ → (tuỳ chọn) Train lại mô hình học máy

Output: docs/anh/hinh_4_16.png
"""

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

OUT = Path(__file__).resolve().parent.parent / "anh" / "hinh_4_16.png"
OUT.parent.mkdir(parents=True, exist_ok=True)

FILL = "#D9E2F3"
BORDER = "#2E5496"
LABEL_BG = "#EAF3DA"
REJECT_FILL = "#F8D7DA"
REJECT_BORDER = "#A12C2F"


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


def arrow(ax, p1, p2, *, dashed=False, connectionstyle="arc3,rad=0", lw=2.2):
    ax.add_patch(
        FancyArrowPatch(
            p1,
            p2,
            arrowstyle="-|>",
            mutation_scale=24,
            linewidth=lw,
            color=BORDER,
            linestyle="--" if dashed else "-",
            connectionstyle=connectionstyle,
            shrinkA=2,
            shrinkB=2,
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


fig, ax = plt.subplots(figsize=(13, 16))
ax.set_xlim(0, 13)
ax.set_ylim(0, 18.5)
ax.set_aspect("equal")
ax.set_axis_off()

CC = 6.5

# 1. Server lpwanmapper (ngoài hệ thống)
B1_CY = 17.0
box(ax, CC, B1_CY, 4.4, 1.2, "Server lpwanmapper", fontsize=13)

# 2. Đồng bộ gói tin (kéo định kỳ)
B2_CY = 14.4
box(ax, CC, B2_CY, 5.4, 1.2, "Đồng bộ gói tin", fontsize=13)

# 3. Bảng kiểm dịch điểm đo
B3_CY = 11.5
box(ax, CC, B3_CY, 5.0, 1.5, "Bảng lưu tạm file", fontsize=13)

# 4. Quản trị viên duyệt theo lô
B4_CY = 8.0
box(ax, CC, B4_CY, 4.0, 1.2, "Admin duyệt file", fontsize=13)

# 5a. Từ chối cả lô — trái
B5L_CY = 5.0
box(
    ax,
    2.0,
    B5L_CY,
    3.4,
    1.4,
    "Từ chối file,\nxoá khỏi bảng tạm",
    fontsize=11.5,
    fill=REJECT_FILL,
    border=REJECT_BORDER,
)

# 5b. Duyệt cả lô → Bảng dữ liệu khảo sát — phải
B5R_CY = 5.0
box(ax, 9.5, B5R_CY, 5.0, 1.5, "Bản dữ liệu khảo sát chung", fontsize=12.5)

# 6. Đặt lại mốc dựng bản đồ
B6_CY = 1.8
box(ax, 4.2, B6_CY, 5.6, 1.2, "Đặt lại mốc dựng bản đồ\ncho trạm thu bị ảnh hưởng", fontsize=11.5)

# 7. Train lại ML (tuỳ chọn)
B7_CY = 1.8
box(ax, 10.6, B7_CY, 4.0, 1.2, "Train lại\nmô hình học máy\n(tuỳ chọn)", fontsize=11)

# ── Mũi tên ────────────────────────────────────────────────────────
# 1 → 2
arrow(ax, (CC, B1_CY - 0.6), (CC, B2_CY + 0.6))
edge_label(ax, CC, 15.85, "Kéo gói tin từ /data")

# 2 → 3
arrow(ax, (CC, B2_CY - 0.6), (CC, B3_CY + 0.75))

# 3 → 4
arrow(ax, (CC, B3_CY - 0.75), (CC, B4_CY + 0.6))

# 4 → 5a (trái — từ chối)
arrow(ax, (CC - 2.0, B4_CY), (2.0, B5L_CY + 0.7))
edge_label(ax, 3.6, 6.6, "Từ chối")

# 4 → 5b (phải — duyệt)
arrow(ax, (CC + 2.0, B4_CY), (9.5, B5R_CY + 0.75))
edge_label(ax, 9.2, 6.6, "Duyệt")

# 5b → 6
arrow(ax, (9.5 - 1.5, B5R_CY - 0.75), (4.2, B6_CY + 0.6))

# 6 → 7
arrow(ax, (4.2 + 2.8, B6_CY), (10.6 - 2.0, B7_CY))

plt.tight_layout()
plt.savefig(OUT, dpi=180, bbox_inches="tight")
print(f"Saved: {OUT}")
