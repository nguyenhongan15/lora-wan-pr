"""Vẽ sơ đồ kiến trúc thành phần tổng thể — LoRa Coverage Platform.

Output: docs/anh/arch_overview.png
Chạy:   python docs/code/arch_overview.py
"""

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

OUT = Path(__file__).resolve().parent.parent / "anh" / "arch_overview.png"
OUT.parent.mkdir(parents=True, exist_ok=True)

PALETTE = {
    "frontend": "#cfe2ff",
    "proxy": "#e2e3e5",
    "service": "#d1e7dd",
    "queue": "#fff3cd",
    "db": "#e7d8f5",
    "external": "#ffe5d0",
}


def box(ax, x, y, w, h, text, color, fontsize=10):
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.04,rounding_size=0.18",
        linewidth=1.2,
        edgecolor="#333",
        facecolor=color,
        zorder=2,
    )
    ax.add_patch(patch)
    ax.text(
        x + w / 2,
        y + h / 2,
        text,
        ha="center",
        va="center",
        fontsize=fontsize,
        fontweight="bold",
        zorder=3,
    )
    return (x, y, w, h)


def arrow(
    ax, p1, p2, label=None, style="->", color="#222", rad=0.0, label_xy=None, fontsize=9, lw=1.4
):
    arr = FancyArrowPatch(
        p1,
        p2,
        arrowstyle=style,
        mutation_scale=14,
        linewidth=lw,
        color=color,
        connectionstyle=f"arc3,rad={rad}",
        zorder=1,
    )
    ax.add_patch(arr)
    if label:
        if label_xy is None:
            label_xy = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
        ax.text(
            label_xy[0],
            label_xy[1],
            label,
            ha="center",
            va="center",
            fontsize=fontsize,
            color=color,
            bbox={"boxstyle": "round,pad=0.22", "fc": "white", "ec": "none", "alpha": 0.9},
            zorder=4,
        )


fig, ax = plt.subplots(figsize=(14, 10))
ax.set_xlim(0, 14)
ax.set_ylim(2.0, 10)
ax.set_axis_off()

# Tầng trình bày
box(
    ax,
    4.0,
    8.7,
    6.0,
    0.9,
    "React Web App\n(Vite · MapLibre GL · TanStack Query)",
    PALETTE["frontend"],
)

# Reverse proxy
box(ax, 4.0, 7.2, 6.0, 0.7, "Nginx reverse proxy", PALETTE["proxy"])

# Dịch vụ backend
box(ax, 4.5, 5.0, 4.5, 1.1, "api-service\n(FastAPI · 5-tầng Clean Arch)", PALETTE["service"])
box(ax, 10.2, 5.0, 3.5, 1.1, "ml-service\n(FastAPI · Extra Trees)", PALETTE["service"])

# Hệ thống bên ngoài
box(ax, 0.2, 5.1, 3.0, 0.9, "ChirpStack\nserver", PALETTE["external"])

# Database (chuyển sang trái)
box(
    ax,
    0.5,
    2.6,
    5.0,
    0.9,
    "PostgreSQL 17 + PostGIS + TimescaleDB\n(schemas: geo · ts · auth · ml · ops)",
    PALETTE["db"],
)

# Queue + cache (Celery chuyển sang phải, dưới ml-service)
box(ax, 5.8, 2.6, 2.6, 0.9, "Valkey broker\n(queue · rate-limit)", PALETTE["queue"])
box(ax, 10.5, 2.6, 3.0, 0.9, "Celery worker\n(retrain · rebuild)", PALETTE["queue"])

# --- Mũi tên ---

# React -> Nginx
arrow(ax, (7.0, 8.7), (7.0, 7.9), label="HTTPS / SSE", label_xy=(7.7, 8.3))

# Nginx -> api-service
arrow(ax, (6.5, 7.2), (6.0, 6.1))

# api-service <-> ml-service
arrow(ax, (9.0, 5.55), (10.2, 5.55), label="gRPC / HTTP", style="<->", label_xy=(9.6, 5.85))

# ChirpStack -> api-service (webhook)
arrow(ax, (3.2, 5.55), (4.5, 5.55), label="webhook", label_xy=(3.85, 5.85))

# api-service <-> Postgres (trái)
arrow(ax, (5.3, 5.0), (4.3, 3.5), style="<->")
# api-service <-> Valkey (giữa)
arrow(ax, (6.5, 5.0), (6.6, 3.5), style="<->")
# api-service <-> Celery (phải)
arrow(ax, (7.8, 5.0), (11.2, 3.5), style="<->")

# Valkey <-> Celery (broker)
arrow(ax, (8.4, 3.05), (10.5, 3.05), label="broker", label_xy=(9.45, 3.35), style="<->")

# Celery -> ml-service: hot-reload artifact (mũi tên dọc ngắn, Celery ngay dưới ml-service)
arrow(
    ax,
    (12.0, 3.5),
    (12.0, 5.0),
    label="hot-reload artifact\n(joblib · POST /admin/reload)",
    color="#1565c0",
    label_xy=(12.0, 4.25),
    lw=2.0,
)

# Legend
legend_items = [
    ("Frontend", PALETTE["frontend"]),
    ("Reverse proxy", PALETTE["proxy"]),
    ("Dịch vụ backend", PALETTE["service"]),
    ("Queue / cache", PALETTE["queue"]),
    ("Database", PALETTE["db"]),
    ("Hệ thống ngoài", PALETTE["external"]),
]
handles = [plt.Rectangle((0, 0), 1, 1, facecolor=c, edgecolor="#333") for _, c in legend_items]
ax.legend(
    handles,
    [n for n, _ in legend_items],
    loc="lower left",
    ncol=3,
    fontsize=9,
    frameon=False,
    bbox_to_anchor=(0.0, -0.02),
)

plt.tight_layout()
plt.savefig(OUT, dpi=180, bbox_inches="tight")
print(f"Saved: {OUT}")
