"""Mặt cắt dọc tia tx→rx: đối chiếu DEM (đất trần) vs DSM (đất + công trình + tán cây)."""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Polygon

OUT = Path(__file__).resolve().parents[1] / "illustrationpic" / "dem_vs_dsm_profile.png"

C_DEM = "#c19a6b"
C_DSM = "#6b4226"
C_DEM_FILL = "#f5e6d3"
C_LOS = "#1565c0"
C_SHADOW = "#d32f2f"
C_TX = "#37474f"
C_EDGE = "#222222"

plt.rcParams.update({"font.family": "DejaVu Sans"})


def make_dem(x):
    """Địa hình đất trần — mềm, liên tục."""
    return 22.0 + 4.0 * np.sin(x * 1.4) + 2.5 * np.sin(x * 3.1 + 0.6) + 1.2 * np.sin(x * 5.7 + 1.2)


def dem_at(x_val):
    return float(make_dem(np.array([x_val]))[0])


def add_building_flat(dsm, x, x0, x1, height):
    """Building mái phẳng: roof = DEM(center) + height; đáy bám DEM ở hai mép."""
    mask = (x >= x0) & (x <= x1)
    floor = dem_at((x0 + x1) / 2)
    dsm[mask] = np.maximum(dsm[mask], floor + height)
    return dsm, floor + height


def add_tree_clump(dsm, x, center, width, height):
    mask = (x >= center - width) & (x <= center + width)
    bump = height * np.exp(-((x[mask] - center) ** 2) / (2 * (width / 2.2) ** 2))
    dsm[mask] = np.maximum(dsm[mask], make_dem(x[mask]) + bump)
    return dsm


def draw_profile(ax):
    x = np.linspace(0.0, 3.0, 1500)
    dem = make_dem(x)
    dsm = dem.copy()

    add_tree_clump(dsm, x, center=0.35, width=0.18, height=6)
    add_building_flat(dsm, x, 0.85, 1.05, 14)
    add_tree_clump(dsm, x, center=1.30, width=0.10, height=5)
    _, blocker_roof = add_building_flat(dsm, x, 1.50, 1.75, 28)
    add_tree_clump(dsm, x, center=2.00, width=0.14, height=3)
    add_building_flat(dsm, x, 2.25, 2.45, 12)
    add_tree_clump(dsm, x, center=2.75, width=0.10, height=3)

    tx_x = 0.0
    tx_ground = dem_at(tx_x)
    tx_tower_h = 20.0
    tx_top = tx_ground + tx_tower_h

    rx_x = 3.0
    rx_ground = dem_at(rx_x)
    rx_dev_h = 1.5
    rx_top = rx_ground + rx_dev_h

    ax.fill_between(x, 0, dem, color=C_DEM_FILL, alpha=0.55, zorder=1)
    ax.plot(
        x,
        dem,
        "--",
        color=C_DEM,
        linewidth=2.2,
        label="DEM (đất trần, Copernicus GLO-30)",
        zorder=3,
    )
    ax.plot(
        x, dsm, "-", color=C_DSM, linewidth=2.4, label="DSM (đất + công trình + tán cây)", zorder=4
    )

    ax.plot(
        [tx_x, rx_x],
        [tx_top, rx_top],
        "-",
        color=C_LOS,
        linewidth=2.2,
        label="Tia LOS tx → rx",
        zorder=5,
    )

    ax.plot([tx_x, tx_x], [tx_ground, tx_top], color=C_TX, linewidth=3.5, zorder=6)
    ax.plot(tx_x, tx_top, "o", color=C_TX, markersize=10, zorder=7)
    ax.annotate(
        "Gateway\n(anten tx)",
        xy=(tx_x, tx_top),
        xytext=(0.08, tx_top + 6),
        fontsize=10,
        weight="bold",
        color=C_TX,
    )

    ax.plot([rx_x, rx_x], [rx_ground, rx_top], color=C_TX, linewidth=3.0, zorder=6)
    ax.plot(rx_x, rx_top, "s", color=C_TX, markersize=10, zorder=7)
    ax.annotate(
        "Thiết bị thu\n(rx)",
        xy=(rx_x, rx_top),
        xytext=(rx_x - 0.42, rx_top + 6),
        fontsize=10,
        weight="bold",
        color=C_TX,
    )

    obs_x0, obs_x1 = 1.50, 1.75
    obs_center = (obs_x0 + obs_x1) / 2

    tangent_slope = (blocker_roof - tx_top) / (obs_x1 - tx_x)
    tangent_at_rx = tx_top + tangent_slope * (rx_x - tx_x)

    shadow_poly = Polygon(
        [
            (obs_x1, blocker_roof),
            (rx_x, tangent_at_rx),
            (rx_x, dem_at(rx_x)),
            (obs_x1, dem_at(obs_x1)),
        ],
        closed=True,
        facecolor=C_SHADOW,
        alpha=0.22,
        edgecolor=C_SHADOW,
        linewidth=1.2,
        linestyle="--",
        zorder=2.5,
    )
    ax.add_patch(shadow_poly)

    los_at_obs = tx_top + (rx_top - tx_top) * (obs_center - tx_x) / (rx_x - tx_x)
    ax.plot(
        [obs_center, obs_center],
        [los_at_obs, blocker_roof],
        color=C_SHADOW,
        linewidth=1.8,
        linestyle=":",
        zorder=5.5,
    )
    ax.annotate(
        f"Δ ≈ {blocker_roof - los_at_obs:.0f} m\n(vật cản cao hơn tia)",
        xy=(obs_center, (los_at_obs + blocker_roof) / 2),
        xytext=(0.20, 38),
        fontsize=9.5,
        color=C_SHADOW,
        weight="bold",
        arrowprops={"arrowstyle": "->", "color": C_SHADOW, "linewidth": 1.1},
    )

    ax.annotate(
        "Bóng che do công trình\n— chỉ DSM nắm bắt được",
        xy=(2.4, (tangent_at_rx + dem_at(2.4)) / 2),
        xytext=(0.55, 65),
        fontsize=10.5,
        weight="bold",
        color=C_SHADOW,
        bbox={"boxstyle": "round,pad=0.3", "facecolor": "white", "edgecolor": C_SHADOW},
        arrowprops={"arrowstyle": "-|>", "color": C_SHADOW, "linewidth": 1.6},
    )

    dem_at_obs = dem_at(obs_center)
    ax.annotate(
        'DEM nằm thấp hơn tia\n→ "không thấy" vật cản',
        xy=(obs_center + 0.05, dem_at_obs),
        xytext=(1.95, 7),
        fontsize=9.5,
        color=C_DEM,
        style="italic",
        arrowprops={"arrowstyle": "->", "color": C_DEM, "linewidth": 1.2, "linestyle": "--"},
    )

    ax.set_xlim(-0.05, 3.05)
    ax.set_ylim(0, 78)
    ax.set_xlabel("Khoảng cách dọc tia (km)", fontsize=11)
    ax.set_ylabel("Độ cao so với mực nước biển (m)", fontsize=11)
    ax.set_title(
        "Mặt cắt dọc tia tx → rx: đối chiếu biên dạng DEM vs DSM",
        fontsize=13,
        weight="bold",
        pad=10,
    )
    ax.grid(True, linestyle=":", alpha=0.5)
    ax.legend(loc="lower left", bbox_to_anchor=(0.32, 0.02), fontsize=9.5, framealpha=0.95)


def draw_sources_inset(ax):
    """Inset trong main axes — upper-middle, không che y-axis labels."""
    inset = ax.inset_axes([0.40, 0.76, 0.40, 0.23])
    inset.set_xlim(0, 10)
    inset.set_ylim(0, 6)
    inset.axis("off")

    frame = FancyBboxPatch(
        (0.05, 0.05),
        9.9,
        5.9,
        boxstyle="round,pad=0.02,rounding_size=0.15",
        linewidth=1.0,
        edgecolor="#999",
        facecolor="#fbfbfb",
    )
    inset.add_patch(frame)
    inset.text(5, 5.5, "4 nguồn hợp thành DSM", ha="center", fontsize=10, weight="bold")

    sources = [
        ("Copernicus\nGLO-30 DEM", 1.6, 3.6, "#dbe9ff"),
        ("ESA WorldCover\ngap-fill", 1.6, 1.6, "#dbe9ff"),
        ("Google Open\nBuildings", 5.0, 3.6, "#dbe9ff"),
        ("Meta canopy\nheight", 5.0, 1.6, "#dbe9ff"),
    ]
    for text, cx, cy, color in sources:
        box = FancyBboxPatch(
            (cx - 1.3, cy - 0.7),
            2.6,
            1.4,
            boxstyle="round,pad=0.02,rounding_size=0.1",
            linewidth=1.0,
            edgecolor=C_EDGE,
            facecolor=color,
        )
        inset.add_patch(box)
        inset.text(cx, cy, text, ha="center", va="center", fontsize=8.2)

    dsm_box = FancyBboxPatch(
        (7.6, 1.9),
        2.2,
        1.6,
        boxstyle="round,pad=0.02,rounding_size=0.1",
        linewidth=1.2,
        edgecolor=C_EDGE,
        facecolor="#c8e6c9",
    )
    inset.add_patch(dsm_box)
    inset.text(8.7, 2.7, "DSM", ha="center", va="center", fontsize=12, weight="bold")

    for cx, cy in [(1.6, 3.6), (1.6, 1.6), (5.0, 3.6), (5.0, 1.6)]:
        arr = FancyArrowPatch(
            (cx + 1.3, cy),
            (7.6, 2.7),
            arrowstyle="-|>",
            mutation_scale=10,
            linewidth=0.9,
            color="#555",
        )
        inset.add_patch(arr)


def main():
    fig, ax = plt.subplots(figsize=(13, 7.5))
    draw_profile(ax)
    draw_sources_inset(ax)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=180, bbox_inches="tight", facecolor="white")
    print(f"Saved: {OUT}")


if __name__ == "__main__":
    main()
