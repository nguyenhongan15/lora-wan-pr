"""Basic geometry features — port of reference_wireless/src/processing/features.py.

Surgical port: identical logic, only changes are stylistic (no module-level
state). Kept the same docstrings/comments where present.
"""

import numpy as np


def haversine(
    lat1, lon1, lat2, lon2
):  # maybe change for caclulating 3D distance with elevation bc pythagore=/=arcs so approximation
    R = 6371000  # mètres

    phi1 = np.radians(lat1)
    phi2 = np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlambda = np.radians(lon2 - lon1)

    a = np.sin(dphi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda / 2) ** 2
    c = 2 * np.arcsin(np.sqrt(a))

    return R * c


def add_basic_features(df):
    df["distance"] = haversine(df["lat"], df["lon"], df["gw_lat"], df["gw_lon"])

    # clip(lower=1.0) khớp build_training_csv.py — tránh log10(0)/âm khi device
    # ~trùng vị trí gateway (distance < 1 m). Parity train↔serving.
    df["log_distance"] = np.log10(df["distance"].clip(lower=1.0))

    df = add_geometry_features(df)

    df["gateway_id"] = df["gateway"].astype("category").cat.codes

    return df


def add_geometry_features(df):
    df["delta_lat"] = df["lat"] - df["gw_lat"]
    df["delta_lon"] = df["lon"] - df["gw_lon"]
    df["angle"] = np.arctan2(df["delta_lat"], df["delta_lon"])
    return df
