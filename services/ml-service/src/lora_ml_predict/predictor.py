"""predictor.py — Inference module for the trained Extra Trees RSSI model.

Usage:
    from lora_ml_predict.predictor import pred

    rssi = pred(16.06, 108.22)      # → -118.37 dBm (example)
    rssi = pred(21.0, 106.5)        # → -96.15 dBm  (example)

The model is an ExtraTreesRegressor (training RMSE ≈ 1.88 dBm) trained on
LoRaWAN survey data from Da Nang and Hai Phong, Vietnam (AS923-2 band).

Coordinates must be within Vietnam boundaries (lat: [8.4, 23.4], lon: [102.1, 109.5]).
The module is self-contained: the trained pipeline, gateway lookup table, and
terrain feature fallbacks are bundled at load time.
"""

from __future__ import annotations

import math
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Paths — resolve relative to this file
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent  # .../lora_ml_predict/
_PROJECT_ROOT = _HERE.parents[3]          # .../lora-wan-pr/
_MODEL_DIR = _PROJECT_ROOT / "services" / "ml-service" / "data"

# trained pipeline: sklearn Pipeline(ColumnTransformer + ExtraTreesRegressor)
_MODEL_PATH = _MODEL_DIR / "extra_trees_model.joblib"

# fallback mean values for terrain / fresnel / land-use features
_FALLBACK_PATH = _MODEL_DIR / "terrain_fallback.json"

# ---------------------------------------------------------------------------
# Gateway lookup table — used to find the nearest gateway for a given (lat, lon)
# Source: seed_gateways.sql (DNIIT deployment), extended with data from
#         devices_history_full.csv.
# ---------------------------------------------------------------------------
_GATEWAYS: list[dict] = [
    {"id": "ac1f09fffe06fcf2", "lat": 16.054766, "lon": 108.219856, "elevation": 9.0,  "freq": 922200000},
    {"id": "7276ff002e06029f", "lat": 16.074104, "lon": 108.152435, "elevation": 14.0, "freq": 922200000},
    {"id": "7276ff002e0507da", "lat": 16.074198, "lon": 108.152626, "elevation": 14.0, "freq": 922200000},
    {"id": "a84041ffff1ec39f", "lat": 16.091300, "lon": 108.217456, "elevation": 0.0,  "freq": 922200000},
    {"id": "ac1f09fffe00ab25", "lat": 16.110730, "lon": 108.128570, "elevation": 12.0, "freq": 922200000},
    {"id": "ac1f09fffe0fd63b", "lat": 15.985690, "lon": 108.239860, "elevation": 15.0, "freq": 922200000},
    {"id": "7276ff002e062cf2", "lat": 16.118301, "lon": 108.273682, "elevation": 584.0, "freq": 922200000},
    {"id": "7276ff002e061f5b", "lat": 16.075603, "lon": 108.222076, "elevation": 9.0,   "freq": 922200000},
    {"id": "a840411eebb44150", "lat": 16.074098, "lon": 108.152530, "elevation": 14.0, "freq": 922200000},
    {"id": "ac1f09fffe0fd629", "lat": 16.068190, "lon": 108.154510, "elevation": 7.0,  "freq": 922200000},
    {"id": "ac1f09fffe00ab20", "lat": 16.054840, "lon": 108.219940, "elevation": 8.0,  "freq": 922200000},
    {"id": "24e124fffef4778e", "lat": 20.654590, "lon": 106.063140, "elevation": 8.0,  "freq": 921400000},
    {"id": "7076ff0054070418", "lat": 20.654448, "lon": 106.063171, "elevation": 7.0,  "freq": 921400000},
]

# ---------------------------------------------------------------------------
# Feature column order (must match training exactly)
# ---------------------------------------------------------------------------
_NUMERIC_FEATURES = [
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
]

_CATEGORICAL_FEATURES = ["gateway"]

_ALL_FEATURES = _NUMERIC_FEATURES + _CATEGORICAL_FEATURES

# ---------------------------------------------------------------------------
# Coordinate bounds (Vietnam, AS923-2)
# ---------------------------------------------------------------------------
_MIN_LAT, _MAX_LAT = 8.4, 23.4
_MIN_LON, _MAX_LON = 102.1, 109.5

# ---------------------------------------------------------------------------
# Lazy-loaded model & fallback cache
# ---------------------------------------------------------------------------
_model: object | None = None
_fallback: dict[str, float] | None = None


def _load_model():
    """Load the trained Extra Trees pipeline (cached after first call)."""
    global _model
    if _model is not None:
        return _model
    if not _MODEL_PATH.exists():
        raise FileNotFoundError(
            f"Trained model not found at {_MODEL_PATH}. "
            "Run `python scripts/train_extra_trees.py` first."
        )
    _model = joblib.load(_MODEL_PATH)
    return _model


def _load_fallback() -> dict[str, float]:
    """Load terrain fallback mean values (cached after first call)."""
    global _fallback
    if _fallback is not None:
        return _fallback
    import json
    if not _FALLBACK_PATH.exists():
        raise FileNotFoundError(
            f"Fallback values not found at {_FALLBACK_PATH}. "
            "Run `python scripts/train_extra_trees.py` first."
        )
    with open(_FALLBACK_PATH) as f:
        _fallback = json.load(f)
    return _fallback


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km (Haversine formula)."""
    R = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(min(a, 1.0)))


def _find_nearest_gateway(lat: float, lon: float) -> dict:
    """Return the closest gateway (by great-circle distance)."""
    best = min(
        _GATEWAYS,
        key=lambda gw: _haversine_km(lat, lon, gw["lat"], gw["lon"]),
    )
    return best


def _validate_coords(lat: float, lon: float) -> None:
    """Raise ValueError if coordinates are outside Vietnam bounds."""
    if not isinstance(lat, (int, float)):
        raise TypeError(f"lat must be a number, got {type(lat).__name__}")
    if not isinstance(lon, (int, float)):
        raise TypeError(f"lon must be a number, got {type(lon).__name__}")
    if not (_MIN_LAT <= lat <= _MAX_LAT):
        raise ValueError(f"lat {lat} is outside Vietnam bounds [{_MIN_LAT}, {_MAX_LAT}]")
    if not (_MIN_LON <= lon <= _MAX_LON):
        raise ValueError(f"lon {lon} is outside Vietnam bounds [{_MIN_LON}, {_MAX_LON}]")


def _build_features(lat: float, lon: float, gw: dict, sf: int = 12) -> pd.DataFrame:
    """Build a 1-row DataFrame with all features expected by the pipeline.

    Parameters
    ----------
    lat, lon : float
        Target (device) coordinates.
    gw : dict
        Nearest gateway record (keys: id, lat, lon, elevation, freq).
    sf : int
        Spreading factor (default 12 — most common in dataset).

    Returns
    -------
    pd.DataFrame with column order matching _ALL_FEATURES.
    """
    fb = _load_fallback()

    # --- Features computable from (lat, lon, gateway) alone ---
    dist_km = _haversine_km(lat, lon, gw["lat"], gw["lon"])
    log_dist = math.log10(max(dist_km * 1000, 1.0))  # log10(distance in meters), min 1m
    delta_lat = lat - gw["lat"]
    delta_lon = lon - gw["lon"]
    angle = math.atan2(delta_lat, delta_lon)

    row: dict[str, float | str] = {
        # --- Computable from (lat, lon, gateway) ---
        "frequency": float(gw["freq"]),
        "spreading_factor": float(sf),
        "log_distance": log_dist,
        "delta_lat": delta_lat,
        "delta_lon": delta_lon,
        "angle": angle,
        "gw_elevation": gw["elevation"],
        # --- Terrain / fresnel / land-use: use dataset mean fallback ---
        # These require DEM data (device elevation, path profile) which
        # is not available at inference time without external infrastructure.
        "log_distance_3d": fb["log_distance_3d"],
        "delta_elevation": fb["delta_elevation"],
        "elevation_angle": fb["elevation_angle"],
        "slope": fb["slope"],
        "roughness": fb["roughness"],
        "terrain_mean": fb["terrain_mean"],
        "terrain_std": fb["terrain_std"],
        "terrain_min": fb["terrain_min"],
        "terrain_max": fb["terrain_max"],
        "fresnel_obstruction_ratio": fb["fresnel_obstruction_ratio"],
        "min_fresnel_clearance": fb["min_fresnel_clearance"],
        "mean_fresnel_clearance": fb["mean_fresnel_clearance"],
        "residential_ratio": fb["residential_ratio"],
        # Categorical
        "gateway": gw["id"],
    }
    return pd.DataFrame([row])[_ALL_FEATURES]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def pred(lat: float, lon: float, spreading_factor: int = 12) -> float:
    """Predict RSSI (dBm) at a given (latitude, longitude).

    Internally finds the nearest DNIIT gateway, computes all required features
    (distance, geometry, terrain fallbacks), and runs the trained Extra Trees
    pipeline (training RMSE ~1.88 dBm).

    .. note::

       Terrain, Fresnel, and land-use features use dataset-wide mean fallbacks
       because device elevation and path profile data (DEM) are not available
       at inference time without external infrastructure. Predictions are most
       reliable when the device location is in the same region (Da Nang / Hai
       Phong) as the training data.

    Parameters
    ----------
    lat : float
        Latitude in degrees (WGS84).
    lon : float
        Longitude in degrees (WGS84).
    spreading_factor : int, optional
        Spreading factor (7-12). Default 12.

    Returns
    -------
    float
        Predicted RSSI in dBm.

    Raises
    ------
    TypeError
        If coordinates are not numeric.
    ValueError
        If coordinates are outside Vietnam bounds (lat: 8.4–23.4, lon: 102.1–109.5)
        or if spreading_factor is not in 7–12 range.
    FileNotFoundError
        If the trained model artifact is missing.
    """
    _validate_coords(lat, lon)

    if not isinstance(spreading_factor, int) or not (7 <= spreading_factor <= 12):
        raise ValueError(f"spreading_factor must be int in [7, 12], got {spreading_factor!r}")

    model = _load_model()
    gw = _find_nearest_gateway(lat, lon)
    features = _build_features(lat, lon, gw, sf=spreading_factor)

    try:
        rssi = float(model.predict(features)[0])
        return rssi
    except Exception as e:
        raise RuntimeError(f"Inference failed: {e}") from e


def pred_with_gateway(lat: float, lon: float, gateway_id: str, spreading_factor: int = 12) -> float:
    """Predict RSSI (dBm) using a specific gateway instead of auto-selecting.

    Parameters
    ----------
    lat, lon : float
        Target coordinates.
    gateway_id : str
        Gateway identifier (e.g. ``"ac1f09fffe06fcf2"``).
    spreading_factor : int, optional
        Spreading factor (7-12). Default 12.

    Returns
    -------
    float
        Predicted RSSI in dBm.
    """
    _validate_coords(lat, lon)
    if not isinstance(spreading_factor, int) or not (7 <= spreading_factor <= 12):
        raise ValueError(f"spreading_factor must be int in [7, 12], got {spreading_factor!r}")

    gw = next((g for g in _GATEWAYS if g["id"] == gateway_id), None)
    if gw is None:
        raise ValueError(f"Unknown gateway id: {gateway_id!r}")

    model = _load_model()
    features = _build_features(lat, lon, gw, sf=spreading_factor)
    try:
        return float(model.predict(features)[0])
    except Exception as e:
        raise RuntimeError(f"Inference failed: {e}") from e


def list_gateways() -> list[dict]:
    """Return the list of known gateways (id, lat, lon, elevation, freq)."""
    return list(_GATEWAYS)
