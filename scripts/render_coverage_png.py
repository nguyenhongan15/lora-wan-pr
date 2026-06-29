"""Render composite RSSI coverage GeoJSON → PNG để xem nhanh (offline, không cần web).

Dùng palette ESTIMATE_RSSI_BINS của frontend (legend.js) để màu khớp bản đồ thật.
Overlay vị trí gateway (gateway_table.csv) + legend + lưới lat/lon.

Usage:
    python scripts/render_coverage_png.py \
        --in apps/web-app/public/coverage/rssi/composite.geojson \
        --gateways services/ml-service/data/gateway_table.csv \
        --out docs/anh/coverage_estimate_preview.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:  # console Windows cp1252 → in '→' vỡ; ép UTF-8 (no-op trên Linux)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:
    pass

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import pandas as pd

# bin_id → (color, label). Khớp ESTIMATE_RSSI_BINS trong apps/web-app/src/components/legend.js.
BIN_STYLE = {
    1: ("#FF0000", "> -100 dBm (rất mạnh)"),
    2: ("#FF8000", "-105..-100 dBm"),
    3: ("#FFFF00", "-110..-105 dBm"),
    4: ("#00FF00", "-115..-110 dBm"),
    5: ("#00FFFF", "-120..-115 dBm"),
    6: ("#0000FF", "< -120 dBm (yếu)"),
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in", dest="inp", required=True, help="composite.geojson")
    ap.add_argument("--gateways", default="", help="gateway_table.csv (gw_lat,gw_lon) — optional")
    ap.add_argument("--out", required=True, help="PNG output")
    ap.add_argument("--title", default="Bản đồ ước lượng vùng phủ RSSI (P.1812 + survey overlay)")
    args = ap.parse_args()

    gdf = gpd.read_file(args.inp)
    if gdf.empty:
        print(f"ERROR: {args.inp} rỗng")
        return 1
    minx, miny, maxx, maxy = gdf.total_bounds
    # Aspect ~ đúng tỉ lệ địa lý ở vĩ độ này.
    import math

    lat_mid = (miny + maxy) / 2
    aspect = (maxx - minx) * math.cos(math.radians(lat_mid)) / (maxy - miny)
    fig_h = 10.0
    fig, ax = plt.subplots(figsize=(fig_h * aspect + 2.5, fig_h))
    ax.set_facecolor("#e9edf0")  # nền xám nhạt = vùng không phủ / biển

    for _, row in gdf.iterrows():
        b = int(row["bin"])
        color, _label = BIN_STYLE.get(b, ("#888888", str(b)))
        gpd.GeoSeries([row.geometry]).plot(ax=ax, color=color, edgecolor="none")

    # Overlay gateways.
    if args.gateways and Path(args.gateways).is_file():
        gw = pd.read_csv(args.gateways)
        latc = "gw_lat" if "gw_lat" in gw.columns else "lat"
        lonc = "gw_lon" if "gw_lon" in gw.columns else "lon"
        ax.scatter(
            gw[lonc],
            gw[latc],
            marker="^",
            s=70,
            c="black",
            edgecolors="white",
            linewidths=0.8,
            zorder=5,
            label="Gateway",
        )

    ax.set_xlim(minx, maxx)
    ax.set_ylim(miny, maxy)
    ax.set_xlabel("Kinh độ (°E)")
    ax.set_ylabel("Vĩ độ (°N)")
    ax.set_title(args.title, fontsize=13)

    handles = [mpatches.Patch(color=c, label=lbl) for _, (c, lbl) in sorted(BIN_STYLE.items())]
    if args.gateways:
        handles.append(
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
    ax.legend(handles=handles, loc="upper right", fontsize=9, framealpha=0.9, title="RSSI")

    fig.tight_layout()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=130, bbox_inches="tight")
    print(f"Saved → {out}  (bbox lon[{minx:.3f},{maxx:.3f}] lat[{miny:.3f},{maxy:.3f}])")
    return 0


if __name__ == "__main__":
    sys.exit(main())
