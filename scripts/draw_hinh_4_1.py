"""Hình 4.1 — Kiến trúc 3 tầng + nguồn dữ liệu ngoài (Server LPWAN Mapper).

Phong cách tham khảo (chốt 2026-06-18):
  * 3 khung tầng nét đứt xếp dọc bên trái, pill tên tầng xanh dương đè cạnh trên.
  * Server LPWAN Mapper là khối 3D ĐẶT NGOÀI mọi tầng, phía trên-phải.
  * Tầng logic: API Service (trái, lõi) ↔ {Web service, ML Service} (phải, xếp chồng).
  * Tầng cơ sở dữ liệu chỉ có 1 khối Database (3D).
  * Mũi tên đen mảnh, nhãn chữ nghiêng đặt rời.
  * Không có tiêu đề hình.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch, Polygon

OUT = Path(__file__).resolve().parents[1] / "docs" / "anh" / "hinh_4_1.png"

# ── palette ─────────────────────────────────────────────────────────
BG = "white"
STROKE = "#2C3E50"
LAYER_PILL_FILL = "#2680EB"
LAYER_PILL_TEXT = "white"
BOX_FILL = "white"
CORE_FILL = "#1F3F6E"
CORE_EDGE = "#0F2347"
CUBE_FILL = "#F4F6F8"
CUBE_EDGE = "#2C3E50"
ARROW = "#1A1A1A"
LABEL_COLOR = "#444444"


def box(
    ax,
    x,
    y,
    w,
    h,
    text,
    *,
    fill=BOX_FILL,
    edge=STROKE,
    text_color="black",
    weight="normal",
    fontsize=12,
    lw=1.4,
    rounding=0.10,
):
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle=f"round,pad=0.02,rounding_size={rounding}",
            linewidth=lw,
            facecolor=fill,
            edgecolor=edge,
        )
    )
    ax.text(
        x + w / 2,
        y + h / 2,
        text,
        ha="center",
        va="center",
        color=text_color,
        fontsize=fontsize,
        weight=weight,
    )


def rect(ax, x, y, w, h, text, *, fill=BOX_FILL, edge=STROKE, fontsize=12, lw=1.3, weight="normal"):
    """Hộp chữ nhật vuông góc (không bo) — dùng cho Web service / ML Service."""
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="square,pad=0.0",
            linewidth=lw,
            facecolor=fill,
            edgecolor=edge,
        )
    )
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fontsize, weight=weight)


def cube3d(
    ax, x, y, w, h, text, *, depth=0.32, fill=CUBE_FILL, edge=CUBE_EDGE, fontsize=11, lw=1.3
):
    """Khối hộp 3D kiểu parallelepiped (mặt trước + mặt trên + mặt phải)."""
    ax.add_patch(
        Polygon(
            [(x, y), (x + w, y), (x + w, y + h), (x, y + h)],
            closed=True,
            facecolor=fill,
            edgecolor=edge,
            linewidth=lw,
        )
    )
    ax.add_patch(
        Polygon(
            [
                (x, y + h),
                (x + depth, y + h + depth),
                (x + w + depth, y + h + depth),
                (x + w, y + h),
            ],
            closed=True,
            facecolor=fill,
            edgecolor=edge,
            linewidth=lw,
        )
    )
    ax.add_patch(
        Polygon(
            [
                (x + w, y),
                (x + w + depth, y + depth),
                (x + w + depth, y + h + depth),
                (x + w, y + h),
            ],
            closed=True,
            facecolor=fill,
            edgecolor=edge,
            linewidth=lw,
        )
    )
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fontsize)


def line(ax, p1, p2, *, double=False, color=ARROW, connectionstyle="arc3,rad=0"):
    style = "<->" if double else "->"
    ax.add_patch(
        FancyArrowPatch(
            p1,
            p2,
            arrowstyle=style,
            mutation_scale=18,
            color=color,
            linewidth=1.4,
            shrinkA=2,
            shrinkB=2,
            connectionstyle=connectionstyle,
        )
    )


def layer_box(ax, x, y, w, h, name, *, pill_w=3.4, pill_h=0.55):
    """Khung tầng nét đứt + pill tên tầng đè cạnh trên."""
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0.02,rounding_size=0.12",
            linewidth=1.4,
            facecolor=BG,
            edgecolor=STROKE,
            linestyle="--",
        )
    )
    px = x + w / 2 - pill_w / 2
    py = y + h - pill_h / 2
    ax.add_patch(
        FancyBboxPatch(
            (px, py),
            pill_w,
            pill_h,
            boxstyle="round,pad=0.02,rounding_size=0.28",
            linewidth=1.0,
            facecolor=LAYER_PILL_FILL,
            edgecolor=LAYER_PILL_FILL,
            zorder=5,
        )
    )
    ax.text(
        px + pill_w / 2,
        py + pill_h / 2,
        name,
        ha="center",
        va="center",
        color=LAYER_PILL_TEXT,
        fontsize=11.5,
        weight="bold",
        zorder=6,
    )


def user_icon(ax, cx, cy, *, body_w=0.9, body_h=0.55, head_r=0.32):
    """Pictogram user: vòng tròn đầu + thân hình viên thuốc."""
    ax.add_patch(Circle((cx, cy + 0.55), head_r, facecolor=BG, edgecolor=STROKE, linewidth=1.4))
    ax.add_patch(
        FancyBboxPatch(
            (cx - body_w / 2, cy - 0.35),
            body_w,
            body_h,
            boxstyle="round,pad=0.02,rounding_size=0.28",
            facecolor=BG,
            edgecolor=STROKE,
            linewidth=1.4,
        )
    )
    ax.text(cx, cy - 0.75, "User", ha="center", va="center", fontsize=11.5, weight="bold")


fig, ax = plt.subplots(figsize=(14, 11))
ax.set_xlim(0, 14)
ax.set_ylim(0, 11.5)
ax.set_aspect("equal")
ax.axis("off")

# ── Server LPWAN Mapper (NGOÀI mọi tầng, phía trên-phải) ─────────────
cube3d(ax, 11.0, 9.0, 2.3, 1.4, "Server\nLPWAN Mapper", fontsize=11)

# ── 3 khung tầng (xếp dọc bên trái, không full-width) ────────────────
LX, LW = 0.4, 10.2
layer_box(ax, LX, 7.7, LW, 3.0, "Tầng giao diện người dùng", pill_w=4.6)
layer_box(ax, LX, 3.8, LW, 3.4, "Tầng logic ứng dụng", pill_w=3.7)
layer_box(ax, LX, 0.3, LW, 3.0, "Tầng cơ sở dữ liệu", pill_w=3.5)

# ── Tầng 1: giao diện người dùng ─────────────────────────────────────
user_icon(ax, cx=2.3, cy=9.0)
box(ax, 6.0, 8.7, 2.7, 1.0, "Web UI", fontsize=13.5, weight="bold")
line(ax, (3.0, 9.2), (6.0, 9.2))  # User → Web UI

# ── Tầng 2: logic ứng dụng ───────────────────────────────────────────
# Trái: API Service (lõi, navy, bo góc lớn)
box(
    ax,
    1.4,
    4.6,
    3.0,
    1.8,
    "API Service",
    fill=CORE_FILL,
    edge=CORE_EDGE,
    text_color="white",
    weight="bold",
    fontsize=13.5,
    rounding=0.22,
)

# Phải: cụm Web service + ML Service xếp chồng (chữ nhật, chia đôi)
rect(ax, 6.0, 5.5, 3.6, 0.9, "Web service", fontsize=12, weight="bold")
rect(ax, 6.0, 4.6, 3.6, 0.9, "Machine learning Service", fontsize=11.5, weight="bold")

# API Service ↔ Web service (bidirectional)
line(ax, (4.4, 5.95), (6.0, 5.95), double=True)
# API Service ↔ Machine learning Service (bidirectional)
line(ax, (4.4, 5.05), (6.0, 5.05), double=True)

# Web service → Web UI (mũi tên đi lên xuyên biên tầng giao diện)
line(ax, (7.3, 6.4), (7.3, 8.7))

# Server LPWAN Mapper → Web service (đi từ phải ngoài vào)
line(ax, (11.0, 9.0), (9.6, 5.95), connectionstyle="arc3,rad=-0.18")

# ── Tầng 3: cơ sở dữ liệu (1 khối 3D bên trái) ───────────────────────
cube3d(ax, 1.6, 1.0, 2.4, 1.4, "Database", fontsize=12)

# API Service ↔ Database (đi xuống xuyên biên tầng)
line(ax, (2.6, 4.6), (2.6, 2.4), double=True)

plt.tight_layout()
plt.savefig(OUT, dpi=200, bbox_inches="tight", facecolor=BG)
print(f"saved {OUT}")
