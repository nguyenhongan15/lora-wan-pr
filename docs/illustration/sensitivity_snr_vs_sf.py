"""Độ nhạy thu và giới hạn SNR theo SF (SX1276/8, BW 125 kHz) — dual-axis chart."""

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch

OUT = Path(__file__).resolve().parents[1] / "illustrationpic" / "sensitivity_snr_vs_sf.png"

plt.rcParams.update({"font.family": "DejaVu Sans"})

SF = [7, 8, 9, 10, 11, 12]
SENS = [-123.0, -126.0, -129.0, -132.0, -134.5, -137.0]
SNR = [-7.5, -10.0, -12.5, -15.0, -17.5, -20.0]

C_SENS = "#1565c0"
C_SNR = "#ef6c00"
C_BG = "#fff8e1"


def main():
    fig, ax1 = plt.subplots(figsize=(11, 6.5))

    ax1.axvspan(SF[0] - 0.5, SF[-1] + 0.5, color=C_BG, alpha=0.45, zorder=0)

    (line1,) = ax1.plot(
        SF,
        SENS,
        "o-",
        color=C_SENS,
        linewidth=2.4,
        markersize=10,
        markerfacecolor="white",
        markeredgewidth=2.0,
        label="Độ nhạy thu (dBm)",
        zorder=4,
    )
    for x, y in zip(SF, SENS, strict=False):
        dy = 14 if x >= 11 else -16
        ax1.annotate(
            f"{y:g}",
            xy=(x, y),
            xytext=(0, dy),
            textcoords="offset points",
            ha="center",
            fontsize=9.5,
            color=C_SENS,
            weight="bold",
        )

    ax1.set_xlabel("Spreading Factor (SF)", fontsize=12, weight="bold")
    ax1.set_ylabel("Độ nhạy thu (dBm)", fontsize=12, color=C_SENS, weight="bold")
    ax1.tick_params(axis="y", labelcolor=C_SENS)
    ax1.set_xticks(SF)
    ax1.set_xticklabels([f"SF{s}" for s in SF], fontsize=11)
    ax1.set_xlim(SF[0] - 0.5, SF[-1] + 0.5)
    ax1.set_ylim(-141, -120)
    ax1.grid(True, axis="y", linestyle=":", alpha=0.5)
    ax1.spines["top"].set_visible(False)

    ax2 = ax1.twinx()
    (line2,) = ax2.plot(
        SF,
        SNR,
        "s--",
        color=C_SNR,
        linewidth=2.4,
        markersize=10,
        markerfacecolor="white",
        markeredgewidth=2.0,
        label="Giới hạn SNR (dB)",
        zorder=4,
    )
    for x, y in zip(SF, SNR, strict=False):
        dy = -14 if x >= 11 else 12
        ax2.annotate(
            f"{y:g}",
            xy=(x, y),
            xytext=(0, dy),
            textcoords="offset points",
            ha="center",
            fontsize=9.5,
            color=C_SNR,
            weight="bold",
        )

    ax2.set_ylabel("Giới hạn SNR (dB)", fontsize=12, color=C_SNR, weight="bold")
    ax2.tick_params(axis="y", labelcolor=C_SNR)
    ax2.set_ylim(-22.5, -5.5)
    ax2.spines["top"].set_visible(False)

    arr = FancyArrowPatch(
        (SF[0] - 0.1, -4.2),
        (SF[-1] + 0.1, -4.2),
        arrowstyle="-|>",
        mutation_scale=22,
        linewidth=2.2,
        color="#555",
        transform=ax2.transData,
        clip_on=False,
    )
    ax2.add_patch(arr)
    ax2.text(
        (SF[0] + SF[-1]) / 2,
        -3.0,
        "SF tăng → độ nhạy tốt hơn, ngưỡng SNR thấp hơn → đổi lại tốc độ dữ liệu giảm",
        ha="center",
        va="bottom",
        fontsize=10.5,
        weight="bold",
        color="#333",
        transform=ax2.transData,
        clip_on=False,
    )

    ax1.text(
        0.015,
        0.03,
        "SX1276/8, BW 125 kHz",
        transform=ax1.transAxes,
        ha="left",
        va="bottom",
        fontsize=9.5,
        style="italic",
        color="#555",
        bbox={"boxstyle": "round,pad=0.3", "facecolor": "white", "edgecolor": "#bbb"},
    )

    ax1.legend(
        handles=[line1, line2],
        loc="upper right",
        bbox_to_anchor=(0.99, 0.99),
        fontsize=10.5,
        framealpha=0.95,
        handlelength=3.2,
        handletextpad=1.0,
        borderpad=0.6,
        markerscale=0.7,
    )

    fig.suptitle(
        "Độ nhạy thu và giới hạn SNR theo Spreading Factor", fontsize=14, weight="bold", y=0.995
    )

    fig.tight_layout(rect=(0, 0, 1, 0.93))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=180, bbox_inches="tight", facecolor="white")
    print(f"Saved: {OUT}")


if __name__ == "__main__":
    main()
