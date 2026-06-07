import numpy as np
import pandas as pd

from scipy.spatial import cKDTree


REFERENCE = pd.read_csv(
    "coverage_predictor/data/reference_points.csv"
)

LAT_TO_M = 111000.0
LON_TO_M = (
    111000.0
    *
    np.cos(
        np.radians(
            REFERENCE["lat"].mean()
        )
    )
)

MIN_DISTANCE = 0.1
K = 9
K_SEARCH = 11
GW_DISTANCE_WEIGHT = 1.1


TREES = {}

for gw in REFERENCE["gateway"].unique():

    subset = (
        REFERENCE[
            REFERENCE["gateway"] == gw
        ]
        .reset_index(drop=True)
    )

    coords = np.column_stack([
        subset["lat"].values * LAT_TO_M,
        subset["lon"].values * LON_TO_M,
    ])

    TREES[gw] = {
        "tree": cKDTree(coords),
        "coords": coords,
        "rssi": subset["rssi"].values,
        "gw_dist": subset["distance"].values,
    }


def compute_neighbor_features(
    lat,
    lon,
    gateway,
    gateway_distance
):
    """Compute features based on the k nearest neighbors.

    Args:
        lat: Latitude of the location.
        lon: Longitude of the location.
        gateway: The gateway to use for the prediction.
        gateway_distance: The distance from the location to the gateway.

    Returns:
        A dictionary of features based on the k nearest neighbors.
    """

    data = TREES[gateway]

    point = np.array([
        lat * LAT_TO_M,
        lon * LON_TO_M
    ])

    dist_all, idx_all = data["tree"].query(
        point,
        k=min(
            K_SEARCH,
            len(data["rssi"])
        )
    )

    dist_all = np.atleast_1d(dist_all)
    idx_all = np.atleast_1d(idx_all)

    keep = []

    for d, idx in zip(
        dist_all,
        idx_all
    ):

        if d <= MIN_DISTANCE:
            continue

        keep.append(
            (d, idx)
        )

    if len(keep) == 0:

        return {
            "rssi_closest_point": np.nan,
            "distance_closest_point": np.nan,
            "closest_to_gw_distance": np.nan,
            "neighbor_rssi_mean": np.nan,
            "neighbor_rssi_weighted_mean": np.nan,
            "neighbor_rssi_std": np.nan,
            "neighbor_distance_mean": np.nan,
            "neighbor_gw_distance_mean": np.nan,
        }

    dist_keep = np.array([
        x[0]
        for x in keep
    ])

    idx_keep = np.array([
        x[1]
        for x in keep
    ])

    score = (
        dist_keep
        +
        GW_DISTANCE_WEIGHT
        *
        np.abs(
            data["gw_dist"][
                idx_keep
            ]
            -
            gateway_distance
        )
    )

    order = np.argsort(
        score
    )[:K]

    idx = idx_keep[order]
    dist = dist_keep[order]

    rssi = data["rssi"][idx]
    gw_dist = data["gw_dist"][idx]

    w = np.exp(
        -dist / 30
    )

    return {

        "rssi_closest_point":
            rssi[0],

        "distance_closest_point":
            dist[0],

        "closest_to_gw_distance":
            gw_dist[0],

        "neighbor_rssi_mean":
            np.mean(rssi),

        "neighbor_rssi_weighted_mean":
            np.sum(
                rssi * w
            )
            /
            np.sum(w),

        "neighbor_rssi_std":
            np.std(rssi),

        "neighbor_distance_mean":
            np.mean(dist),

        "neighbor_gw_distance_mean":
            np.mean(gw_dist),
    }