"""Residual theo khoảng cách + bảng bias phân khoảng (step function)."""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

OUT = Path(__file__).resolve().parents[1] / "illustrationpic" / "residual_bias_step.png"

plt.rcParams.update({"font.family": "DejaVu Sans"})

RNG = np.random.default_rng(42)

C_SCATTER = "#5e8ca8"
C_STEP = "#c62828"
C_ZERO = "#444"
C_BIN_EDGE = "#cccccc"


def true_bias(d):
    """Bias hệ thống theo khoảng cách — minh họa cho 1 gateway."""
    return -0.4 - 2.8 * np.tanh((d - 600) / 350) - 1.6 * np.tanh((d - 1700) / 300)


def synth_walk_survey(n=320):
    """Sinh dữ liệu khảo sát giả lập."""
    d = RNG.uniform(40, 2700, size=n)
    noise = RNG.normal(0, 3.5, size=n)
    residual = true_bias(d) + noise
    outlier_mask = RNG.uniform(size=n) < 0.04
    residual[outlier_mask] += RNG.normal(0, 10, size=outlier_mask.sum())
    return d, residual


def bin_means(d, r, edges):
    means = np.full(len(edges) - 1, np.nan)
    counts = np.zeros(len(edges) - 1, dtype=int)
    for i in range(len(edges) - 1):
        mask = (d >= edges[i]) & (d < edges[i + 1])
        counts[i] = mask.sum()
        if mask.any():
            means[i] = r[mask].mean()
    return means, counts


def step_xy(edges, means):
    xs, ys = [], []
    for i, m in enumerate(means):
        if np.isnan(m):
            continue
        xs.extend([edges[i], edges[i + 1]])
        ys.extend([m, m])
    return xs, ys


def main():
    d, r = synth_walk_survey()
    edges = np.arange(0, 2801, 250)
    means, _counts = bin_means(d, r, edges)

    fig, ax = plt.subplots(figsize=(13, 7))

    for e in edges:
        ax.axvline(e, color=C_BIN_EDGE, linewidth=0.7, linestyle=":", zorder=1)

    ax.axhline(
        0, color=C_ZERO, linewidth=1.6, linestyle="--", zorder=2, label="residual = 0 (không lệch)"
    )

    ax.scatter(
        d,
        r,
        s=22,
        color=C_SCATTER,
        alpha=0.42,
        edgecolor="none",
        zorder=3,
        label=f"Mẫu RSSI khảo sát (n={len(d)})",
    )

    xs, ys = step_xy(edges, means)
    ax.plot(
        xs,
        ys,
        color=C_STEP,
        linewidth=3.0,
        solid_joinstyle="miter",
        zorder=5,
        label="Bias phân khoảng (mean residual / bin)",
    )

    for i in range(len(edges) - 1):
        if np.isnan(means[i]):
            continue
        xc = (edges[i] + edges[i + 1]) / 2
        ax.annotate(
            f"{means[i]:+.1f}",
            xy=(xc, means[i]),
            xytext=(0, 10 if means[i] < 0 else -14),
            textcoords="offset points",
            ha="center",
            fontsize=8.5,
            color=C_STEP,
            weight="bold",
        )

    ax.annotate(
        "Bảng bias phân khoảng (bias_<gw>.json)\n"
        "→ cộng trực tiếp vào tổn hao vật lý\n"
        "    trước khi tính margin",
        xy=(1850, means[7]),
        xytext=(1700, -19),
        fontsize=10.5,
        weight="bold",
        color=C_STEP,
        bbox={"boxstyle": "round,pad=0.4", "facecolor": "#fff5f5", "edgecolor": C_STEP},
        arrowprops={"arrowstyle": "-|>", "color": C_STEP, "linewidth": 1.6},
    )

    ax.annotate(
        "Residual lệch âm dần ở cự ly xa\n→ P.1812 + DSM hơi lạc quan ở rìa vùng phủ",
        xy=(2400, true_bias(2400)),
        xytext=(1300, 14),
        fontsize=9.5,
        style="italic",
        color="#444",
        arrowprops={"arrowstyle": "->", "color": "#666", "linewidth": 1.1, "linestyle": "--"},
    )

    ax.set_xlim(0, 2800)
    ax.set_ylim(-25, 22)
    ax.set_xlabel("Khoảng cách từ gateway (m)", fontsize=12, weight="bold")
    ax.set_ylabel("Residual = RSSI đo − RSSI dự đoán (dB)", fontsize=12, weight="bold")
    ax.set_title(
        "Phân tán residual theo khoảng cách + bảng bias phân khoảng\n"
        "(1 gateway tiêu biểu, khảo sát tại Đà Nẵng)",
        fontsize=13,
        weight="bold",
        pad=10,
    )
    ax.grid(True, axis="y", linestyle=":", alpha=0.45)
    ax.legend(loc="upper right", fontsize=10, framealpha=0.95)

    ax.text(
        0.012,
        0.02,
        "Bin = 250 m; bias[bin] = mean(residual) — áp dụng khi phát-lại Stage 1",
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=9.5,
        color="#444",
        style="italic",
        bbox={"boxstyle": "round,pad=0.4", "facecolor": "#fafafa", "edgecolor": "#bbb"},
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=180, bbox_inches="tight", facecolor="white")
    print(f"Saved: {OUT}")


if __name__ == "__main__":
    main()
