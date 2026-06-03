"""So sánh RMSE và phân tích độ lệch — Stage 2 ML v0.6 hold-out."""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

OUT = Path(__file__).resolve().parents[1] / "illustrationpic" / "rmse_bias_comparison.png"

plt.rcParams.update({"font.family": "DejaVu Sans"})

C_BASELINE = "#9e9e9e"
C_V05 = "#ffb74d"
C_V06 = "#1565c0"
C_API = "#90caf9"
C_GOOD = "#1565c0"
C_BAD = "#c62828"
C_ZERO = "#333"


def draw_panel_a(ax):
    labels = ["Null baseline\n(chỉ Tầng 1)", "v0.5", "v0.6 offline\n(active)", "v0.6\nAPI serve"]
    rmses = [15.5, 12.90, 10.58, 13.47]
    biases = [None, None, "+0,77", "+4,55"]
    colors = [C_BASELINE, C_V05, C_V06, C_API]
    edges = ["#555", "#a14f00", "#0a3a78", "#1565c0"]
    xs = [0, 1, 2, 3.4]

    bars = ax.bar(xs, rmses, color=colors, edgecolor=edges, linewidth=1.6, width=0.78, zorder=3)
    bars[2].set_linewidth(2.6)

    ax.errorbar(
        [0],
        [15.5],
        yerr=[[2.5], [2.5]],
        fmt="none",
        ecolor="#444",
        capsize=10,
        capthick=2,
        linewidth=2,
        zorder=4,
    )

    for x, v in zip(xs, rmses, strict=False):
        ax.text(x, v + 0.4, f"{v:.2f}", ha="center", fontsize=11, weight="bold", color="#222")
    ax.text(0, 15.5 + 3.0, "khoảng ~13–18", ha="center", fontsize=9, color="#444", style="italic")

    for x, b in zip(xs, biases, strict=False):
        if b is None:
            continue
        ax.text(x, -0.7, f"bias = {b} dB", ha="center", fontsize=8.5, color="#333", style="italic")

    ax.annotate(
        "−18% RMSE\n(Tầng 1 sửa P.2108,\nkhông đổi feature/hyperparam)",
        xy=(2, 11.0),
        xytext=(1.3, 19.0),
        fontsize=9.5,
        ha="center",
        va="center",
        color=C_GOOD,
        weight="bold",
        arrowprops={"arrowstyle": "-|>", "color": C_GOOD, "linewidth": 1.8},
    )

    ax.text(
        3.4,
        -2.2,
        "↑ API serve hiện có drift wiring\n→ eval thật phải qua script offline",
        ha="center",
        va="top",
        fontsize=8.5,
        color=C_BAD,
        style="italic",
    )

    ax.text(
        0,
        1.2,
        "Đường cơ sở rỗng\n— chỉ vật lý",
        ha="center",
        fontsize=8.5,
        style="italic",
        color="#555",
    )

    summary = (
        "v0.6 (active) — hold-out\n"
        "─────────────────\n"
        " RMSE  = 10,58 dB\n"
        " MAE   =  7,80 dB\n"
        " Bias  = +0,77 dB  (≈ 0)\n"
        " n     = 337  /  4 gateway"
    )
    ax.text(
        0.985,
        0.98,
        summary,
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=9,
        family="monospace",
        bbox={
            "boxstyle": "round,pad=0.4",
            "facecolor": "#e3f2fd",
            "edgecolor": C_V06,
            "linewidth": 1.4,
        },
    )

    ax.set_xticks(xs)
    ax.set_xticklabels(labels, fontsize=10)
    ax.set_ylabel("RMSE (dB)", fontsize=12, weight="bold")
    ax.set_title(
        "(a) So sánh RMSE — baseline → v0.5 → v0.6 (offline vs API)",
        fontsize=12.5,
        weight="bold",
        pad=10,
    )
    ax.set_ylim(-5, 22)
    ax.set_xlim(-0.6, 4.0)
    ax.grid(True, axis="y", linestyle=":", alpha=0.5)
    ax.axhline(0, color="#888", linewidth=0.8)


def draw_panel_b(ax):
    bin_labels = ["0–0,5", "0,5–1", "1–2", "2–5", "5–10", "10–15", "15–25"]
    bias = [-0.4, +0.6, -0.8, +0.9, +8.5, -1.1, +0.3]

    xs = np.arange(len(bin_labels))
    colors = [C_BAD if abs(b) > 3 else C_GOOD for b in bias]
    edges = ["#7a1717" if abs(b) > 3 else "#0a3a78" for b in bias]

    ax.bar(xs, bias, color=colors, edgecolor=edges, linewidth=1.4, width=0.7, zorder=3)
    ax.axhline(
        0, color=C_ZERO, linewidth=1.8, linestyle="--", zorder=2, label="bias = 0 (không lệch)"
    )

    sym_band_low, sym_band_high = -2, 2
    ax.axhspan(
        sym_band_low,
        sym_band_high,
        color="#c8e6c9",
        alpha=0.30,
        zorder=1,
        label="dải ±2 dB (đối xứng quanh 0)",
    )

    for x, b in zip(xs, bias, strict=False):
        offset = 0.45 if b > 0 else -0.95
        ax.text(x, b + offset, f"{b:+.1f}", ha="center", fontsize=10, weight="bold", color="#222")

    ax.annotate(
        'Outlier do artifact\n"receiver-trong-nhà"\ncủa DSM\n(45 mẫu rải rác)',
        xy=(4, 8.5),
        xytext=(2.0, 10.5),
        fontsize=10,
        ha="center",
        color=C_BAD,
        weight="bold",
        bbox={
            "boxstyle": "round,pad=0.35",
            "facecolor": "#fff5f5",
            "edgecolor": C_BAD,
            "linewidth": 1.4,
        },
        arrowprops={"arrowstyle": "-|>", "color": C_BAD, "linewidth": 1.8},
    )

    ax.set_xticks(xs)
    ax.set_xticklabels([f"{lab}\nkm" for lab in bin_labels], fontsize=9.5)
    ax.set_ylabel("Bias residual sau Tầng 2 (dB)", fontsize=12, weight="bold")
    ax.set_title(
        "(b) Phân tích độ lệch theo dải cự ly (v0.6 hold-out)", fontsize=12.5, weight="bold", pad=10
    )
    ax.set_xlabel("Khoảng cách từ gateway (bin)", fontsize=11)
    ax.set_ylim(-4, 13)
    ax.grid(True, axis="y", linestyle=":", alpha=0.5)
    ax.legend(loc="upper right", fontsize=9, framealpha=0.95)


def main():
    fig, (ax_a, ax_b) = plt.subplots(
        1,
        2,
        figsize=(16, 7.2),
        gridspec_kw={"width_ratios": [1.15, 1.0], "wspace": 0.22},
    )
    fig.suptitle(
        "Tầng 2 (XGBoost residual) — chứng minh giá trị & kiểm tra độ lệch",
        fontsize=14,
        weight="bold",
        y=0.99,
    )
    draw_panel_a(ax_a)
    draw_panel_b(ax_b)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=180, bbox_inches="tight", facecolor="white")
    print(f"Saved: {OUT}")


if __name__ == "__main__":
    main()
