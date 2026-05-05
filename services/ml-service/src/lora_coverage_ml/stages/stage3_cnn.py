"""Stage 3 — ResNet-18 trên DEM + NDVI raster patch quanh đường truyền.

SKELETON. Khi build:
  - Input: 64x64 raster patch (DEM, NDVI, building footprint) dọc line-of-sight
    từ target → gateway.
  - Output: path-loss prediction trực tiếp (không qua Stage 1).
  - Confidence: deep ensemble (5 model) → variance.
  - Train: ≥ 50K survey điểm + DEM SRTM v3 + Landsat NDVI.
  - GPU khuyến nghị (CPU inference cũng OK với ONNX).
"""

from __future__ import annotations

# class Stage3CNNModel:
#     model_version: str
#     def __init__(self, onnx_path: str, dem_provider, ndvi_provider): ...
#     def predict(self, target, gateway): ...

__all__: list[str] = []
