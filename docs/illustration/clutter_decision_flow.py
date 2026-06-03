"""Vẽ sơ đồ logic chọn nguồn clutter (DSM vs P.2108) + so sánh bias trước/sau."""

from pathlib import Path

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Polygon

OUT = Path(__file__).resolve().parents[1] / "illustrationpic" / "clutter_decision_flow.png"

C_START = "#dbe9ff"
C_DECISION = "#fff2cc"
C_YES = "#c8e6c9"
C_NO = "#ffd6a5"
C_END = "#e1d5f5"
C_EDGE = "#333333"
C_TABLE_BG = "#fafafa"
C_BEFORE = "#e57373"
C_AFTER = "#81c784"

FONT = {"family": "DejaVu Sans"}
plt.rcParams.update({"font.family": "DejaVu Sans"})


def rounded_box(ax, xy, w, h, text, facecolor, fontsize=10, weight="normal"):
    x, y = xy
    box = FancyBboxPatch(
        (x - w / 2, y - h / 2),
        w,
        h,
        boxstyle="round,pad=0.02,rounding_size=0.25",
        linewidth=1.4,
        edgecolor=C_EDGE,
        facecolor=facecolor,
    )
    ax.add_patch(box)
    ax.text(x, y, text, ha="center", va="center", fontsize=fontsize, weight=weight, wrap=True)


def rect_box(ax, xy, w, h, text, facecolor, fontsize=10):
    x, y = xy
    box = FancyBboxPatch(
        (x - w / 2, y - h / 2),
        w,
        h,
        boxstyle="round,pad=0.02,rounding_size=0.05",
        linewidth=1.4,
        edgecolor=C_EDGE,
        facecolor=facecolor,
    )
    ax.add_patch(box)
    ax.text(x, y, text, ha="center", va="center", fontsize=fontsize, wrap=True)


def diamond(ax, xy, w, h, text, facecolor, fontsize=10):
    x, y = xy
    pts = [(x, y + h / 2), (x + w / 2, y), (x, y - h / 2), (x - w / 2, y)]
    ax.add_patch(Polygon(pts, closed=True, linewidth=1.4, edgecolor=C_EDGE, facecolor=facecolor))
    ax.text(x, y, text, ha="center", va="center", fontsize=fontsize, weight="bold")


def arrow(ax, p0, p1, label=None, label_offset=(0.15, 0)):
    a = FancyArrowPatch(
        p0,
        p1,
        arrowstyle="-|>",
        mutation_scale=16,
        linewidth=1.4,
        color=C_EDGE,
        shrinkA=2,
        shrinkB=2,
    )
    ax.add_patch(a)
    if label:
        mx = (p0[0] + p1[0]) / 2 + label_offset[0]
        my = (p0[1] + p1[1]) / 2 + label_offset[1]
        ax.text(
            mx,
            my,
            label,
            ha="center",
            va="center",
            fontsize=10,
            weight="bold",
            bbox={"boxstyle": "round,pad=0.2", "facecolor": "white", "edgecolor": "none"},
        )


def draw_flow(ax):
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 12)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title(
        "Sơ đồ logic chọn nguồn clutter: DSM vs ITU-R P.2108", fontsize=13, weight="bold", pad=14
    )

    start = (5, 11)
    decision = (5, 8.8)
    yes_box = (2, 6)
    no_box = (8, 6)
    merge = (5, 3.6)

    rounded_box(
        ax,
        start,
        6.4,
        1.0,
        "Tổn hao trung vị từ ITU-R P.1812\n(chưa có thành phần clutter)",
        C_START,
        fontsize=10,
        weight="bold",
    )

    diamond(ax, decision, 4.8, 1.6, "Có dữ liệu DSM\ncho khu vực?", C_DECISION, fontsize=10)

    rect_box(
        ax,
        yes_box,
        3.6,
        1.6,
        "Vật cản đã nằm trong\nbiên dạng bề mặt (DSM)\n→ BỎ P.2108",
        C_YES,
        fontsize=9.5,
    )

    rect_box(
        ax,
        no_box,
        3.6,
        1.6,
        "Cộng tổn hao clutter\nthống kê từ ITU-R P.2108\n(nguy cơ tính trùng)",
        C_NO,
        fontsize=9.5,
    )

    rounded_box(
        ax,
        merge,
        6.4,
        1.2,
        "Tổng tổn hao đường truyền\n→ chuyển sang tính RSSI / SNR",
        C_END,
        fontsize=10,
        weight="bold",
    )

    arrow(ax, (start[0], start[1] - 0.5), (decision[0], decision[1] + 0.8))
    arrow(
        ax,
        (decision[0] - 2.0, decision[1] + 0.2),
        (yes_box[0] + 0.2, yes_box[1] + 0.8),
        label="CÓ",
        label_offset=(-0.35, 0.25),
    )
    arrow(
        ax,
        (decision[0] + 2.0, decision[1] + 0.2),
        (no_box[0] - 0.2, no_box[1] + 0.8),
        label="KHÔNG",
        label_offset=(0.55, 0.25),
    )
    arrow(ax, (yes_box[0] + 0.2, yes_box[1] - 0.8), (merge[0] - 1.8, merge[1] + 0.6))
    arrow(ax, (no_box[0] - 0.2, no_box[1] - 0.8), (merge[0] + 1.8, merge[1] + 0.6))


def draw_table(ax):
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 4)
    ax.axis("off")

    frame = FancyBboxPatch(
        (0.3, 0.2),
        9.4,
        3.6,
        boxstyle="round,pad=0.02,rounding_size=0.1",
        linewidth=1.2,
        edgecolor="#bbbbbb",
        facecolor=C_TABLE_BG,
    )
    ax.add_patch(frame)
    ax.text(
        5,
        3.45,
        "Tác động lên bias hệ thống (n=500, P.1812 + DSM)",
        ha="center",
        va="center",
        fontsize=11,
        weight="bold",
    )

    before, after = 26.0, 2.7
    max_h = 2.0
    bar_w = 0.9
    base_y = 0.6

    bx, ax_after = 2.0, 4.2
    h_before = max_h
    h_after = max_h * (after / before)

    ax.add_patch(
        mpatches.Rectangle(
            (bx - bar_w / 2, base_y),
            bar_w,
            h_before,
            facecolor=C_BEFORE,
            edgecolor=C_EDGE,
            linewidth=1.2,
        )
    )
    ax.text(bx, base_y + h_before + 0.2, "+26 dB", ha="center", fontsize=11, weight="bold")
    ax.text(
        bx, base_y - 0.25, "Trước\n(tính trùng P.2108 + DSM)", ha="center", va="top", fontsize=9.5
    )

    ax.add_patch(
        mpatches.Rectangle(
            (ax_after - bar_w / 2, base_y),
            bar_w,
            h_after,
            facecolor=C_AFTER,
            edgecolor=C_EDGE,
            linewidth=1.2,
        )
    )
    ax.text(ax_after, base_y + h_after + 0.2, "+2,7 dB", ha="center", fontsize=11, weight="bold")
    ax.text(
        ax_after, base_y - 0.25, "Sau\n(bỏ P.2108 khi có DSM)", ha="center", va="top", fontsize=9.5
    )

    arr = FancyArrowPatch(
        (bx + bar_w / 2 + 0.15, base_y + h_before * 0.6),
        (ax_after - bar_w / 2 - 0.15, base_y + h_after + 0.2),
        arrowstyle="-|>",
        mutation_scale=22,
        linewidth=2.2,
        color="#1565c0",
    )
    ax.add_patch(arr)
    ax.text(
        (bx + ax_after) / 2,
        base_y + max_h * 0.85,
        "Giảm ~23 dB",
        ha="center",
        fontsize=10.5,
        weight="bold",
        color="#1565c0",
        bbox={"boxstyle": "round,pad=0.25", "facecolor": "white", "edgecolor": "#1565c0"},
    )

    note_x = 6.2
    ax.text(
        note_x,
        2.9,
        "Quy tắc: chỉ dùng 1 nguồn clutter để tránh\ncộng trùng tổn hao do vật cản gần thu.",
        ha="left",
        va="top",
        fontsize=10,
    )
    ax.text(
        note_x,
        1.7,
        "• Có DSM  → biên dạng bề mặt đã chứa\n   nhà/cây → BỎ P.2108\n"
        "• Không DSM → cộng P.2108 (thống kê)",
        ha="left",
        va="top",
        fontsize=9.5,
    )


def main():
    fig = plt.figure(figsize=(11, 10.5))
    gs = fig.add_gridspec(2, 1, height_ratios=[2.2, 1.0], hspace=0.0)
    ax_flow = fig.add_subplot(gs[0])
    ax_table = fig.add_subplot(gs[1])
    draw_flow(ax_flow)
    draw_table(ax_table)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=180, bbox_inches="tight", facecolor="white")
    print(f"Saved: {OUT}")


if __name__ == "__main__":
    main()
