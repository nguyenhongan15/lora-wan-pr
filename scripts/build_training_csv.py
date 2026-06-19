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

import json
import logging
import os
import sys
import time
from collections import Counter
from pathlib import Path

import geopandas as gpd
import h3
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

# --- Split rule (H3 + temporal hold-out) ---
# Plan: chia 70/15/15 train/val/test, phan tang theo o luoi H3 res 8
# (~0.74 km^2/cell, scale "khu pho"). Test = sessions moi nhat, cap 30%/cell.
# Val = sessions tiep theo. Train = phan con lai, loai bo cell nam trong
# buffer 1-ring quanh test/val (cho cell khoi rò ri canh nhau).
H3_RES = 8
SESSION_WINDOW_S = 3600  # 1 gio — khop toc do bo + cadence packet
TEST_QUOTA = 1500
VAL_QUOTA = 1500
BUFFER_RING = 0  # cell-disjoint H3 res 8 ~860m centroid da du tach roi; ring 1
# voi dataset 14k rows phu khu do thi DN se "an" 73% data vao vung dem.
TEST_CELL_CAP_RATIO = 0.30  # 1 cell khong chiem qua 30% test rows


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


def assign_h3_session_split(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Gan cot data_split (train/val/test) theo H3 res 8 + session 1h.

    Quy tac:
    - Session = (device, h3_cell, floor(ts / 3600s)). Moi packet trong cung
      session => cung split, tranh ro ri packet anh em.
    - test: sessions moi nhat, cap TEST_CELL_CAP_RATIO/cell, lay den TEST_QUOTA rows.
    - val:  sessions tiep theo, lay den VAL_QUOTA rows.
    - excluded_buffer: train candidate nam trong grid_disk(test+val cells, 1) — DROP.
    - train: con lai.

    Tra (df_kept, stats). df_kept da drop excluded_buffer + helper col.
    """
    log.info(
        "assigning H3+temporal split (res=%d, session=%ds, buffer_ring=%d)...",
        H3_RES,
        SESSION_WINDOW_S,
        BUFFER_RING,
    )

    df["h3_cell"] = [
        h3.latlng_to_cell(float(la), float(lo), H3_RES)
        for la, lo in zip(df["lat"], df["lon"], strict=False)
    ]

    ts_epoch = pd.to_datetime(df["time"], utc=True).astype("int64") // 1_000_000_000
    bucket = (ts_epoch // SESSION_WINDOW_S).astype("int64")
    device_str = df["device"].fillna("anon").astype(str)
    df["session_id"] = device_str + "|" + df["h3_cell"] + "|" + bucket.astype(str)
    df["_ts_epoch"] = ts_epoch

    # Aggregate theo CELL — quota cap cell de tranh blow-up khi cell co nhieu
    # session. Truoc day loop session-level + cap test_count theo s.n_rows nhung
    # labeling cuoi sweep toan cell → test bi vuot quota nhieu lan (vd. 5.8x).
    # Cell-level quota: pick cell newest-first, accumulate cell's total rows.
    cell_agg = (
        df.groupby("h3_cell", as_index=False)
        .agg(
            last_ts=("_ts_epoch", "max"),
            n_rows=("rssi", "size"),
        )
        .sort_values(["last_ts", "h3_cell"], ascending=[False, True])
    )
    n_sessions = df["session_id"].nunique()
    log.info(
        "total cells: %d, total sessions: %d (avg %.1f rows/cell)",
        len(cell_agg),
        n_sessions,
        len(df) / max(len(cell_agg), 1),
    )

    cap_per_cell = max(int(TEST_QUOTA * TEST_CELL_CAP_RATIO), 60)
    test_cells: set[str] = set()
    test_count = 0
    for c in cell_agg.itertuples(index=False):
        if test_count >= TEST_QUOTA:
            break
        if c.n_rows > cap_per_cell:
            # Cell hotspot (vd. truong dai hoc ~1000 rows) — skip de tranh
            # 1 cell chiem >30% test set, ep test phai phan tan dia ly.
            continue
        test_cells.add(c.h3_cell)
        test_count += c.n_rows

    val_cells: set[str] = set()
    val_count = 0
    for c in cell_agg.itertuples(index=False):
        if c.h3_cell in test_cells:
            continue
        if val_count >= VAL_QUOTA:
            break
        if c.n_rows > cap_per_cell:
            continue
        val_cells.add(c.h3_cell)
        val_count += c.n_rows

    test_buffer: set[str] = set()
    for c in test_cells:
        test_buffer.update(h3.grid_disk(c, BUFFER_RING))
    val_buffer: set[str] = set()
    for c in val_cells:
        val_buffer.update(h3.grid_disk(c, BUFFER_RING))
    exclude_zone = (test_buffer | val_buffer) - test_cells - val_cells

    def _label_row(cell: str) -> str:
        # Label HOAN TOAN theo cell — dam bao cell-disjoint train/val/test.
        # 1 cell co the chua nhieu session, neu chi label theo session_id thi
        # cac session khac cung cell se ket o train → leak cell (assert fail).
        if cell in test_cells:
            return "test"
        if cell in val_cells:
            return "val"
        if cell in exclude_zone:
            return "excluded_buffer"
        return "train"

    df["data_split"] = [_label_row(cell) for cell in df["h3_cell"]]

    counts = df["data_split"].value_counts().to_dict()
    log.info("split counts: %s", counts)
    n_excl = int(counts.get("excluded_buffer", 0))

    df = df[df["data_split"] != "excluded_buffer"].reset_index(drop=True)
    df = df.drop(columns=["_ts_epoch"])

    train_cells = set(df.loc[df["data_split"] == "train", "h3_cell"])
    test_cells_kept = set(df.loc[df["data_split"] == "test", "h3_cell"])
    assert train_cells.isdisjoint(test_cells_kept), (
        f"LEAK: {len(train_cells & test_cells_kept)} H3 cells appear in both train and test"
    )
    train_sess_kept = set(df.loc[df["data_split"] == "train", "session_id"])
    test_sess_kept = set(df.loc[df["data_split"] == "test", "session_id"])
    assert train_sess_kept.isdisjoint(test_sess_kept), "LEAK: session_id in both train and test"
    log.info("disjoint assertions OK (train/test cells + sessions)")

    def _ts_range(mask: pd.Series) -> dict:
        if mask.sum() == 0:
            return {"min": None, "max": None, "n": 0}
        sub = pd.to_datetime(df.loc[mask, "time"], utc=True)
        return {
            "min": sub.min().isoformat(),
            "max": sub.max().isoformat(),
            "n": int(mask.sum()),
        }

    stats = {
        "h3_res": H3_RES,
        "session_window_s": SESSION_WINDOW_S,
        "test_quota": TEST_QUOTA,
        "val_quota": VAL_QUOTA,
        "buffer_ring": BUFFER_RING,
        "test_cell_cap_ratio": TEST_CELL_CAP_RATIO,
        "n_train": int((df["data_split"] == "train").sum()),
        "n_val": int((df["data_split"] == "val").sum()),
        "n_test": int((df["data_split"] == "test").sum()),
        "n_excluded_buffer": n_excl,
        "n_cells_train": int(df.loc[df["data_split"] == "train", "h3_cell"].nunique()),
        "n_cells_val": int(df.loc[df["data_split"] == "val", "h3_cell"].nunique()),
        "n_cells_test": int(df.loc[df["data_split"] == "test", "h3_cell"].nunique()),
        "n_sessions_train": int(df.loc[df["data_split"] == "train", "session_id"].nunique()),
        "n_sessions_val": int(df.loc[df["data_split"] == "val", "session_id"].nunique()),
        "n_sessions_test": int(df.loc[df["data_split"] == "test", "session_id"].nunique()),
        "train_ts_range": _ts_range(df["data_split"] == "train"),
        "val_ts_range": _ts_range(df["data_split"] == "val"),
        "test_ts_range": _ts_range(df["data_split"] == "test"),
    }
    return df, stats


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
    df, split_stats = assign_h3_session_split(df)

    CSV_OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(CSV_OUT, index=False)
    log.info("wrote %s (%d rows, %.1f MB)", CSV_OUT, len(df), CSV_OUT.stat().st_size / 1e6)

    stats_path = CSV_OUT.parent / "train_split_stats.json"
    with stats_path.open("w") as f:
        json.dump(split_stats, f, indent=2)
    log.info("wrote split stats to %s", stats_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
