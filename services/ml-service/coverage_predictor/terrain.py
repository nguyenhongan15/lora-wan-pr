import os

import numpy as np
import rasterio
import geopandas as gpd

from shapely.geometry import Point
from collections import Counter

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

DATA_DIR = os.path.join(
    BASE_DIR,
    "data",
    "terrain",
)

dem = rasterio.open(
    os.path.join(
        DATA_DIR,
        "dem.tif"
    )
)

dem2 = rasterio.open(
    os.path.join(
        DATA_DIR,
        "dem2.tif"
    )
)

terrain = gpd.read_file(
    os.path.join(
        DATA_DIR,
        "landuse.geojson"
    )
)

terrain2 = gpd.read_file(
    os.path.join(
        DATA_DIR,
        "landuse2.geojson"
    )
)


def _use_dem2(lat):
    return lat > 16.71


def get_elevation(lat, lon):

    if lat is None or lon is None:
        return None

    if not (-90 <= lat <= 90):
        return None

    if not (-180 <= lon <= 180):
        return None

    try:

        dataset = dem2 if _use_dem2(lat) else dem

        row, col = dataset.index(
            lon,
            lat
        )

        value = dataset.read(
            1
        )[row, col]

        if value == dataset.nodata:
            return None

        return float(value)

    except:
        return None


def get_terrain_type(lat, lon):

    point = Point(
        lon,
        lat
    )

    dataset = (
        terrain2
        if _use_dem2(lat)
        else terrain
    )

    matches = dataset[
        dataset.contains(point)
    ]

    if len(matches) == 0:
        return "unknown"

    row = matches.iloc[0]

    if (
        "landuse" in row
        and
        row["landuse"] is not None
    ):
        return row["landuse"]

    if (
        "natural" in row
        and
        row["natural"] is not None
    ):
        return row["natural"]

    return "unknown"


def get_slope(lat, lon):

    try:

        dataset = (
            dem2
            if _use_dem2(lat)
            else dem
        )

        row, col = dataset.index(
            lon,
            lat
        )

        window = dataset.read(
            1,
            window=(
                (row - 1, row + 2),
                (col - 1, col + 2)
            )
        )

        gy, gx = np.gradient(
            window
        )

        slope = np.sqrt(
            gx ** 2
            +
            gy ** 2
        )

        return float(
            np.mean(
                slope
            )
        )

    except:
        return None


def get_roughness(lat, lon):

    try:

        dataset = (
            dem2
            if _use_dem2(lat)
            else dem
        )

        row, col = dataset.index(
            lon,
            lat
        )

        window = dataset.read(
            1,
            window=(
                (row - 2, row + 3),
                (col - 2, col + 3)
            )
        )

        return float(
            np.std(
                window
            )
        )

    except:
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

    n_points = max(
        int(
            distance
            /
            step_meters
        ) + 1,
        2
    )

    lats = np.linspace(
        lat1,
        lat2,
        n_points
    )

    lons = np.linspace(
        lon1,
        lon2,
        n_points
    )

    h1_total = (
        h1
        +
        gateway_antenna_height
    )

    h2_total = (
        h2
        +
        device_antenna_height
    )

    c = 299792458

    wavelength = (
        c
        /
        frequency
    )

    terrain_elevations = []
    terrain_types = []

    obstruction_values = []
    fresnel_clearances = []

    for i, (lat, lon) in enumerate(
        zip(
            lats,
            lons
        )
    ):

        d1 = (
            i
            /
            (n_points - 1)
        ) * distance

        d2 = (
            distance
            -
            d1
        )

        if (
            d1 == 0
            or
            d2 == 0
        ):
            fresnel_radius = 0

        else:

            fresnel_radius = np.sqrt(
                (
                    wavelength
                    *
                    d1
                    *
                    d2
                )
                /
                (
                    d1
                    +
                    d2
                )
            )

        elev = get_elevation(
            lat,
            lon
        )

        if elev is None:
            continue

        terrain_elevations.append(
            elev
        )

        terrain_types.append(
            get_terrain_type(
                lat,
                lon
            )
        )

        los_height = (
            h1_total
            +
            (
                h2_total
                -
                h1_total
            )
            *
            (
                i
                /
                (
                    n_points
                    -
                    1
                )
            )
        )

        obstruction_values.append(
            elev
            -
            los_height
        )

        fresnel_clearances.append(
            los_height
            -
            fresnel_radius
            -
            elev
        )

    if len(
        terrain_elevations
    ) == 0:

        return {
            "terrain_mean": np.nan,
            "terrain_std": np.nan,
            "terrain_min": np.nan,
            "terrain_max": np.nan,
            "terrain_range": np.nan,
            "max_obstruction": np.nan,
            "fresnel_obstruction_ratio": np.nan,
            "min_fresnel_clearance": np.nan,
            "mean_fresnel_clearance": np.nan,
            "residential_ratio": np.nan,
        }

    terrain_elevations = np.array(
        terrain_elevations
    )

    obstruction_values = np.array(
        obstruction_values
    )

    fresnel_clearances = np.array(
        fresnel_clearances
    )

    terrain_mean = np.nanmean(
        terrain_elevations
    )

    terrain_std = np.nanstd(
        terrain_elevations
    )

    terrain_min = np.nanmin(
        terrain_elevations
    )

    terrain_max = np.nanmax(
        terrain_elevations
    )

    terrain_range = (
        terrain_max
        -
        terrain_min
    )

    max_obstruction = np.nanmax(
        obstruction_values
    )

    fresnel_obstruction_ratio = np.nanmean(
        fresnel_clearances
        <
        0
    )

    min_fresnel_clearance = np.nanmin(
        fresnel_clearances
    )

    mean_fresnel_clearance = np.nanmean(
        fresnel_clearances
    )

    counts = Counter(
        terrain_types
    )

    residential_ratio = (
        counts["residential"]
        /
        len(
            terrain_types
        )
    )

    return {

        "terrain_mean":
            terrain_mean,

        "terrain_std":
            terrain_std,

        "terrain_min":
            terrain_min,

        "terrain_max":
            terrain_max,

        "terrain_range":
            terrain_range,

        "max_obstruction":
            max_obstruction,

        "fresnel_obstruction_ratio":
            fresnel_obstruction_ratio,

        "min_fresnel_clearance":
            min_fresnel_clearance,

        "mean_fresnel_clearance":
            mean_fresnel_clearance,

        "residential_ratio":
            residential_ratio,
    }
