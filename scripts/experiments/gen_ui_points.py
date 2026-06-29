"""Render lớp 'điểm khảo sát' (survey points) tô màu theo RSSI — minh hoạ giao diện."""

import os

import matplotlib
import numpy as np
import psycopg

matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt

BINS = [
    (-1e9, -120, "#0000FF", "< -120 dBm"),
    (-120, -115, "#00FFFF", "-120..-115"),
    (-115, -110, "#00FF00", "-115..-110"),
    (-110, -105, "#FFFF00", "-110..-105"),
    (-105, -100, "#FF8000", "-105..-100"),
    (-100, 1e9, "#FF0000", "> -100 dBm"),
]
u = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
with psycopg.connect(u) as c, c.cursor() as cur:
    cur.execute("""SELECT ST_Y(location::geometry), ST_X(location::geometry), rssi_dbm
        FROM ts.survey_training
        WHERE ST_Y(location::geometry) BETWEEN 15.8 AND 16.3
          AND ST_X(location::geometry) BETWEEN 107.9 AND 108.5 AND rssi_dbm IS NOT NULL""")
    pts = cur.fetchall()
    cur.execute("""SELECT ST_Y(location::geometry), ST_X(location::geometry)
        FROM geo.gateways WHERE is_public=true
          AND ST_Y(location::geometry) BETWEEN 15.8 AND 16.3
          AND ST_X(location::geometry) BETWEEN 107.9 AND 108.5""")
    gws = cur.fetchall()
lat = np.array([p[0] for p in pts])
lon = np.array([p[1] for p in pts])
r = np.array([p[2] for p in pts])
fig, ax = plt.subplots(figsize=(8, 7.4))
ax.set_facecolor("#eef1f4")
for lo, hi, col, _ in BINS:
    m = (r >= lo) & (r < hi)
    if m.any():
        ax.scatter(lon[m], lat[m], s=6, c=col, alpha=0.55, edgecolors="none")
if gws:
    gla = [g[0] for g in gws]
    glo = [g[1] for g in gws]
    ax.scatter(glo, gla, marker="^", s=80, c="black", edgecolors="white", linewidths=0.9, zorder=5)
ax.set_xlabel("Kinh độ (°E)")
ax.set_ylabel("Vĩ độ (°N)")
ax.set_title(f"Lớp điểm khảo sát (RSSI đo thực) — {len(pts)} điểm")
h = [mpatches.Patch(color=c, label=lbl) for _, _, c, lbl in BINS]
h.append(
    plt.Line2D(
        [],
        [],
        marker="^",
        color="black",
        markerfacecolor="black",
        markeredgecolor="white",
        linestyle="",
        markersize=9,
        label="Gateway",
    )
)
ax.legend(handles=h, loc="upper right", fontsize=8, framealpha=0.9, title="RSSI")
ax.grid(alpha=0.25)
fig.tight_layout()
fig.savefig("/app/reports/fig_ui_points.png", dpi=140)
print(f"saved fig_ui_points.png  n={len(pts)} gws={len(gws)}")
