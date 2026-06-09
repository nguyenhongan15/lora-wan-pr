"""Multi-tile DEM/landuse lookup helpers.

ml-service may serve regions covered by multiple DEM tiles (Đà Nẵng + Hải
Phòng + …). Reference module hard-coded `if lat > 16.71 use dem2 else dem`.
Here we scan a directory once on first use, cache `(bounds, dataset)` tuples,
and pick the right tile per (lat, lon).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import geopandas as gpd
import rasterio
from rasterio.errors import RasterioIOError
from shapely.geometry import Point

log = logging.getLogger(__name__)

DEM_ENV = "LORA_REFERENCE_DEM_DIRECTORY"
LANDUSE_ENV = "LORA_OSM_LANDUSE_DIRECTORY"

_dem_tiles: list | None = None
_landuse_gdfs: list | None = None


def _dem_dir() -> Path:
    p = os.environ.get(DEM_ENV)
    if not p:
        raise RuntimeError(f"{DEM_ENV} not set")
    return Path(p)


def _landuse_dir() -> Path:
    p = os.environ.get(LANDUSE_ENV)
    if not p:
        raise RuntimeError(f"{LANDUSE_ENV} not set")
    return Path(p)


def _load_dem_tiles() -> list:
    global _dem_tiles
    if _dem_tiles is not None:
        return _dem_tiles
    tiles = []
    for tif in sorted(_dem_dir().glob("*.tif")):
        try:
            ds = rasterio.open(tif)
        except RasterioIOError as e:
            log.warning("Skip DEM tile %s: %s", tif, e)
            continue
        # Cache cả band array trong RAM: ~100MB/tile × 3 tile = 300MB tổng.
        # Tránh đọc lại 100MB qua mỗi get_elevation() call (Fresnel path ~70
        # step → 150+ lookups/request × 100MB = 15GB read/req nếu không cache).
        band = ds.read(1)
        tiles.append((ds.bounds, ds, band, tif.name))
        log.info("DEM tile loaded: %s bounds=%s band_shape=%s", tif.name, ds.bounds, band.shape)
    if not tiles:
        raise RuntimeError(f"No .tif tiles found under {_dem_dir()}")
    _dem_tiles = tiles
    return tiles


def _load_landuse() -> list:
    global _landuse_gdfs
    if _landuse_gdfs is not None:
        return _landuse_gdfs
    gdfs = []
    for gj in sorted(_landuse_dir().glob("*.geojson")):
        gdf = gpd.read_file(gj)
        gdfs.append((gdf.total_bounds, gdf, gj.name))
        log.info("Landuse loaded: %s n=%d", gj.name, len(gdf))
    if not gdfs:
        raise RuntimeError(f"No .geojson files found under {_landuse_dir()}")
    _landuse_gdfs = gdfs
    return gdfs


def _pick_dem(lat: float, lon: float):
    for bounds, ds, band, _name in _load_dem_tiles():
        if bounds.left <= lon <= bounds.right and bounds.bottom <= lat <= bounds.top:
            return ds, band
    return None, None


def _pick_landuse(lat: float, lon: float):
    for bounds, gdf, _name in _load_landuse():
        west, south, east, north = bounds
        if west <= lon <= east and south <= lat <= north:
            return gdf
    return None


def get_elevation(lat: float, lon: float) -> float | None:
    if lat is None or lon is None:
        return None
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return None
    ds, band = _pick_dem(lat, lon)
    if ds is None:
        return None
    try:
        row, col = ds.index(lon, lat)
        value = band[row, col]
        if value == ds.nodata:
            return None
        return float(value)
    except Exception:
        return None


def get_terrain_type(lat: float, lon: float) -> str:
    gdf = _pick_landuse(lat, lon)
    if gdf is None:
        return "unknown"
    point = Point(lon, lat)
    # sindex (R-tree) prunes 3084 polygons → vài candidate trước khi
    # contains() chính xác. Per-request từ O(N) xuống O(log N + k).
    candidate_idx = gdf.sindex.query(point, predicate="contains")
    if len(candidate_idx) == 0:
        return "unknown"
    row = gdf.iloc[candidate_idx[0]]
    import pandas as pd  # local to avoid hard dep at import time

    if "landuse" in row and row["landuse"] is not None and pd.notna(row["landuse"]):
        return str(row["landuse"])
    if "natural" in row and row["natural"] is not None and pd.notna(row["natural"]):
        return str(row["natural"])
    return "unknown"


def get_slope(lat: float, lon: float) -> float | None:
    import numpy as np

    ds, band = _pick_dem(lat, lon)
    if ds is None:
        return None
    try:
        row, col = ds.index(lon, lat)
        window = band[row - 1 : row + 2, col - 1 : col + 2]
        gy, gx = np.gradient(window)
        slope = np.sqrt(gx**2 + gy**2)
        return float(np.mean(slope))
    except Exception:
        return None


def get_roughness(lat: float, lon: float) -> float | None:
    import numpy as np

    ds, band = _pick_dem(lat, lon)
    if ds is None:
        return None
    try:
        row, col = ds.index(lon, lat)
        window = band[row - 2 : row + 3, col - 2 : col + 3]
        return float(np.std(window))
    except Exception:
        return None
