"""Urbanization index lookup (precomputed GeoTIFF).

Plan v1 §3.5: `urbanization_index` = building footprint area fraction trong
radius 200m quanh target. Range [0, 1] — rural ~0.01, dense urban ~0.4.

Pipeline 2 bước:
  1. Offline build (rare, manual): `scripts/build_urbanization_grid.py` đọc
     OSM PBF VN, rasterize building footprint, smooth bằng radius-200m mean
     filter, output `urbanization_vn.tif`.
  2. Runtime (mỗi predict): module này đọc precomputed GeoTIFF, lookup tại
     (lat, lon) qua nearest-neighbor (raster đã smooth).

Lý do tách offline/runtime: PBF parser nặng (~1GB file), không phù hợp load
ở serving process. Raster lookup O(1) phù hợp ms-level inference budget.

Path env var: `LORA_URBANIZATION_PATH`.
"""

from __future__ import annotations

from typing import Protocol

import rasterio
from rasterio.transform import rowcol


class _Point(Protocol):
    """Duck-typed lat/lon. Target khớp.

    @property cho phép frozen dataclass thoả Protocol.
    """

    @property
    def latitude(self) -> float: ...

    @property
    def longitude(self) -> float: ...


class UrbanizationLookup:
    """Precomputed urbanization raster reader.

    What: index_at(point) → float ∈ [0, 1].
    Hidden: rasterio handle, transform, nodata fallback.
    Failure mode:
      - File missing → __init__ raises FileNotFoundError (fail-fast).
      - Point ngoài bbox → 0.0 (rural fallback). Tương đồng DemLookup.
    """

    def __init__(self, raster_path: str) -> None:
        self._dataset = rasterio.open(raster_path)
        self._band = self._dataset.read(1)
        self._nodata = self._dataset.nodata
        self._transform = self._dataset.transform
        self._height = self._dataset.height
        self._width = self._dataset.width

    def index_at(self, point: _Point) -> float:
        """Urbanization index ∈ [0, 1] tại (lat, lon).

        Raster đã được smooth bằng radius-200m mean filter trong build script,
        nên runtime chỉ cần nearest-neighbor pixel — không cần re-aggregate.
        """
        try:
            row, col = rowcol(self._transform, point.longitude, point.latitude)
        except (ValueError, IndexError):
            return 0.0
        if not (0 <= row < self._height and 0 <= col < self._width):
            return 0.0
        value = float(self._band[row, col])
        if self._nodata is not None and value == self._nodata:
            return 0.0
        # Clamp [0, 1] phòng noise số học từ build script (e.g., overlap polygon).
        if value < 0.0:
            return 0.0
        if value > 1.0:
            return 1.0
        return value
