"""Vẽ Hình 4.4 — Kiến trúc triển khai mô hình truyền sóng vật lý.

Sơ đồ kiến trúc theo phong cách báo cáo: ô chỉ chứa TỪ KHOÁ, mũi tên theo quy
ước (liền = luồng gọi/xử lý, đứt = luồng dữ liệu), hình trụ = nguồn dữ liệu/CSDL,
hình chữ nhật bo góc = mô-đun xử lý. Có khung chú thích (legend).

Nội dung phản ánh đúng mã nguồn:
  * 2 đường tiêu thụ: /predict (Stage1ItuModel) + Heatmap (precompute_rssi_heatmap)
  * Lõi dùng chung: infrastructure/itu/p1812_config (configure_p1812_propagation +
    p2108_clutter_db) -> KHÔNG drift tham số giữa 2 đường.
  * Engine: crc-covlib 4.6.2 hiện thực ITU-R P.1812-7 / P.2108-1 / P.2109.
  * Dữ liệu: DEM Copernicus GLO-30 (engine đọc địa hình); PostGIS geo.gateways
    (bias/NF/tham số GW, áp ở cả 2 đường); Survey ts.survey_training (ghi đè ô đo,
    CHỈ heatmap).

Chạy: python scripts/figures/draw_fig_44_arch.py
Xuất: docs/anh/fig_44_arch.png
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
from matplotlib.patches import Ellipse, FancyArrowPatch, FancyBboxPatch, Rectangle

# --- Font: Times New Roman (hỗ trợ tiếng Việt), fallback DejaVu Serif ----------
_SERIF = [f.name for f in fm.fontManager.ttflist]
_FONT = "Times New Roman" if "Times New Roman" in _SERIF else "DejaVu Serif"
plt.rcParams.update(
    {
        "font.family": _FONT,
        "axes.unicode_minus": False,
        "figure.dpi": 200,
        "savefig.dpi": 200,
    }
)

# --- Bảng màu báo cáo (muted) -------------------------------------------------
C_CONSUMER = ("#dce8f5", "#2f5d8a")  # xanh dương nhạt — mô-đun tiêu thụ
C_CORE = ("#f7dada", "#a23a3d")  # đỏ nhạt — lõi dùng chung (nhấn mạnh)
C_ENGINE = ("#dff0d8", "#4f7a3a")  # xanh lá nhạt — engine
C_DATA = ("#fcecca", "#b9852f")  # cam nhạt — nguồn dữ liệu
C_TEXT = "#16213a"
C_ARROW = "#3a3a3a"
C_ARROW_DATA = "#7a6a30"


def rounded_box(ax, x, y, w, h, face, edge, lw=1.6):
    box = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0,rounding_size=2.2",
        facecolor=face,
        edgecolor=edge,
        linewidth=lw,
        zorder=3,
        mutation_aspect=1.0,
    )
    ax.add_patch(box)


def cylinder(ax, x, y, w, h, face, edge, lw=1.6):
    """Hình trụ CSDL: thân chữ nhật + 2 ellipse (nắp trên đầy, đáy cong)."""
    ry = h * 0.11
    # thân
    ax.add_patch(Rectangle((x, y + ry), w, h - 2 * ry, facecolor=face, edgecolor="none", zorder=3))
    # cạnh thân (2 đường dọc)
    ax.plot([x, x], [y + ry, y + h - ry], color=edge, lw=lw, zorder=3.1)
    ax.plot([x + w, x + w], [y + ry, y + h - ry], color=edge, lw=lw, zorder=3.1)
    # đáy (nửa ellipse trước)
    ax.add_patch(
        Ellipse((x + w / 2, y + ry), w, 2 * ry, facecolor=face, edgecolor=edge, lw=lw, zorder=3.05)
    )
    # che nửa trên của đáy bằng thân đã vẽ; nắp trên (ellipse đầy)
    ax.add_patch(
        Ellipse(
            (x + w / 2, y + h - ry), w, 2 * ry, facecolor=face, edgecolor=edge, lw=lw, zorder=3.2
        )
    )


def arrow(ax, p0, p1, *, dashed=False, color=None, lw=1.9, rad=0.0):
    color = color or (C_ARROW_DATA if dashed else C_ARROW)
    style = (0, (5, 3)) if dashed else "solid"
    a = FancyArrowPatch(
        p0,
        p1,
        arrowstyle="-|>",
        mutation_scale=16,
        linewidth=lw,
        color=color,
        linestyle=style,
        connectionstyle=f"arc3,rad={rad}",
        zorder=2.5,
        shrinkA=2,
        shrinkB=2,
    )
    ax.add_patch(a)


def label(
    ax,
    x,
    y,
    txt,
    *,
    size=12,
    weight="normal",
    style="normal",
    color=C_TEXT,
    ha="center",
    va="center",
    family=None,
):
    ax.text(
        x,
        y,
        txt,
        ha=ha,
        va=va,
        fontsize=size,
        fontweight=weight,
        fontstyle=style,
        color=color,
        zorder=4,
        family=family or _FONT,
    )


def arrow_tag(ax, x, y, txt, *, color=C_ARROW, size=9.5):
    ax.text(
        x,
        y,
        txt,
        ha="center",
        va="center",
        fontsize=size,
        fontstyle="italic",
        color=color,
        zorder=4.5,
        bbox={
            "boxstyle": "round,pad=0.18",
            "facecolor": "white",
            "edgecolor": "none",
            "alpha": 0.9,
        },
    )


# ============================== VẼ HÌNH =======================================
fig, ax = plt.subplots(figsize=(13.2, 9.0))
ax.set_xlim(0, 160)
ax.set_ylim(0, 110)
ax.axis("off")

# ---- Tiêu đề ----
label(ax, 80, 105.5, "Kiến trúc triển khai mô hình truyền sóng vật lý", size=18, weight="bold")

MONO = "Consolas" if "Consolas" in _SERIF else _FONT

# ---- Tầng 1: 2 mô-đun tiêu thụ ----
# /predict
rounded_box(ax, 14, 80, 50, 16, *C_CONSUMER)
label(ax, 39, 91.5, "/predict", size=14, weight="bold", color=C_CONSUMER[1])
label(ax, 39, 87.0, "Dự đoán điểm tín hiệu", size=11.5)
label(ax, 39, 83.0, "«Stage1ItuModel»", size=10.5, style="italic", color="#555")

# Heatmap
rounded_box(ax, 96, 80, 50, 16, *C_CONSUMER)
label(ax, 121, 91.5, "Heatmap", size=14, weight="bold", color=C_CONSUMER[1])
label(ax, 121, 87.0, "Bản đồ ước lượng vùng phủ", size=11.5)
label(ax, 121, 83.0, "«precompute_rssi_heatmap»", size=10.5, style="italic", color="#555")

# ---- Tầng 2: Lõi dùng chung ----
rounded_box(ax, 46, 58, 68, 15, *C_CORE, lw=2.1)
label(ax, 80, 69.5, "LÕI CẤU HÌNH DÙNG CHUNG", size=13, weight="bold", color=C_CORE[1])
label(ax, 80, 65.2, "p1812_config", size=11.5, style="italic", color="#555")
label(ax, 80, 61.2, "configure_p1812_propagation( )  ·  p2108_clutter_db( )", size=10.5)

# ---- Tầng 3: Engine truyền sóng ----
rounded_box(ax, 46, 38, 68, 15, *C_ENGINE)
label(
    ax,
    80,
    49.5,
    "ENGINE TRUYỀN SÓNG — crc-covlib 4.6.2",
    size=12.5,
    weight="bold",
    color=C_ENGINE[1],
)
label(ax, 80, 44.8, "P.1812-7   ·   P.2108-1   ·   P.2109", size=12, weight="bold")
label(
    ax,
    80,
    40.8,
    "nhiễu xạ địa hình · clutter thống kê · xuyên tường",
    size=9.5,
    style="italic",
    color="#555",
)

# ---- Nguồn dữ liệu (hình trụ) ----
# DEM (dưới engine — engine đọc địa hình)
cylinder(ax, 57, 13, 46, 16, *C_DATA)
label(ax, 80, 23.4, "DEM — Copernicus GLO-30", size=11.5, weight="bold", color="#7a5713")
label(ax, 80, 18.6, "DTM + DSM  (30 m, GeoTIFF)", size=10.5)

# PostGIS (trái — hiệu chỉnh, áp ở cả 2 đường)
cylinder(ax, 2, 54, 38, 18, *C_DATA)
label(ax, 21, 66.6, "PostGIS · geo.gateways", size=11, weight="bold", color="#7a5713")
label(ax, 21, 62.4, "rssi_bias_db · noise_floor_dbm", size=9.2)
label(ax, 21, 58.8, "vị trí · ăng-ten · công suất", size=9.2)

# Survey (phải — ground truth, chỉ heatmap)
cylinder(ax, 120, 54, 38, 18, *C_DATA)
label(ax, 139, 66.6, "Survey · ts.survey_training", size=10.5, weight="bold", color="#7a5713")
label(ax, 139, 62.2, "RSSI đo thực tế", size=9.5)
label(ax, 139, 58.6, "(ground truth)", size=9.0, style="italic", color="#555")

# ============================== MŨI TÊN =======================================
# Tiêu thụ -> lõi (liền, "gọi")
arrow(ax, (39, 80), (62, 73))
arrow(ax, (121, 80), (98, 73))
arrow_tag(ax, 47, 77.2, "gọi")
arrow_tag(ax, 113, 77.2, "gọi")

# Lõi -> engine (liền)
arrow(ax, (80, 58), (80, 53))
arrow_tag(ax, 80, 55.6, "cấu hình & chạy")

# DEM -> engine (đứt, dữ liệu)
arrow(ax, (80, 29), (80, 38), dashed=True)
arrow_tag(ax, 80, 33.4, "đọc địa hình", color=C_ARROW_DATA)

# PostGIS -> lõi (đứt, hiệu chỉnh — áp ở cả 2 đường vì lõi dùng chung)
arrow(ax, (40, 65), (46, 65), dashed=True)
arrow_tag(ax, 41, 69.5, "hiệu chỉnh", color=C_ARROW_DATA, size=9.0)

# Survey -> Heatmap (đứt, dữ liệu; CHỈ heatmap)
arrow(ax, (132, 73), (123, 80), dashed=True)
arrow_tag(ax, 136, 77.5, "ghi đè ô đo", color=C_ARROW_DATA, size=9.0)

# ============================== CHÚ THÍCH =====================================
lx, ly, lw_, lh = 4, 3, 50, 23
ax.add_patch(
    FancyBboxPatch(
        (lx, ly),
        lw_,
        lh,
        boxstyle="round,pad=0,rounding_size=1.5",
        facecolor="#fbfbfb",
        edgecolor="#999",
        linewidth=1.0,
        zorder=3,
    )
)
label(ax, lx + 3, ly + lh - 3.2, "CHÚ THÍCH", size=10.5, weight="bold", ha="left", color="#444")

# mẫu: rounded box
rounded_box(ax, lx + 3, ly + 12.8, 7, 4, "#e9e9e9", "#666", lw=1.2)
label(ax, lx + 12, ly + 14.8, "Mô-đun xử lý", size=9.3, ha="left")
# mẫu: cylinder
cylinder(ax, lx + 3, ly + 6.5, 7, 5.0, "#e9e9e9", "#666", lw=1.2)
label(ax, lx + 12, ly + 9.0, "Nguồn dữ liệu / CSDL", size=9.3, ha="left")
# mẫu: mũi tên liền
arrow(ax, (lx + 3, ly + 4.0), (lx + 10, ly + 4.0), lw=1.7)
label(ax, lx + 12, ly + 4.0, "Gọi / xử lý", size=9.3, ha="left")
# mẫu: mũi tên đứt
arrow(ax, (lx + 30, ly + 4.0), (lx + 37, ly + 4.0), dashed=True, lw=1.7)
label(ax, lx + 39, ly + 4.0, "Dữ liệu", size=9.3, ha="left")

# ---- Lưu ----
OUT = Path(__file__).resolve().parents[2] / "docs" / "anh" / "fig_44_arch.png"
fig.savefig(OUT, bbox_inches="tight", facecolor="white", pad_inches=0.15)
print(f"Saved -> {OUT}")
