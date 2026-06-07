import pandas as pd
from scipy.spatial import cKDTree

REFERENCE = pd.read_csv(
    "data/reference_points.csv"
)

TREES = {}

for gw in REFERENCE.gateway.unique():
    subset = REFERENCE[
        REFERENCE.gateway == gw
    ]

    TREES[gw] = (
        subset,
        cKDTree(
            subset[["lat", "lon"]]
        )
    )
def compute_neighbor_features(
    lat,
    lon,
    gateway
):
    """Compute features based on the k nearest neighbors.

    Args:
        lat: Latitude of the location.
        lon: Longitude of the location.
        gateway: The gateway to use for the prediction.

    Returns:
        A dictionary of features based on the k nearest neighbors.
    """