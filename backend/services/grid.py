"""
services/grid.py — Tiện ích sinh lưới tọa độ.

Loại lưới:
  - Square uniform (`make_grid`):           demand grid cho heatmap simulator.
  - H3 hexagon candidate (`make_h3_candidates`): vị trí ứng viên gateway.
  - H3 hexagon adaptive demand (`make_adaptive_demand_grid`): demand dày ở
    đô thị (res 9 ~174m), thưa ở nông thôn (res 7 ~1.22km).

Tách rạch ròi vì:
  - Square: tile-friendly cho frontend heatmap.
  - Hex: khoảng cách láng giềng đều (định lý Tóth) → tối ưu cho placement
         và tính độ phủ (cell có area đều).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import h3
import numpy as np
from shapely.geometry import MultiPolygon, Polygon


# ─────────────────────────────────────────────────────────────────────────────
# Helpers — degree/meter conversion
# ─────────────────────────────────────────────────────────────────────────────

def meters_to_deg_lat(m: float) -> float:
    return m / 111_320.0


def meters_to_deg_lng(m: float, lat_deg: float) -> float:
    return m / (111_320.0 * math.cos(math.radians(lat_deg)))


# ─────────────────────────────────────────────────────────────────────────────
# Square uniform grid
# ─────────────────────────────────────────────────────────────────────────────

def make_grid(
    min_lat: float, max_lat: float,
    min_lng: float, max_lng: float,
    resolution_m: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Sinh lưới điểm vuông đều từ bbox theo resolution (m)."""
    center_lat = (min_lat + max_lat) / 2
    step_lat = meters_to_deg_lat(resolution_m)
    step_lng = meters_to_deg_lng(resolution_m, center_lat)
    lats = np.arange(min_lat, max_lat, step_lat)
    lngs = np.arange(min_lng, max_lng, step_lng)
    gx, gy = np.meshgrid(lngs, lats)
    return gy.flatten(), gx.flatten()


def bbox_with_padding(
    lats: np.ndarray, lngs: np.ndarray, pad_ratio: float = 0.1,
) -> tuple[float, float, float, float]:
    """Bbox có padding (default 10%) quanh điểm đo."""
    pad_lat = (lats.max() - lats.min()) * pad_ratio or 0.005
    pad_lng = (lngs.max() - lngs.min()) * pad_ratio or 0.005
    return (
        lats.min() - pad_lat, lats.max() + pad_lat,
        lngs.min() - pad_lng, lngs.max() + pad_lng,
    )


# ─────────────────────────────────────────────────────────────────────────────
# H3 hex candidate grid (Phase v3.1 step 3)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class H3Candidate:
    """1 candidate gateway location, sinh từ H3 hex polyfill."""
    h3_index:      str
    h3_resolution: int
    lat:           float
    lng:           float


# H3 cell sizes
#   res 5: ~9.0 km cạnh
#   res 6: ~3.2 km cạnh
#   res 7: ~1.2 km cạnh
#   res 8: ~0.46 km cạnh
#   res 9: ~0.17 km cạnh
H3_DEFAULT_RESOLUTION = 7


def _shapely_polygon_to_h3(poly: Polygon) -> "h3.LatLngPoly":
    """Convert shapely Polygon (lng,lat) → H3 LatLngPoly (lat,lng)."""
    outer = [(p[1], p[0]) for p in poly.exterior.coords]
    holes = [
        [(p[1], p[0]) for p in interior.coords]
        for interior in poly.interiors
    ]
    return h3.LatLngPoly(outer, *holes)


def _polyfill(
    polygon: MultiPolygon | Polygon,
    h3_resolution: int,
) -> set[str]:
    """H3 polyfill (Multi)Polygon → set of H3 cell indices."""
    polygons = (
        list(polygon.geoms) if isinstance(polygon, MultiPolygon) else [polygon]
    )
    cells: set[str] = set()
    for poly in polygons:
        cells.update(h3.polygon_to_cells(_shapely_polygon_to_h3(poly), h3_resolution))
    return cells


def make_h3_candidates(
    polygon: MultiPolygon | Polygon,
    h3_resolution: int = H3_DEFAULT_RESOLUTION,
) -> list[H3Candidate]:
    """Sinh tập H3 hex cells phủ kín polygon."""
    if not 0 <= h3_resolution <= 15:
        raise ValueError(f"h3_resolution phải trong [0, 15], got {h3_resolution}")

    cells = _polyfill(polygon, h3_resolution)
    candidates: list[H3Candidate] = []
    for cell in cells:
        lat, lng = h3.cell_to_latlng(cell)
        candidates.append(H3Candidate(
            h3_index      = cell,
            h3_resolution = h3_resolution,
            lat           = lat,
            lng           = lng,
        ))
    return candidates


# ─────────────────────────────────────────────────────────────────────────────
# H3 adaptive demand grid (Phase v3.1 step 5b)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DemandCell:
    """1 demand point cho optimizer. Weight default 1.0; tương lai = WorldPop."""
    h3_index:      str
    h3_resolution: int
    lat:           float
    lng:           float
    density_class: str       # "urban" | "rural"
    weight:        float     # default 1.0


# Mapping spec → H3 res (kịch bản POC):
#   urban → res 8 (cạnh ~460m, ~0.74 km²/cell — khu phố level, sweet spot)
#   rural → res 7 (cạnh ~1.22km, trùng candidate — so cell tự nhiên)
# Có thể nâng urban lên res 9 (~174m) nếu sau này cần độ chính xác block-level.
URBAN_H3_RESOLUTION_DEFAULT = 8
RURAL_H3_RESOLUTION_DEFAULT = 7


def _polyfill_to_demand(
    polygon: MultiPolygon | Polygon,
    h3_resolution: int,
    *,
    density_class: str,
    weight: float = 1.0,
) -> list[DemandCell]:
    """H3 polyfill polygon → list[DemandCell]."""
    cells = _polyfill(polygon, h3_resolution)
    result: list[DemandCell] = []
    for cell in cells:
        lat, lng = h3.cell_to_latlng(cell)
        result.append(DemandCell(
            h3_index      = cell,
            h3_resolution = h3_resolution,
            lat           = lat,
            lng           = lng,
            density_class = density_class,
            weight        = weight,
        ))
    return result


def make_adaptive_demand_grid(
    full_polygon:   MultiPolygon | Polygon,
    urban_polygon:  MultiPolygon | Polygon | None = None,
    *,
    urban_h3_res:   int   = URBAN_H3_RESOLUTION_DEFAULT,
    rural_h3_res:   int   = RURAL_H3_RESOLUTION_DEFAULT,
    urban_weight:   float = 1.0,
    rural_weight:   float = 1.0,
) -> list[DemandCell]:
    """
    Sinh demand grid 2 lớp adaptive.

    Algorithm:
      1. Polyfill `urban_polygon` ở `urban_h3_res` (dày) → cells class="urban"
      2. `rural_polygon = full_polygon - urban_polygon` (shapely difference)
      3. Polyfill `rural_polygon` ở `rural_h3_res` (thưa) → cells class="rural"
      4. Concat cả hai

    Nếu `urban_polygon = None` → uniform rural grid toàn full_polygon.

    Args:
        full_polygon:  Toàn AOI (Đà Nẵng mới ~12000 km²).
        urban_polygon: Vùng đô thị (vd union 23 phường, ~950 km²).
        urban_h3_res:  H3 resolution cho urban (default 9 = ~174m).
        rural_h3_res:  H3 resolution cho rural (default 7 = ~1.22km).
        urban_weight:  Default weight cho urban cells (= 1.0; sau này dùng WorldPop).
        rural_weight:  Default weight cho rural cells.

    Returns:
        list[DemandCell] không sort. Tổng count phụ thuộc diện tích + resolution.
    """
    if not 0 <= urban_h3_res <= 15:
        raise ValueError(f"urban_h3_res phải trong [0, 15], got {urban_h3_res}")
    if not 0 <= rural_h3_res <= 15:
        raise ValueError(f"rural_h3_res phải trong [0, 15], got {rural_h3_res}")

    cells: list[DemandCell] = []

    if urban_polygon is not None:
        cells.extend(_polyfill_to_demand(
            urban_polygon, urban_h3_res,
            density_class="urban", weight=urban_weight,
        ))
        rural_polygon = full_polygon.difference(urban_polygon)
    else:
        rural_polygon = full_polygon

    if not rural_polygon.is_empty:
        cells.extend(_polyfill_to_demand(
            rural_polygon, rural_h3_res,
            density_class="rural", weight=rural_weight,
        ))

    return cells