"""Raster feature extraction cho Stage 3+ (DEM, NDVI patches).

SKELETON. Quy trình dự kiến:
  - Lấy line từ target → gateway (great-circle).
  - Buffer 100m mỗi bên → polygon.
  - Crop DEM (SRTM v3, ~30m resolution) + NDVI (Landsat) → 64x64 patch.
  - Stack thành (channels=3, H=64, W=64) tensor.

DEM data hiện tại đã có: services/ml-service/data/dem/*.hgt (4 tile).
"""

from __future__ import annotations

__all__: list[str] = []
