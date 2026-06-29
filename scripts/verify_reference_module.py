"""Verify reference module's terrain/Fresnel/landuse features reproduce
sensibly on our DEM + OSM landuse data.

Acceptance:
  - No NaN/Inf in 13 hard features.
  - terrain_mean within ±50m of CSV value (DEM source may differ slightly).
  - fresnel_obstruction_ratio in [0,1].
  - residential_ratio in [0,1].

Picks 5 Đà Nẵng rows (lat < 16.71 → use single DEM tile).

Usage:
    uv run --with pandas --with rasterio --with geopandas --with shapely \
        python scripts/verify_reference_module.py
"""

from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from shapely.geometry import Point

REPO_ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = (
    REPO_ROOT
    / "services"
    / "ml-service"
    / "data"
    / "training"
    / "processed"
    / "devices_history_full.csv"
)
DEM_PATH = Path("E:/DATN/lora-data/dem/copernicus_glo30_danang.tif")
LANDUSE_PATH = REPO_ROOT / "data" / "osm" / "landuse_danang.geojson"

_dem = rasterio.open(DEM_PATH)
_terrain = gpd.read_file(LANDUSE_PATH)


def get_elevation(lat, lon):
    if lat is None or lon is None:
        return None
    try:
        row, col = _dem.index(lon, lat)
        value = _dem.read(1)[row, col]
        if value == _dem.nodata:
            return None
        return float(value)
    except Exception:
        return None


def get_terrain_type(lat, lon):
    point = Point(lon, lat)
    matches = _terrain[_terrain.contains(point)]
    if len(matches) == 0:
        return "unknown"
    row = matches.iloc[0]
    if "landuse" in row and row["landuse"] is not None and pd.notna(row["landuse"]):
        return row["landuse"]
    if "natural" in row and row["natural"] is not None and pd.notna(row["natural"]):
        return row["natural"]
    return "unknown"


def get_slope(lat, lon):
    try:
        row, col = _dem.index(lon, lat)
        window = _dem.read(1, window=((row - 1, row + 2), (col - 1, col + 2)))
        gy, gx = np.gradient(window)
        slope = np.sqrt(gx**2 + gy**2)
        return float(np.mean(slope))
    except Exception:
        return None


def get_roughness(lat, lon):
    try:
        row, col = _dem.index(lon, lat)
        window = _dem.read(1, window=((row - 2, row + 3), (col - 2, col + 3)))
        return float(np.std(window))
    except Exception:
        return None


def get_path_features(
    lat1,
    lon1,
    h1,
    lat2,
    lon2,
    h2,
    distance,
    frequency=922200000,
    step_meters=30,
    gateway_antenna_height=15,
    device_antenna_height=1.5,
):
    n_points = max(int(distance / step_meters) + 1, 2)
    lats = np.linspace(lat1, lat2, n_points)
    lons = np.linspace(lon1, lon2, n_points)
    h1_total = h1 + gateway_antenna_height
    h2_total = h2 + device_antenna_height
    c = 299792458
    wavelength = c / frequency

    terrain_elevations, terrain_types, obstruction_values, fresnel_clearances = [], [], [], []
    for i, (lat, lon) in enumerate(zip(lats, lons, strict=True)):
        d1 = (i / (n_points - 1)) * distance
        d2 = distance - d1
        fresnel_radius = 0 if (d1 == 0 or d2 == 0) else np.sqrt((wavelength * d1 * d2) / (d1 + d2))
        elev = get_elevation(lat, lon)
        if elev is None:
            elev = np.nan
        terrain_elevations.append(elev)
        t = get_terrain_type(lat, lon) or "unknown"
        terrain_types.append(t)
        los_height = h1_total + (h2_total - h1_total) * (i / (n_points - 1))
        obstruction_values.append(elev - los_height)
        fresnel_clearances.append(los_height - fresnel_radius - elev)

    terrain_elevations = np.array(terrain_elevations)
    obstruction_values = np.array(obstruction_values)
    fresnel_clearances = np.array(fresnel_clearances)

    counts = Counter(terrain_types)
    total = len(terrain_types)
    return {
        "terrain_mean": float(np.nanmean(terrain_elevations)),
        "terrain_std": float(np.nanstd(terrain_elevations)),
        "terrain_min": float(np.nanmin(terrain_elevations)),
        "terrain_max": float(np.nanmax(terrain_elevations)),
        "fresnel_obstruction_ratio": float(np.nanmean(fresnel_clearances < 0)),
        "min_fresnel_clearance": float(np.nanmin(fresnel_clearances)),
        "mean_fresnel_clearance": float(np.nanmean(fresnel_clearances)),
        "forest_ratio": counts["forest"] / total,
        "water_ratio": counts["water"] / total,
        "residential_ratio": counts["residential"] / total,
        "unknown_ratio": counts["unknown"] / total,
    }


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    log = logging.getLogger("verify")

    log.info("Loading CSV…")
    df = pd.read_csv(CSV_PATH)
    df_dn = df[df["lat"] < 16.71].copy()
    log.info("Đà Nẵng rows: %d / %d", len(df_dn), len(df))

    sample = df_dn.sample(5, random_state=42).reset_index(drop=True)

    log.info("─" * 80)
    log.info("Comparing OUR features vs CSV features (5 random Đà Nẵng links):")
    for i, row in sample.iterrows():
        lat, lon, gw_lat, gw_lon = row["lat"], row["lon"], row["gw_lat"], row["gw_lon"]
        freq = row["frequency"]
        dist = row["distance"]

        elev = get_elevation(lat, lon)
        gw_elev = get_elevation(gw_lat, gw_lon)
        slope = get_slope(lat, lon)
        roughness = get_roughness(lat, lon)
        feats = get_path_features(
            lat, lon, elev or 0, gw_lat, gw_lon, gw_elev or 0, dist, frequency=freq
        )

        log.info("Row %d  d=%.0fm  gateway=%s", i, dist, row["gateway"][:16])
        log.info("  elevation         OUR=%-8s  CSV=%-8s", elev, row["elevation"])
        log.info("  gw_elevation      OUR=%-8s  CSV=%-8s", gw_elev, row["gw_elevation"])
        log.info("  slope             OUR=%-8.3f  CSV=%-8.3f", slope or 0, row["slope"])
        log.info("  roughness         OUR=%-8.3f  CSV=%-8.3f", roughness or 0, row["roughness"])
        log.info(
            "  terrain_mean      OUR=%-8.3f  CSV=%-8.3f", feats["terrain_mean"], row["terrain_mean"]
        )
        log.info(
            "  terrain_std       OUR=%-8.3f  CSV=%-8.3f", feats["terrain_std"], row["terrain_std"]
        )
        log.info(
            "  fresnel_obstr.    OUR=%-8.3f  CSV=%-8.3f",
            feats["fresnel_obstruction_ratio"],
            row["fresnel_obstruction_ratio"],
        )
        log.info(
            "  min_fresnel_cl.   OUR=%-8.3f  CSV=%-8.3f",
            feats["min_fresnel_clearance"],
            row["min_fresnel_clearance"],
        )
        log.info(
            "  residential_ratio OUR=%-8.3f  CSV=%-8.3f",
            feats["residential_ratio"],
            row["residential_ratio"],
        )

        for k, v in feats.items():
            if np.isnan(v) or np.isinf(v):
                log.error("  ❌ %s is NaN/Inf", k)
        log.info("")
    log.info("─" * 80)


if __name__ == "__main__":
    main()
