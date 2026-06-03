"""Cơ chế margin = min(power, snr): điểm phủ ⇔ cả hai ràng buộc dương."""

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, PathPatch, Rectangle
from matplotlib.path import Path as MplPath

OUT = Path(__file__).resolve().parents[1] / "illustrationpic" / "margin_min_constraints.png"

plt.rcParams.update({"font.family": "DejaVu Sans"})

C_BAR = "#90caf9"
C_BAR_EDGE = "#1565c0"
C_MARGIN = "#a5d6a7"
C_MARGIN_EDGE = "#2e7d32"
C_THRESH = "#c62828"
C_TEXT = "#222"
C_BRACE = "#444"
C_KEY = "#c62828"

XB0, XB1 = 12, 62


def value_to_x(v, vmin, vmax):
    return XB0 + (v - vmin) / (vmax - vmin) * (XB1 - XB0)


def draw_bar(
    ax,
    y,
    value_min,
    value_max,
    threshold,
    actual,
    unit,
    title,
    thresh_label,
    actual_label,
    margin_label,
):
    h = 5.5

    ax.add_patch(
        Rectangle(
            (XB0, y - h / 2), XB1 - XB0, h, facecolor="#f5f5f5", edgecolor="#bbb", linewidth=0.8
        )
    )

    x_th = value_to_x(threshold, value_min, value_max)
    x_ac = value_to_x(actual, value_min, value_max)

    ax.add_patch(
        Rectangle(
            (XB0, y - h / 2), x_th - XB0, h, facecolor=C_BAR, edgecolor=C_BAR_EDGE, linewidth=1.0
        )
    )
    ax.add_patch(
        Rectangle(
            (x_th, y - h / 2),
            x_ac - x_th,
            h,
            facecolor=C_MARGIN,
            edgecolor=C_MARGIN_EDGE,
            linewidth=1.0,
            hatch="//",
        )
    )

    ax.plot([x_th, x_th], [y - h / 2 - 1.5, y + h / 2 + 3.0], color=C_THRESH, linewidth=2.2)
    ax.plot(
        [x_ac, x_ac],
        [y - h / 2 - 1.5, y + h / 2 + 1.0],
        color=C_BAR_EDGE,
        linewidth=2.0,
        linestyle="--",
    )

    ax.text(XB0 - 1, y, title, ha="right", va="center", fontsize=11, weight="bold", color=C_TEXT)

    ax.text(
        x_th,
        y + h / 2 + 4.2,
        thresh_label,
        ha="center",
        va="bottom",
        fontsize=9.5,
        color=C_THRESH,
        weight="bold",
        bbox={"boxstyle": "round,pad=0.2", "facecolor": "white", "edgecolor": C_THRESH},
    )
    ax.text(
        x_ac,
        y + h / 2 + 1.8,
        actual_label,
        ha="center",
        va="bottom",
        fontsize=9.5,
        color=C_BAR_EDGE,
        weight="bold",
    )

    ax.annotate(
        "",
        xy=(x_ac, y - h / 2 - 2.5),
        xytext=(x_th, y - h / 2 - 2.5),
        arrowprops={"arrowstyle": "<->", "color": C_MARGIN_EDGE, "linewidth": 1.8},
    )
    ax.text(
        (x_th + x_ac) / 2,
        y - h / 2 - 4.5,
        margin_label,
        ha="center",
        va="top",
        fontsize=11,
        weight="bold",
        color=C_MARGIN_EDGE,
    )

    ax.text(
        XB1 + 0.5,
        y - h / 2 - 0.5,
        f"{unit}",
        ha="left",
        va="top",
        fontsize=8.5,
        color="#666",
        style="italic",
    )


def draw_brace(ax, x, y_top, y_bot, width=1.6):
    y_mid = (y_top + y_bot) / 2
    verts = [
        (x, y_top),
        (x + width, y_top),
        (x + width, y_mid + width),
        (x + 2 * width, y_mid),
        (x + width, y_mid - width),
        (x + width, y_bot),
        (x, y_bot),
    ]
    codes = [
        MplPath.MOVETO,
        MplPath.CURVE3,
        MplPath.CURVE3,
        MplPath.LINETO,
        MplPath.CURVE3,
        MplPath.CURVE3,
        MplPath.LINETO,
    ]
    ax.add_patch(
        PathPatch(MplPath(verts, codes), facecolor="none", edgecolor=C_BRACE, linewidth=2.0)
    )


def main():
    fig, ax = plt.subplots(figsize=(13, 8.5))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.set_aspect("auto")
    ax.axis("off")

    ax.text(
        50,
        96,
        "Margin = min(ràng buộc công suất, ràng buộc SNR)",
        ha="center",
        fontsize=15,
        weight="bold",
    )
    ax.text(
        50,
        91.5,
        "Một điểm chỉ được coi là PHỦ khi cả hai dự phòng đều dương",
        ha="center",
        fontsize=11,
        color="#555",
        style="italic",
    )

    draw_bar(
        ax,
        y=72,
        value_min=-140,
        value_max=-115,
        threshold=-129,
        actual=-121,
        unit="dBm",
        title="Ràng buộc\ncông suất\n(RSSI − Sens.)",
        thresh_label="Sensitivity = −129 dBm",
        actual_label="RSSI = −121 dBm",
        margin_label="Dự phòng công suất = +8 dB",
    )

    draw_bar(
        ax,
        y=42,
        value_min=-22,
        value_max=-2,
        threshold=-12.5,
        actual=-9.5,
        unit="dB",
        title="Ràng buộc\ntín hiệu/nhiễu\n(SNR − SNR_limit)",
        thresh_label="SNR_limit = −12,5 dB",
        actual_label="SNR = −9,5 dB",
        margin_label="Dự phòng SNR = +3 dB",
    )

    draw_brace(ax, x=68, y_top=78, y_bot=36, width=1.6)
    ax.text(
        74,
        57,
        "Margin =\nmin( +8 dB , +3 dB )",
        fontsize=12,
        weight="bold",
        color=C_TEXT,
        va="center",
    )
    ax.text(74, 49, "= ", fontsize=14, weight="bold", color=C_TEXT, va="center")
    ax.text(77, 49, "+3 dB", fontsize=18, weight="bold", color=C_KEY, va="center")
    ax.text(
        74,
        44,
        "(SNR là ràng buộc quyết định)",
        fontsize=9.5,
        style="italic",
        color="#666",
        va="center",
    )

    cover_box = FancyBboxPatch(
        (10, 16),
        50,
        10,
        boxstyle="round,pad=0.3,rounding_size=0.5",
        linewidth=1.4,
        edgecolor=C_MARGIN_EDGE,
        facecolor="#e8f5e9",
    )
    ax.add_patch(cover_box)
    ax.text(
        35,
        23.5,
        "✓  Điểm được coi là PHỦ  ⇔  Margin > 0 ở cả hai ràng buộc",
        ha="center",
        va="center",
        fontsize=12,
        weight="bold",
        color=C_MARGIN_EDGE,
    )
    ax.text(
        35,
        18.8,
        "(min(+8, +3) = +3 > 0  →  điểm này có phủ)",
        ha="center",
        va="center",
        fontsize=10,
        style="italic",
        color="#444",
    )

    counter_box = FancyBboxPatch(
        (65, 16),
        30,
        10,
        boxstyle="round,pad=0.3,rounding_size=0.5",
        linewidth=1.4,
        edgecolor=C_THRESH,
        facecolor="#ffebee",
    )
    ax.add_patch(counter_box)
    ax.text(
        80,
        23.5,
        "✗  Ví dụ phản chứng",
        ha="center",
        va="center",
        fontsize=10.5,
        weight="bold",
        color=C_THRESH,
    )
    ax.text(
        80,
        19.3,
        "RSSI dư +10 dB nhưng SNR = −15 dB\n→ min(+10, −2,5) < 0  →  KHÔNG phủ",
        ha="center",
        va="center",
        fontsize=9,
        color="#444",
    )

    legend_y = 6
    ax.add_patch(Rectangle((12, legend_y), 3, 2.5, facecolor=C_BAR, edgecolor=C_BAR_EDGE))
    ax.text(15.8, legend_y + 1.2, "tới ngưỡng", fontsize=9, va="center")
    ax.add_patch(
        Rectangle((30, legend_y), 3, 2.5, facecolor=C_MARGIN, edgecolor=C_MARGIN_EDGE, hatch="//")
    )
    ax.text(33.8, legend_y + 1.2, "dự phòng (margin)", fontsize=9, va="center")
    ax.plot([56, 59], [legend_y + 1.2, legend_y + 1.2], color=C_THRESH, linewidth=2.2)
    ax.text(60, legend_y + 1.2, "ngưỡng (Sens / SNR_limit)", fontsize=9, va="center")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=180, bbox_inches="tight", facecolor="white")
    print(f"Saved: {OUT}")


if __name__ == "__main__":
    main()
