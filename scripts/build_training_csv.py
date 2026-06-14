"""Regenerate training CSV cho ml-service từ DB ts.survey_training.

Replace bước manual của reference_wireless/main.py (fetch_data + parse + clean).
Đầu vào: rows community-flagged trong ts.survey_training + geo.gateways.
Đầu ra: services/ml-service/reference_wireless/data/processed/devices_history_full.csv
        (cùng schema cũ để train_extra_trees.py đọc không đổi).

Pipeline (port từ reference_wireless/processing/{features,terrain}.py — KHÔNG
import trực tiếp vì module-level mở DEM với path tương đối + bbox cũ chỉ
Đà Nẵng nội thành):
  1. Query DB → DataFrame raw (lat/lon/gw_lat/gw_lon/rssi/snr/frequency/SF/...).
  2. add_basic_features: distance, log_distance, delta_lat/lon, angle, gateway_id.
  3. add_terrain_features: elevation/gw_elevation/delta_elevation/distance_3d/
     fspl/elevation_angle/slope/roughness + path features (terrain_mean/std/
     min/max/range, obstruction_*, fresnel_*, forest/water/residential/
     unknown_ratio).
  4. Write CSV (overwrite).

Optimization: DEM được preload thành numpy array (1 lần read) thay vì
reference_wireless gọi `dem.read(1)[row,col]` mỗi lookup → 10-100x faster.

Run trong Celery task retrain (subprocess), hoặc thủ công:
    docker compose exec celery-worker python /app/scripts/build_training_csv.py

Est. time: 5-30 phút cho 10000 rows (terrain sampling dọc path 30m/step).
"""

from __future__ import annotations

import logging
import os
import sys
import time
from collections import Counter
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from shapely.geometry import Point
from sqlalchemy import create_engine, text

log = logging.getLogger("build_training_csv")

# --- Paths ---
DEM_CENTRAL = Path(os.environ.get("LORA_DEM_CENTRAL", "/data/dem/copernicus_glo30_danang.tif"))
DEM_NORTH = Path(os.environ.get("LORA_DEM_NORTH", "/data/dem/copernicus_glo30_north_vn.tif"))
LANDUSE_CENTRAL = Path(
    os.environ.get(
        "LORA_LANDUSE_CENTRAL",
        "/app/services/ml-service/reference_wireless/data/terrain/landuse_central.geojson",
    )
)
LANDUSE_NORTH = Path(
    os.environ.get(
        "LORA_LANDUSE_NORTH",
        "/app/services/ml-service/reference_wireless/data/terrain/landuse2.geojson",
    )
)
CSV_OUT = Path(
    os.environ.get(
        "LORA_TRAINING_CSV_OUT",
        "/app/services/ml-service/reference_wireless/data/processed/devices_history_full.csv",
    )
)

# Lat split for North VN vs Central VN DEMs (Hải Phòng > 20°N; Huế/ĐN/QN < 17.5°N).
LAT_SPLIT_N = 17.5

# Antenna heights (giữ nguyên reference_wireless).
DEVICE_ANTENNA_H_M = 1.5
GATEWAY_ANTENNA_H_M = 15.0

# Path sampling step.
PATH_STEP_M = 30.0


# --- DEM cache ---
class _DemCache:
    """Preload DEM raster vào memory 1 lần để lookup O(1).

    rasterio.dataset.read(1) trả full array. Index lookup qua `transform`
    inverse cho (lat,lon) → (row,col). Nhanh hơn ~100x so với mở/read mỗi call.
    """

    def __init__(self, path: Path):
        self._path = path
        self._loaded = False
        self.array: np.ndarray | None = None
        self.nodata: float | None = None
        self.transform = None
        self.bounds = None
        self.height = 0
        self.width = 0

    def load(self) -> None:
        if self._loaded:
            return
        log.info("loading DEM %s ...", self._path)
        with rasterio.open(self._path) as src:
            self.array = src.read(1)
            self.nodata = src.nodata
            self.transform = src.transform
            self.bounds = src.bounds
            self.height = src.height
            self.width = src.width
        log.info(
            "DEM loaded shape=%s bounds=%s",
            self.array.shape,
            self.bounds,
        )
        self._loaded = True

    def get(self, lat: float, lon: float) -> float | None:
        if self.array is None:
            return None
        b = self.bounds
        if not (b.bottom <= lat <= b.top and b.left <= lon <= b.right):
            return None
        # transform.index(lon, lat) → (row, col); but we use inverse manually
        # to avoid overhead of calling rasterio per-row.
        col = int((lon - self.transform.c) / self.transform.a)
        row = int((lat - self.transform.f) / self.transform.e)
        if not (0 <= row < self.height and 0 <= col < self.width):
            return None
        v = float(self.array[row, col])
        if self.nodata is not None and v == self.nodata:
            return None
        return v

    def window_std(self, lat: float, lon: float, half: int = 2) -> float | None:
        if self.array is None:
            return None
        b = self.bounds
        if not (b.bottom <= lat <= b.top and b.left <= lon <= b.right):
            return None
        col = int((lon - self.transform.c) / self.transform.a)
        row = int((lat - self.transform.f) / self.transform.e)
        r0, r1 = max(0, row - half), min(self.height, row + half + 1)
        c0, c1 = max(0, col - half), min(self.width, col + half + 1)
        w = self.array[r0:r1, c0:c1]
        if w.size == 0:
            return None
        if self.nodata is not None:
            w = w[w != self.nodata]
            if w.size == 0:
                return None
        return float(np.std(w))

    def window_slope(self, lat: float, lon: float) -> float | None:
        if self.array is None:
            return None
        b = self.bounds
        if not (b.bottom <= lat <= b.top and b.left <= lon <= b.right):
            return None
        col = int((lon - self.transform.c) / self.transform.a)
        row = int((lat - self.transform.f) / self.transform.e)
        if not (1 <= row < self.height - 1 and 1 <= col < self.width - 1):
            return None
        w = self.array[row - 1 : row + 2, col - 1 : col + 2]
        if self.nodata is not None and np.any(w == self.nodata):
            return None
        gy, gx = np.gradient(w)
        return float(np.mean(np.sqrt(gx**2 + gy**2)))


# --- Landuse cache ---
class _LanduseCache:
    """Load GeoJSON 1 lần + build spatial index. Lookup tag dominant qua sindex."""

    def __init__(self, path: Path):
        self._path = path
        self._loaded = False
        self.gdf: gpd.GeoDataFrame | None = None

    def load(self) -> None:
        if self._loaded:
            return
        log.info("loading landuse %s ...", self._path)
        try:
            self.gdf = gpd.read_file(self._path)
            # Trigger sindex build.
            _ = self.gdf.sindex
            log.info("landuse loaded %d polygons", len(self.gdf))
        except Exception as exc:
            log.warning("landuse load failed %s: %s", self._path, exc)
            self.gdf = gpd.GeoDataFrame(geometry=[])
        self._loaded = True

    def lookup(self, lat: float, lon: float) -> str:
        if self.gdf is None or len(self.gdf) == 0:
            return "unknown"
        pt = Point(lon, lat)
        idx = list(self.gdf.sindex.query(pt, predicate="contains"))
        if not idx:
            # sindex.query với predicate=contains đôi khi mỉss khi polygon
            # rất gần điểm; fallback intersects.
            idx = list(self.gdf.sindex.query(pt, predicate="intersects"))
            if not idx:
                return "unknown"
        row = self.gdf.iloc[idx[0]]
        for key in ("landuse", "natural"):
            if key in row and row[key] not in (None, "", "nan"):
                v = str(row[key])
                if v and v != "nan":
                    return v
        return "unknown"


# --- DB query ---
_QUERY_COMMUNITY = """
SELECT
  s.device_id                                    AS device,
  ST_Y(s.location::geometry)                     AS lat,
  ST_X(s.location::geometry)                     AS lon,
  g.code                                         AS gateway,
  ST_Y(g.location::geometry)                     AS gw_lat,
  ST_X(g.location::geometry)                     AS gw_lon,
  s.rssi_dbm                                     AS rssi,
  s.snr_db                                       AS snr,
  s.timestamp                                    AS time,
  (s.frequency_mhz * 1e6)::double precision      AS frequency,
  NULL::int                                      AS bandwidth,
  s.spreading_factor                             AS spreading_factor
FROM ts.survey_training s
JOIN geo.gateways g ON s.serving_gateway_id = g.id
WHERE s.submitted_for_community = TRUE
"""


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    return url


def query_db() -> pd.DataFrame:
    eng = create_engine(_database_url(), pool_pre_ping=True)
    with eng.connect() as conn:
        df = pd.read_sql(text(_QUERY_COMMUNITY), conn)
    log.info("queried %d community rows from ts.survey_training", len(df))
    return df


# --- Feature engineering (port từ reference_wireless) ---
def _haversine(lat1, lon1, lat2, lon2):
    earth_radius = 6371000.0
    phi1 = np.radians(lat1)
    phi2 = np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlmb = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlmb / 2) ** 2
    c = 2 * np.arcsin(np.sqrt(a))
    return earth_radius * c


def add_basic_features(df: pd.DataFrame) -> pd.DataFrame:
    df["distance"] = _haversine(df["lat"], df["lon"], df["gw_lat"], df["gw_lon"])
    df["log_distance"] = np.log10(df["distance"].clip(lower=1.0))
    df["delta_lat"] = df["lat"] - df["gw_lat"]
    df["delta_lon"] = df["lon"] - df["gw_lon"]
    df["angle"] = np.arctan2(df["delta_lat"], df["delta_lon"])
    df["gateway_id"] = df["gateway"].astype("category").cat.codes
    return df


def _pick_dem(lat: float, central: _DemCache, north: _DemCache) -> _DemCache:
    return north if lat >= LAT_SPLIT_N else central


def _pick_landuse(lat: float, central: _LanduseCache, north: _LanduseCache) -> _LanduseCache:
    return north if lat >= LAT_SPLIT_N else central


def _path_features(
    lat1,
    lon1,
    h1,
    lat2,
    lon2,
    h2,
    distance,
    frequency,
    dem_c: _DemCache,
    dem_n: _DemCache,
    lu_c: _LanduseCache,
    lu_n: _LanduseCache,
) -> dict:
    """Port từ terrain.get_path_features. Sample DEM + landuse dọc path TX-RX."""
    n = max(int(distance / PATH_STEP_M) + 1, 2)
    lats = np.linspace(lat1, lat2, n)
    lons = np.linspace(lon1, lon2, n)

    h1_total = (h1 or 0.0) + GATEWAY_ANTENNA_H_M
    h2_total = (h2 or 0.0) + DEVICE_ANTENNA_H_M

    c = 299792458.0
    wavelength = c / frequency if frequency else c / 9.22e8

    terrain_elev = np.full(n, np.nan)
    obstruction = np.full(n, np.nan)
    fresnel_clear = np.full(n, np.nan)
    types: list[str] = []

    for i, (la, lo) in enumerate(zip(lats, lons, strict=False)):
        d1 = (i / (n - 1)) * distance
        d2 = distance - d1
        fr_radius = np.sqrt((wavelength * d1 * d2) / (d1 + d2)) if d1 > 0 and d2 > 0 else 0.0

        dem = _pick_dem(la, dem_c, dem_n)
        elev = dem.get(la, lo)
        if elev is not None:
            terrain_elev[i] = elev

        lu = _pick_landuse(la, lu_c, lu_n)
        types.append(lu.lookup(la, lo))

        los_h = h1_total + (h2_total - h1_total) * (i / (n - 1))
        if elev is not None:
            obstruction[i] = elev - los_h
            fresnel_clear[i] = los_h - fr_radius - elev

    # Path stats — tolerate all-NaN columns.
    def _safe(fn, arr):
        try:
            v = fn(arr)
            return float(v) if np.isfinite(v) else float("nan")
        except (ValueError, RuntimeWarning):
            return float("nan")

    terrain_mean = _safe(np.nanmean, terrain_elev)
    terrain_std = _safe(np.nanstd, terrain_elev)
    terrain_min = _safe(np.nanmin, terrain_elev)
    terrain_max = _safe(np.nanmax, terrain_elev)
    terrain_range = (
        terrain_max - terrain_min
        if np.isfinite(terrain_max) and np.isfinite(terrain_min)
        else float("nan")
    )

    obstructed = obstruction > 0
    obstruction_ratio = _safe(np.nanmean, obstructed.astype(float))
    max_obstruction = _safe(np.nanmax, obstruction)
    mean_obstruction = _safe(np.nanmean, np.maximum(obstruction, 0))

    fresnel_blocked = fresnel_clear < 0
    fresnel_obstruction_ratio = _safe(np.nanmean, fresnel_blocked.astype(float))
    min_fresnel_clearance = _safe(np.nanmin, fresnel_clear)
    mean_fresnel_clearance = _safe(np.nanmean, fresnel_clear)

    counts = Counter(types)
    total = max(len(types), 1)
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
        "forest_ratio": counts.get("forest", 0) / total + counts.get("wood", 0) / total,
        "water_ratio": counts.get("water", 0) / total,
        "residential_ratio": counts.get("residential", 0) / total,
        "unknown_ratio": counts.get("unknown", 0) / total,
    }


def add_terrain_features(
    df: pd.DataFrame,
    dem_c: _DemCache,
    dem_n: _DemCache,
    lu_c: _LanduseCache,
    lu_n: _LanduseCache,
) -> pd.DataFrame:
    log.info("computing elevations for %d rows...", len(df))
    elev = []
    gw_elev = []
    for la, lo in zip(df["lat"], df["lon"], strict=False):
        dem = _pick_dem(la, dem_c, dem_n)
        elev.append(dem.get(la, lo))
    for la, lo in zip(df["gw_lat"], df["gw_lon"], strict=False):
        dem = _pick_dem(la, dem_c, dem_n)
        gw_elev.append(dem.get(la, lo))
    df["elevation"] = elev
    df["gw_elevation"] = gw_elev

    n_before = len(df)
    df = df.dropna(subset=["elevation", "gw_elevation"]).reset_index(drop=True)
    log.info("dropped %d rows ngoài coverage DEM, còn %d", n_before - len(df), len(df))

    df["delta_elevation"] = (
        df["elevation"] - df["gw_elevation"] + DEVICE_ANTENNA_H_M - GATEWAY_ANTENNA_H_M
    )

    # terrain_type (single sample at RX) — giữ schema cũ.
    log.info("looking up terrain_type...")
    df["terrain_type"] = [
        _pick_landuse(la, lu_c, lu_n).lookup(la, lo)
        for la, lo in zip(df["lat"], df["lon"], strict=False)
    ]

    df["distance_3d"] = np.sqrt(df["distance"] ** 2 + df["delta_elevation"] ** 2)
    df["log_distance_3d"] = np.log10(df["distance_3d"].clip(lower=1.0))

    d_km = df["distance_3d"] / 1000.0
    f_mhz = df["frequency"] / 1e6
    df["fspl"] = 20 * np.log10(d_km.clip(lower=0.001)) + 20 * np.log10(f_mhz) + 32.44

    df["elevation_angle"] = np.arctan2(df["delta_elevation"], df["distance_3d"])

    log.info("computing slope + roughness...")
    df["slope"] = [
        _pick_dem(la, dem_c, dem_n).window_slope(la, lo)
        for la, lo in zip(df["lat"], df["lon"], strict=False)
    ]
    df["roughness"] = [
        _pick_dem(la, dem_c, dem_n).window_std(la, lo)
        for la, lo in zip(df["lat"], df["lon"], strict=False)
    ]

    log.info("computing path features (terrain stats + obstruction + Fresnel) ...")
    t0 = time.time()
    path_rows = []
    log_every = max(1, len(df) // 20)
    for i, r in enumerate(df.itertuples(index=False)):
        path_rows.append(
            _path_features(
                r.gw_lat,
                r.gw_lon,
                r.gw_elevation,
                r.lat,
                r.lon,
                r.elevation,
                r.distance,
                r.frequency,
                dem_c,
                dem_n,
                lu_c,
                lu_n,
            )
        )
        if (i + 1) % log_every == 0:
            log.info("  path features %d/%d (%.0fs)", i + 1, len(df), time.time() - t0)
    path_df = pd.DataFrame(path_rows)
    log.info("path features done in %.0fs", time.time() - t0)

    df = pd.concat([df.reset_index(drop=True), path_df.reset_index(drop=True)], axis=1)
    return df


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    log.info("build_training_csv starting")

    df = query_db()
    if len(df) == 0:
        log.error("no community rows found — aborting")
        return 2

    dem_c = _DemCache(DEM_CENTRAL)
    dem_c.load()
    dem_n = _DemCache(DEM_NORTH)
    dem_n.load()
    lu_c = _LanduseCache(LANDUSE_CENTRAL)
    lu_c.load()
    lu_n = _LanduseCache(LANDUSE_NORTH)
    lu_n.load()

    df = add_basic_features(df)
    df = add_terrain_features(df, dem_c, dem_n, lu_c, lu_n)

    CSV_OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(CSV_OUT, index=False)
    log.info("wrote %s (%d rows, %.1f MB)", CSV_OUT, len(df), CSV_OUT.stat().st_size / 1e6)
    return 0


if __name__ == "__main__":
    sys.exit(main())
