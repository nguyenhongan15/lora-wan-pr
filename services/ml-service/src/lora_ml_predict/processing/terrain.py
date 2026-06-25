"""Terrain/Fresnel/landuse features — port of reference_wireless/src/processing/terrain.py.

Surgical port:
  - Module-level rasterio/geopandas load replaced by lazy lookup in
    `dem_lookup` (env vars LORA_REFERENCE_DEM_DIRECTORY +
    LORA_OSM_LANDUSE_DIRECTORY).
  - Hard-coded gateway/device antenna heights in add_terrain_features now
    flow from caller (per BIGBOSS: use DB values).
  - All path-features arithmetic (Fresnel, obstruction, terrain stats,
    landuse ratios) kept byte-identical to source.
"""

from collections import Counter

import numpy as np
import pandas as pd

from .dem_lookup import (
    get_elevation,
    get_roughness,
    get_slope,
    get_terrain_type,
)


def add_3d_distance(df):

    dz = df["delta_elevation"]

    df["distance_3d"] = np.sqrt(df["distance"] ** 2 + dz**2)

    # clip(lower=1.0) khớp build_training_csv.py:424 — parity train↔serving.
    df["log_distance_3d"] = np.log10(df["distance_3d"].clip(lower=1.0))

    return df


def add_fspl(df):  # free space path loss theorical

    d_km = df["distance_3d"] / 1000
    f_mhz = df["frequency"] / 1e6

    df["fspl"] = 20 * np.log10(d_km) + 20 * np.log10(f_mhz) + 32.44

    return df


def add_terrain_features(df, gw_antenna_height_m=15.0, device_antenna_height_m=1.5):
    df["elevation"] = df.apply(lambda x: get_elevation(x["lat"], x["lon"]), axis=1)

    df["gw_elevation"] = df.apply(lambda x: get_elevation(x["gw_lat"], x["gw_lon"]), axis=1)

    df = df.dropna(subset=["elevation", "gw_elevation"])

    df["delta_elevation"] = (
        df["elevation"] - df["gw_elevation"] + device_antenna_height_m - gw_antenna_height_m
    )

    df["terrain_type"] = df.apply(lambda x: get_terrain_type(x["lat"], x["lon"]), axis=1)

    df = add_3d_distance(df)
    df = add_fspl(df)

    df["elevation_angle"] = np.arctan2(df["delta_elevation"], df["distance_3d"])

    df["slope"] = df.apply(lambda x: get_slope(x["lat"], x["lon"]), axis=1)

    df["roughness"] = df.apply(lambda x: get_roughness(x["lat"], x["lon"]), axis=1)

    df["obstruction_ratio"], df["max_obstruction"] = zip(
        *df.apply(
            lambda x: get_obstruction_features(
                x["lat"],
                x["lon"],
                x["elevation"],
                x["gw_lat"],
                x["gw_lon"],
                x["gw_elevation"],
                x["distance"],
            ),
            axis=1,
        ),
        strict=True,
    )

    terrain_features = df.apply(
        lambda x: get_path_features(
            x["lat"],
            x["lon"],
            x["elevation"],
            x["gw_lat"],
            x["gw_lon"],
            x["gw_elevation"],
            x["distance"],
            x["frequency"],
            gateway_antenna_height=gw_antenna_height_m,
            device_antenna_height=device_antenna_height_m,
        ),
        axis=1,
    )
    terrain_features = pd.DataFrame(terrain_features.tolist())
    df = pd.concat([df.reset_index(drop=True), terrain_features.reset_index(drop=True)], axis=1)
    return df


def get_obstruction_features(lat1, lon1, h1, lat2, lon2, h2, distance, step_meters=30):
    n = int(distance / step_meters) + 1
    lats = np.linspace(lat1, lat2, n)
    lons = np.linspace(lon1, lon2, n)

    terrain = []
    for lat, lon in zip(lats, lons, strict=True):
        elev = get_elevation(lat, lon)
        if elev is None:
            elev = np.nan
        terrain.append(elev)

    terrain = np.array(terrain)
    if np.all(np.isnan(terrain)):
        return np.nan, np.nan

    los_line = np.linspace(h1, h2, n)
    obstruction = terrain - los_line
    obstructed = obstruction > 0
    obstruction_ratio = np.nanmean(obstructed)
    max_obstruction = np.nanmax(obstruction)

    return obstruction_ratio, max_obstruction


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

    terrain_elevations = []
    terrain_types = []
    obstruction_values = []
    fresnel_clearances = []

    for i, (lat, lon) in enumerate(zip(lats, lons, strict=True)):
        d1 = (i / (n_points - 1)) * distance
        d2 = distance - d1

        if d1 == 0 or d2 == 0:
            fresnel_radius = 0
        else:
            fresnel_radius = np.sqrt((wavelength * d1 * d2) / (d1 + d2))

        elev = get_elevation(lat, lon)

        if elev is None:
            elev = np.nan

        terrain_elevations.append(elev)

        terrain_type = get_terrain_type(lat, lon)

        if terrain_type is None:
            terrain_type = "unknown"

        terrain_types.append(terrain_type)

        los_height = h1_total + (h2_total - h1_total) * (i / (n_points - 1))

        obstruction = elev - los_height
        obstruction_values.append(obstruction)

        fresnel_clearance = los_height - fresnel_radius - elev
        fresnel_clearances.append(fresnel_clearance)

    terrain_elevations = np.array(terrain_elevations)
    obstruction_values = np.array(obstruction_values)
    fresnel_clearances = np.array(fresnel_clearances)

    terrain_mean = np.nanmean(terrain_elevations)
    terrain_std = np.nanstd(terrain_elevations)
    terrain_min = np.nanmin(terrain_elevations)
    terrain_max = np.nanmax(terrain_elevations)
    terrain_range = terrain_max - terrain_min

    obstructed = obstruction_values > 0
    obstruction_ratio = np.nanmean(obstructed)
    max_obstruction = np.nanmax(obstruction_values)
    mean_obstruction = np.nanmean(np.maximum(obstruction_values, 0))

    fresnel_blocked = fresnel_clearances < 0
    fresnel_obstruction_ratio = np.nanmean(fresnel_blocked)
    min_fresnel_clearance = np.nanmin(fresnel_clearances)
    mean_fresnel_clearance = np.nanmean(fresnel_clearances)

    counts = Counter(terrain_types)
    total = len(terrain_types)
    forest_ratio = counts["forest"] / total
    water_ratio = counts["water"] / total
    residential_ratio = counts["residential"] / total
    unknown_ratio = counts["unknown"] / total

    return {
        "terrain_mean": terrain_mean,
        "terrain_std": terrain_std,
        "terrain_min": terrain_min,
        "terrain_max": terrain_max,
        "terrain_range": terrain_range,
        "obstruction_ratio": obstruction_ratio,
        "max_obstruction": max_obstruction,
        "mean_obstruction": mean_obstruction,
        "fresnel_obstruction_ratio": fresnel_obstruction_ratio,
        "min_fresnel_clearance": min_fresnel_clearance,
        "mean_fresnel_clearance": mean_fresnel_clearance,
        "forest_ratio": forest_ratio,
        "water_ratio": water_ratio,
        "residential_ratio": residential_ratio,
        "unknown_ratio": unknown_ratio,
    }
