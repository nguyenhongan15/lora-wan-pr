"""Serve-time wrapper around reference processing module.

Builds a 1-row DataFrame, runs `add_basic_features` + `add_terrain_features`
identically to training time, returns a dict with the 20 numeric features +
`gateway` categorical that ExtraTreesRegressor was trained on.
"""

from __future__ import annotations

import pandas as pd

from .features import add_basic_features
from .terrain import add_terrain_features

FEATURE_KEYS = [
    "frequency",
    "spreading_factor",
    "log_distance",
    "log_distance_3d",
    "delta_lat",
    "delta_lon",
    "angle",
    "gw_elevation",
    "delta_elevation",
    "elevation_angle",
    "slope",
    "roughness",
    "terrain_mean",
    "terrain_std",
    "terrain_min",
    "terrain_max",
    "fresnel_obstruction_ratio",
    "min_fresnel_clearance",
    "mean_fresnel_clearance",
    "residential_ratio",
    "gateway",
]


def compute_link_features(
    lat: float,
    lon: float,
    gw_lat: float,
    gw_lon: float,
    gw_ant_h_m: float,
    freq_hz: float,
    sf: int,
    gateway_code: str,
    device_ant_h_m: float = 1.5,
) -> dict | None:
    """Compute the 20 ET features for one (device, gateway) link.

    Returns None when DEM lookup fails for either endpoint (caller should
    fall back to mean / skip the prediction).
    """
    row = {
        "lat": lat,
        "lon": lon,
        "gw_lat": gw_lat,
        "gw_lon": gw_lon,
        "frequency": freq_hz,
        "spreading_factor": float(sf),
        "gateway": gateway_code,
    }
    df = pd.DataFrame([row])
    df = add_basic_features(df)
    df = add_terrain_features(
        df,
        gw_antenna_height_m=gw_ant_h_m,
        device_antenna_height_m=device_ant_h_m,
    )
    if df.empty:
        return None
    out = {k: df.iloc[0][k] for k in FEATURE_KEYS}
    return out
