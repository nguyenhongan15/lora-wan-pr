"""
services/heatmap_png.py — Render heatmap RSSI/SNR thành PNG static.

Port từ LoRa-survey-heatmap (src/heatmap.py::HeatMapGenerator._plot) —
giữ nguyên các yếu tố tạo nên báo cáo nhìn đẹp: imshow interpolated grid,
contour có nhãn, colorbar dọc, scatter điểm đo có viền đen, alpha overlay.

Khác reference:
  - Tọa độ trục là (lng, lat) GPS thay vì pixel — không cần floorplan image.
  - Dùng services.interpolation.interpolate() (đã có RBF + corner-anchoring)
    thay vì gọi scipy.Rbf trực tiếp → không duplicate logic.
  - Không có background image; nền là trục matplotlib trắng. Có thể thêm
    contextily basemap sau nếu cần.

Trả về PNG bytes; route gói vào fastapi Response.
"""

from __future__ import annotations

import io
import logging
from typing import Literal

import matplotlib

matplotlib.use("Agg")  # non-GUI backend cho server context, MUST set trước pyplot

import matplotlib.pyplot as plt           # noqa: E402
import numpy as np                        # noqa: E402
from matplotlib import cm                 # noqa: E402
from matplotlib.colors import Normalize   # noqa: E402

from services.interpolation import interpolate  # noqa: E402

logger = logging.getLogger(__name__)

Metric = Literal["rssi", "snr"]

# Ngưỡng LoRa Alliance CVT (đồng thuận với HeatmapLayer.jsx + KML exporter)
_DEFAULT_VMIN = {"rssi": -120.0, "snr": -20.0}
_DEFAULT_VMAX = {"rssi": -60.0,  "snr":  10.0}
_UNIT         = {"rssi": "dBm",  "snr":  "dB"}
_TITLE        = {
    "rssi": "Received Signal Strength Indication (RSSI)",
    "snr":  "Signal-to-Noise Ratio (SNR)",
}


def render_heatmap_png(
    rows: list[dict],
    *,
    metric: Metric         = "rssi",
    method: str            = "rbf",
    resolution_m: int      = 100,
    colormap: str          = "RdYlBu_r",
    contours: int | None   = 5,
    show_points: bool      = True,
    alpha: float           = 0.6,
    dpi: int               = 200,
    vmin: float | None     = None,
    vmax: float | None     = None,
    title_suffix: str      = "",
) -> bytes:
    """
    Sinh PNG heatmap cho 1 campaign.

    Args:
        rows:         List dict từ DB query với keys 'lat', 'lng',
                      'rssi_dbm', 'snr_db'. Tối thiểu 3 điểm.
        metric:       'rssi' (rssi_dbm) | 'snr' (snr_db).
        method:       'rbf' | 'idw' | 'kriging' | 'delaunay' — chuyển thẳng
                      cho services.interpolation.interpolate().
        resolution_m: Cell size grid (m). Nhỏ hơn → mượt hơn nhưng chậm hơn.
        colormap:     Tên matplotlib cmap. Mặc định RdYlBu_r (đồng thuận với
                      HeatmapLayer.jsx — đỏ = mạnh, xanh = yếu).
        contours:     Số đường đồng mức. None = không vẽ.
        show_points:  Vẽ scatter điểm đo (viền đen, fill theo cmap).
        alpha:        Độ trong suốt heatmap layer (0..1).
        dpi:          Độ phân giải xuất file (200 vừa cho web, 300 cho in).
        vmin/vmax:    Range thang màu. None = dùng ngưỡng LoRa Alliance.
        title_suffix: Append vào title (ví dụ tên campaign).

    Returns:
        PNG bytes — sẵn sàng đưa vào fastapi Response.

    Raises:
        ValueError: Nếu < 3 điểm có giá trị metric hợp lệ (RBF cần ≥ 3).
    """
    # ── Trích lat/lng + giá trị metric, lọc None ────────────────────────────
    col = "rssi_dbm" if metric == "rssi" else "snr_db"
    pts = [
        (r["lat"], r["lng"], r[col])
        for r in rows
        if r.get("lat") is not None
        and r.get("lng") is not None
        and r.get(col)  is not None
    ]
    if len(pts) < 3:
        raise ValueError(
            f"Cần ≥ 3 điểm có {col} hợp lệ để nội suy, chỉ có {len(pts)}."
        )

    lats = [p[0] for p in pts]
    lngs = [p[1] for p in pts]
    vals = [p[2] for p in pts]

    # ── Nội suy bằng pipeline có sẵn (RBF + corner-anchoring) ───────────────
    grid_lats, grid_lngs, predicted, _unc = interpolate(
        lats, lngs, vals,
        method        = method,         # type: ignore[arg-type]
        resolution_m  = resolution_m,
    )

    # ── Reshape predicted về 2D grid để imshow ──────────────────────────────
    # interpolate() trả flatten arrays từ meshgrid (lats × lngs). Dò đúng
    # số cột bằng cách đếm unique lng (np.arange step đều → unique giữ thứ tự).
    n_lng = int(np.unique(grid_lngs).size)
    n_lat = int(np.unique(grid_lats).size)
    if n_lat * n_lng != predicted.size:
        # Fallback an toàn nếu shape không khớp (edge case grid lệch)
        n_lat = predicted.size // n_lng
    z = predicted.reshape(n_lat, n_lng)

    # ── Range thang màu ─────────────────────────────────────────────────────
    if vmin is None:
        vmin = _DEFAULT_VMIN[metric]
    if vmax is None:
        vmax = _DEFAULT_VMAX[metric]

    # Bbox lat/lng (extent dùng cho imshow + contour)
    lo_min, lo_max = float(grid_lngs.min()), float(grid_lngs.max())
    la_min, la_max = float(grid_lats.min()), float(grid_lats.max())
    extent = (lo_min, lo_max, la_min, la_max)

    # ── Plot ────────────────────────────────────────────────────────────────
    cmap = plt.get_cmap(colormap)
    norm = Normalize(vmin=vmin, vmax=vmax, clip=True)
    mapper = cm.ScalarMappable(norm=norm, cmap=cmap)

    fig, ax = plt.subplots(figsize=(10, 8))

    title = _TITLE[metric]
    if title_suffix:
        title = f"{title} — {title_suffix}"
    ax.set_title(title, fontsize=11)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")

    # imshow: lưu ý origin='lower' vì lat tăng từ dưới lên trên (khác pixel
    # coords trong reference dùng origin='upper'). Phải khớp với extent.
    img = ax.imshow(
        z,
        extent      = extent,
        origin      = "lower",
        alpha       = alpha,
        cmap        = cmap,
        vmin        = vmin,
        vmax        = vmax,
        aspect      = "auto",
        zorder      = 10,
        interpolation = "bilinear",
    )

    # Contour lines (giữ nguyên cách reference vẽ + clabel)
    if contours and contours > 0:
        try:
            cs = ax.contour(
                z,
                levels      = contours,
                colors      = "k",
                linewidths  = 0.5,
                alpha       = 0.4,
                extent      = extent,
                origin      = "lower",
                zorder      = 20,
            )
            ax.clabel(cs, inline=True, fontsize=6)
        except Exception as e:   # contour có thể fail khi z đồng nhất
            logger.warning("contour_failed: %s", e)

    # Colorbar
    cbar = fig.colorbar(
        img, ax=ax,
        orientation="vertical", shrink=0.84, aspect=20, pad=0.02,
        label=_UNIT[metric],
    )
    cbar.ax.tick_params(labelsize=8)

    # Scatter điểm đo (viền đen, fill = giá trị mapped — đồng nhất visual
    # giữa điểm đo và heatmap nền)
    if show_points:
        ax.scatter(
            lngs, lats,
            c            = [mapper.to_rgba(v) for v in vals],
            edgecolors   = "black",
            linewidths   = 0.4,
            s            = 22,
            zorder       = 30,
        )

    ax.set_xlim(lo_min, lo_max)
    ax.set_ylim(la_min, la_max)
    ax.grid(True, linestyle=":", alpha=0.3, zorder=5)

    # ── Xuất PNG bytes ──────────────────────────────────────────────────────
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()
