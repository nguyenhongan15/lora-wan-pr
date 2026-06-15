"""Precompute composite RSSI heatmap cho Đà Nẵng — phiên bản cuối cùng.

Công thức "Bản đồ ước lượng" (RSSI heatmap):
  * Gateway có điểm đo: P.1812 + DTM + per-gw NF + điểm đo (survey overlay).
  * Gateway chưa có điểm đo: P.1812 + DTM + per-gw NF.

Grid chốt 50m × 50m. KHÔNG dùng Stage 2 ML, KHÔNG dùng DSM. Survey overlay
luôn bật: per-gw, override cell có điểm đo bằng max RSSI thực đo (filter
ST_DistanceSphere < 50 km để né ETL corruption Hải Phòng↔Đà Nẵng). Gw không có
điểm đo → no-op tự nhiên (pure physics).

Output:
  - composite.geojson   : 6 dải RSSI (> -100, -105..-100, ..., < -120 dBm)
  - redundancy.geojson  : 3 dải gw_count (1, 2, ≥3)
  - per_gw/<code>.geojson: lớp riêng từng gateway
  - manifest.json       : generated_at, model, bbox, gateway list

Composite = max(RSSI) toàn gateway; gw_count = số gw nghe được ≥ -130 dBm.

Usage:
    python scripts/precompute_rssi_heatmap.py --force
    python scripts/precompute_rssi_heatmap.py --bbox 15.9,108.0,16.1,108.3
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import multiprocessing as mp
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
API_SRC = REPO_ROOT / "services" / "api-service" / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))

log = logging.getLogger("precompute_rssi")

# ITU-R P.2108-1 §3.2 — Terrestrial path clutter loss model chỉ valid cho
# distance ≥ 0.25 km. Cell gần hơn skip clutter (pure P.1812 path loss).
_P2108_MIN_DISTANCE_KM = 0.25


def meters_to_degrees(lat: float, dx_m: float, dy_m: float) -> tuple[float, float]:
    """Convert metres → degrees (dlon, dlat) at given latitude (local-flat)."""
    dlat = dy_m / 111320.0
    dlon = dx_m / (111320.0 * math.cos(math.radians(lat)))
    return dlon, dlat


@dataclass(frozen=True, slots=True)
class GatewayJob:
    """Pickleable per-gateway spec — passed across multiprocessing boundary."""

    code: str
    name: str
    lat: float
    lon: float
    altitude_m: float
    antenna_height_m: float
    antenna_gain_dbi: float
    tx_power_dbm: float
    frequency_mhz: float
    radius_km: float
    grid_m: float
    dem_dir: str
    surface_dem_dir: str
    output_path: str
    location_percent: float = 50.0
    environment_prob_pct: float = 0.0
    environment: str = "outdoor"
    landcover_dir: str = ""
    bias_path: str = ""
    smooth_px: int = 5
    noise_floor_dbm: float | None = None
    raster_dir: str = ""


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _compute_pl_grid(
    job: GatewayJob,
    nx: int,
    ny: int,
    lat_min: float,
    lon_min: float,
    step_dlat: float,
    step_dlon: float,
    skip_mask: np.ndarray | None = None,
) -> np.ndarray:
    """Sample P.1812 path-loss (+ P.2108 clutter khi DTM-only) trên grid nx×ny.

    Clutter source phụ thuộc surface mode:
      * `job.surface_dem_dir` rỗng (DTM-only): P.1812 + P.2108 statistic.
      * `job.surface_dem_dir` set (DSM): chỉ P.1812 — building heights đã có
        trong surface elevation; cộng P.2108 nữa = double-count.
    """
    from crc_covlib import simulation as covlib  # type: ignore[import-untyped]
    from crc_covlib.helper import itur_p2108  # type: ignore[import-untyped]

    pl_grid = np.full((ny, nx), np.nan, dtype=np.float32)

    eirp_dbm = job.tx_power_dbm + job.antenna_gain_dbi
    eirp_w = 10.0 ** ((eirp_dbm - 30.0) / 10.0)

    sim = covlib.Simulation()
    sim.SetTransmitterLocation(job.lat, job.lon)
    sim.SetTransmitterHeight(job.antenna_height_m)
    sim.SetTransmitterFrequency(job.frequency_mhz)
    sim.SetTransmitterPower(eirp_w, covlib.PowerType.EIRP)
    sim.SetReceiverHeightAboveGround(1.5)
    sim.SetPropagationModel(covlib.PropagationModel.ITU_R_P_1812)
    sim.SetITURP1812TimePercentage(50.0)
    sim.SetITURP1812LocationPercentage(job.location_percent)
    sim.SetITURP1812SurfaceProfileMethod(
        covlib.P1812SurfaceProfileMethod.P1812_USE_SURFACE_ELEV_DATA
    )
    sim.SetPrimaryTerrainElevDataSource(covlib.TerrainElevDataSource.TERR_ELEV_GEOTIFF)
    sim.SetTerrainElevDataSourceDirectory(
        covlib.TerrainElevDataSource.TERR_ELEV_GEOTIFF, job.dem_dir
    )
    sim.SetPrimarySurfaceElevDataSource(covlib.SurfaceElevDataSource.SURF_ELEV_GEOTIFF)
    sim.SetSurfaceElevDataSourceDirectory(
        covlib.SurfaceElevDataSource.SURF_ELEV_GEOTIFF,
        job.surface_dem_dir or job.dem_dir,
    )
    if job.landcover_dir:
        from lora_coverage_api.infrastructure.itu.landcover_mapping import (
            apply_esa_worldcover_mapping,
        )

        apply_esa_worldcover_mapping(sim, job.landcover_dir)
    sim.SetResultType(covlib.ResultType.PATH_LOSS_DB)
    sim.SetTerrainElevDataSamplingResolution(30)

    t0 = time.time()
    n_done = 0
    n_finite = 0
    n_errors = 0
    n_total = nx * ny
    freq_ghz = job.frequency_mhz / 1000.0
    apply_p2108 = not job.surface_dem_dir

    for iy in range(ny):
        lat = lat_min + iy * step_dlat
        for ix in range(nx):
            if skip_mask is not None and skip_mask[iy, ix]:
                n_done += 1
                continue
            lon = lon_min + ix * step_dlon
            try:
                pl = sim.GenerateReceptionPointResult(lat, lon)
                if math.isfinite(pl):
                    if apply_p2108:
                        d_km = _haversine_km(job.lat, job.lon, lat, lon)
                        if d_km >= _P2108_MIN_DISTANCE_KM:
                            clutter = itur_p2108.TerrestrialPathClutterLoss(
                                freq_ghz, d_km, job.location_percent
                            )
                            pl = pl + clutter
                    pl_grid[iy, ix] = pl
                    n_finite += 1
            except (RuntimeError, ValueError) as exc:
                if n_errors < 3:
                    log.warning(
                        "[%s] cell (%.5f, %.5f) %s: %s",
                        job.code,
                        lat,
                        lon,
                        type(exc).__name__,
                        exc,
                    )
                n_errors += 1

            n_done += 1
        if (iy + 1) % 50 == 0 or iy == ny - 1:
            elapsed = time.time() - t0
            rate = n_done / max(elapsed, 1e-3)
            eta = (n_total - n_done) / max(rate, 1e-3)
            log.info(
                "[%s] %d/%d (%.0f%%, %.0f%% finite) %.0f cells/s ETA %.0fs",
                job.code,
                n_done,
                n_total,
                100.0 * n_done / n_total,
                100.0 * n_finite / max(n_done, 1),
                rate,
                eta,
            )

    if n_errors:
        log.info("[%s] %d cell exception total trong %d cell", job.code, n_errors, n_total)

    if job.environment_prob_pct > 0.0:
        from crc_covlib.helper import itur_p2109  # type: ignore[import-untyped]

        bel_db = float(
            itur_p2109.BuildingEntryLoss(
                job.frequency_mhz / 1000.0,
                job.environment_prob_pct,
                itur_p2109.BuildingType.TRADITIONAL,
                0.0,
            )
        )
        if math.isfinite(bel_db):
            finite_mask = np.isfinite(pl_grid)
            pl_grid[finite_mask] += np.float32(bel_db)
            log.info(
                "[%s] P.2109 BEL +%.1f dB (env=%s, prob=%.0f%%)",
                job.code,
                bel_db,
                job.environment,
                job.environment_prob_pct,
            )
        else:
            log.warning(
                "[%s] P.2109 BEL non-finite cho freq=%.1f MHz, prob=%.0f%% — skip",
                job.code,
                job.frequency_mhz,
                job.environment_prob_pct,
            )

    return pl_grid


def _smooth_pl_grid(pl_grid: np.ndarray, kernel_px: int) -> np.ndarray:
    """NaN-safe median filter trên PL grid để khử spike DSM building-receiver."""
    if kernel_px <= 1:
        return pl_grid
    from scipy.ndimage import median_filter  # type: ignore[import-untyped]

    finite_mask = np.isfinite(pl_grid)
    if not finite_mask.any():
        return pl_grid
    fill = float(np.median(pl_grid[finite_mask]))
    filled = np.where(finite_mask, pl_grid, fill).astype(np.float32)
    smoothed = median_filter(filled, size=kernel_px, mode="nearest")
    smoothed[~finite_mask] = np.nan
    return smoothed


def _load_gateways(db_url: str, only_codes: list[str] | None) -> list[dict[str, Any]]:
    import psycopg

    sql = """
        SELECT code, name,
               ST_Y(location::geometry) AS lat,
               ST_X(location::geometry) AS lon,
               altitude_m, antenna_height_m, antenna_gain_dbi,
               tx_power_dbm, frequency_mhz, noise_floor_dbm
        FROM geo.gateways
        WHERE is_public = true
    """
    params: list[Any] = []
    if only_codes:
        sql += " AND code = ANY(%s)"
        params.append(only_codes)
    sql += " ORDER BY code"

    if db_url.startswith("postgresql+psycopg://"):
        db_url = db_url.replace("postgresql+psycopg://", "postgresql://", 1)

    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        assert cur.description is not None
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]


def _resolve_db_url() -> str:
    direct = os.environ.get("DATABASE_URL")
    if direct:
        return direct
    os.environ.setdefault("LORA_JWT_SECRET", "x" * 32)
    os.environ.setdefault(
        "LORA_LINKING_FERNET_KEYS",
        "ZmFrZWtleWZha2VrZXlmYWtla2V5ZmFrZWtleWZha2VrZXk=",
    )
    os.environ.setdefault("LORA_DEM_DIRECTORY", os.environ.get("LORA_DEM_DIRECTORY", "."))
    from lora_coverage_api.config import get_settings

    return get_settings().database_url


def _load_dotenv_if_present() -> None:
    """Auto-load repo-root `.env` để script chạy được từ PowerShell mà không
    cần set env thủ công. Không override env đã set sẵn ngoài shell."""
    env_path = REPO_ROOT / ".env"
    if not env_path.is_file():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        log.warning("python-dotenv không khả dụng — skip auto-load .env")
        return
    load_dotenv(env_path, override=False)


OUTPUT_DIR = REPO_ROOT / "apps" / "web-app" / "public" / "coverage" / "rssi"

# Đà Nẵng bbox: lat 15.80..16.30, lon 107.90..108.50 (~55km × 65km).
BBOX_DANANG = (15.80, 107.90, 16.30, 108.50)

GRID_METERS_DEFAULT = 50.0
# Ngưỡng "gateway có nghe được" cho overlay gw_count. -130 = SF12 limit + margin.
REDUNDANCY_THRESHOLD_DBM = -130.0

# 6 visible RSSI bins khớp SURVEY_RSSI_BINS (5 dB step trong -120..-100, plus
# tail trên/dưới). Cell < -130 dBm KHÔNG polygonize → transparent, basemap lộ
# ra. Bin id 1 = mạnh nhất, 6 = yếu nhất. Palette + label frontend mapping ở
# apps/web-app/src/components/legend.js (SURVEY_RSSI_BINS, single source of
# truth) — Survey Points map + Estimate composite map dùng chung scheme.
RSSI_BINS: list[tuple[float, float, int, str]] = [
    (-100.0, math.inf, 1, "> -100 dBm"),
    (-105.0, -100.0, 2, "-105 .. -100 dBm"),
    (-110.0, -105.0, 3, "-110 .. -105 dBm"),
    (-115.0, -110.0, 4, "-115 .. -110 dBm"),
    (-120.0, -115.0, 5, "-120 .. -115 dBm"),
    (-130.0, -120.0, 6, "< -120 dBm"),
]
GW_COUNT_BINS: list[tuple[int, int, str]] = [
    (1, 1, "1 gateway"),
    (2, 2, "2 gateways"),
    (3, 99, ">= 3 gateways"),
]


@dataclass(frozen=True, slots=True, eq=False)
class RssiJob:
    """Per-gateway compute spec: sub-bbox snapped to common grid indices.

    `skip_mask` (Phase B của 2-phase dominance prefilter): bool ndarray shape
    (sub_ny, sub_nx). True = bỏ qua cell. None = compute full sub-grid (default).
    """

    code: str
    name: str
    lat: float
    lon: float
    altitude_m: float
    antenna_height_m: float
    antenna_gain_dbi: float
    tx_power_dbm: float
    frequency_mhz: float
    noise_floor_dbm: float | None
    iy_start: int
    ix_start: int
    sub_ny: int
    sub_nx: int
    sub_lat_min: float
    sub_lon_min: float
    step_dlat: float
    step_dlon: float
    grid_m: float
    dem_dir: str
    location_percent: float
    smooth_px: int
    skip_mask: Any = None


def _compute_one_rssi(job: RssiJob) -> dict[str, Any]:
    """Worker: tính UL RSSI sub-grid cho 1 gateway (P.1812 + DTM + per-gw NF)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    t0 = time.time()

    gw_job = GatewayJob(
        code=job.code,
        name=job.name,
        lat=job.lat,
        lon=job.lon,
        altitude_m=job.altitude_m,
        antenna_height_m=job.antenna_height_m,
        antenna_gain_dbi=job.antenna_gain_dbi,
        tx_power_dbm=job.tx_power_dbm,
        frequency_mhz=job.frequency_mhz,
        radius_km=0.0,
        grid_m=job.grid_m,
        dem_dir=job.dem_dir,
        surface_dem_dir="",
        output_path="",
        location_percent=job.location_percent,
        environment_prob_pct=0.0,
        environment="outdoor",
        landcover_dir="",
        bias_path="",
        smooth_px=job.smooth_px,
        noise_floor_dbm=job.noise_floor_dbm,
    )

    pl_grid = _compute_pl_grid(
        gw_job,
        job.sub_nx,
        job.sub_ny,
        job.sub_lat_min,
        job.sub_lon_min,
        job.step_dlat,
        job.step_dlon,
        skip_mask=job.skip_mask,
    )
    if job.smooth_px > 1:
        pl_grid = _smooth_pl_grid(pl_grid, job.smooth_px)

    # PL → UL RSSI: rssi_ul = device_eirp + gw_rx_gain - pl. Cùng formula với
    # training residual target (measured uplink RSSI tại gateway).
    from lora_coverage_api.domain.coverage import (
        AS923_DEVICE_TX_POWER_CAP_DBM,
        DEVICE_DEFAULT_TX_GAIN_DBI,
    )

    device_eirp = AS923_DEVICE_TX_POWER_CAP_DBM + DEVICE_DEFAULT_TX_GAIN_DBI
    rssi_grid = (device_eirp + job.antenna_gain_dbi - pl_grid).astype(np.float32)

    elapsed = time.time() - t0
    n_finite = int(np.isfinite(rssi_grid).sum())
    n_total = job.sub_ny * job.sub_nx
    log.info(
        "[%s] sub-grid %d×%d done %.0fs (%d/%d finite, %.0f%%)",
        job.code,
        job.sub_ny,
        job.sub_nx,
        elapsed,
        n_finite,
        n_total,
        100.0 * n_finite / max(n_total, 1),
    )
    return {
        "code": job.code,
        "name": job.name,
        "lat": job.lat,
        "lon": job.lon,
        "noise_floor_dbm": job.noise_floor_dbm,
        "iy_start": job.iy_start,
        "ix_start": job.ix_start,
        "sub_ny": job.sub_ny,
        "sub_nx": job.sub_nx,
        "rssi_grid": rssi_grid,
        "elapsed_s": round(elapsed, 1),
        "n_finite": n_finite,
        "n_total": n_total,
    }


def _danang_ocean_polygon(
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
) -> Any:
    """Hand-traced Đà Nẵng coastline: bbox - (mainland + Sơn Trà). Cell sông Hàn
    nằm INSIDE mainland → ngoài ocean → preserve khi mask = DEM giao ocean."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    mainland = Polygon(
        [
            (lon_min, lat_max),
            (lon_min, lat_min),
            (108.300, lat_min),  # bottom of mainland at bbox south
            (108.330, 15.900),  # Non Nuoc / Hoa Hai coast
            (108.305, 16.000),  # Bac My An
            (108.255, 16.060),  # My Khe south
            (108.250, 16.080),  # near Han river mouth (east)
            (108.230, 16.095),  # Han river mouth — mainland east bank
            (108.205, 16.100),  # bay south
            (108.175, 16.130),  # bay west lower
            (108.165, 16.180),  # bay west mid
            (108.155, 16.220),  # bay west upper
            (108.130, 16.290),  # Hai Van pass coast
            (lon_min, lat_max),
        ]
    )
    son_tra = Polygon(
        [
            (108.220, 16.105),
            (108.260, 16.170),
            (108.300, 16.180),
            (108.370, 16.170),
            (108.400, 16.115),
            (108.355, 16.085),
            (108.280, 16.085),
            (108.220, 16.105),
        ]
    )
    bbox_poly = Polygon(
        [
            (lon_min, lat_min),
            (lon_max, lat_min),
            (lon_max, lat_max),
            (lon_min, lat_max),
            (lon_min, lat_min),
        ]
    )
    return bbox_poly.difference(unary_union([mainland, son_tra]))


def _build_sea_mask_dem(
    dem_path: str,
    lat_min: float,
    lon_min: float,
    ny: int,
    nx: int,
    step_dlat: float,
    step_dlon: float,
    threshold_m: float,
    restrict_to_ocean: bool = True,
) -> np.ndarray:
    """Sea mask = (DEM ≤ threshold) AND (cell INSIDE hand-traced ocean polygon).

    `restrict_to_ocean=True` (mặc định): chỉ mask cell nằm trong polygon biển/vịnh
    Đà Nẵng → sông Hàn + lạch trong đất liền (elev≈0 nhưng nằm trong mainland) sẽ
    được preserve. `restrict_to_ocean=False`: pure DEM threshold (mask cả sông).
    """
    import rasterio
    from rasterio.windows import from_bounds

    lat_max = lat_min + (ny - 1) * step_dlat
    lon_max = lon_min + (nx - 1) * step_dlon
    with rasterio.open(dem_path) as ds:
        if ds.crs is None or ds.crs.to_epsg() != 4326:
            raise RuntimeError(f"DEM CRS must be EPSG:4326, got {ds.crs}")
        win = from_bounds(
            lon_min - 0.002,
            lat_min - 0.002,
            lon_max + 0.002,
            lat_max + 0.002,
            ds.transform,
        )
        arr = ds.read(1, window=win, boundless=True, fill_value=0.0)
        wt = ds.window_transform(win)
    if wt.b != 0.0 or wt.d != 0.0:
        raise RuntimeError(
            "DEM transform is rotated; nearest-neighbor lookup needs axis-aligned raster"
        )
    lats = lat_min + np.arange(ny) * step_dlat
    lons = lon_min + np.arange(nx) * step_dlon
    cols = np.clip(((lons - wt.c) / wt.a).astype(np.int32), 0, arr.shape[1] - 1)
    rows = np.clip(((lats - wt.f) / wt.e).astype(np.int32), 0, arr.shape[0] - 1)
    elev = arr[rows[:, None], cols[None, :]]
    mask = elev <= threshold_m
    n_dem = int(mask.sum())
    if restrict_to_ocean:
        from shapely import contains_xy

        ocean = _danang_ocean_polygon(lat_min, lon_min, lat_max, lon_max)
        xs = np.broadcast_to(lons[np.newaxis, :], (ny, nx))
        ys = np.broadcast_to(lats[:, np.newaxis], (ny, nx))
        in_ocean = contains_xy(ocean, xs, ys)
        mask = mask & in_ocean
        log.info(
            "DEM sea mask: %d cell ≤ %.2fm; %d trong ocean polygon → %d final (%.1f%%)",
            n_dem,
            threshold_m,
            int(in_ocean.sum()),
            int(mask.sum()),
            100.0 * mask.sum() / (ny * nx),
        )
    else:
        log.info(
            "DEM sea mask (no ocean restrict): %d/%d cell ≤ %.2fm (%.1f%%)",
            n_dem,
            ny * nx,
            threshold_m,
            100.0 * n_dem / (ny * nx),
        )
    return mask


def _smooth_nan_safe(
    arr: np.ndarray,
    sigma: float,
) -> np.ndarray:
    """NaN-safe Gaussian smoothing: làm mịn tia diffraction artifact của P.1812
    mà KHÔNG lan giá trị finite ra cell NaN (no-coverage / sea). Standard
    scipy.ndimage.gaussian_filter propagate NaN khắp kernel → vô dụng cho heatmap.
    Cách chuẩn: filter(arr*mask)/filter(mask), cell ban đầu NaN giữ NaN.
    """
    from scipy.ndimage import gaussian_filter

    finite = np.isfinite(arr)
    filled = np.where(finite, arr, 0.0).astype(np.float32)
    weights = finite.astype(np.float32)
    num = gaussian_filter(filled, sigma=sigma, mode="constant", cval=0.0)
    den = gaussian_filter(weights, sigma=sigma, mode="constant", cval=0.0)
    out = np.full_like(arr, np.nan, dtype=np.float32)
    safe = den > 1e-6
    out[safe] = num[safe] / den[safe]
    out[~finite] = np.nan
    return out


def _polygonize_rssi_grid(
    rssi_grid: np.ndarray,
    lon_origin: float,
    lat_origin: float,
    step_dlon: float,
    step_dlat: float,
    opening_struct: np.ndarray | None,
) -> list[dict[str, Any]]:
    """RSSI grid → list GeoJSON Feature (1 per RSSI bin). Reused cho composite
    và per-gateway output."""
    features: list[dict[str, Any]] = []
    for low, high, bin_id, label in RSSI_BINS:
        if math.isinf(high):
            mask = np.isfinite(rssi_grid) & (rssi_grid >= low)
        else:
            mask = np.isfinite(rssi_grid) & (rssi_grid >= low) & (rssi_grid < high)
        if opening_struct is not None:
            from scipy.ndimage import binary_opening

            mask = binary_opening(mask, structure=opening_struct)
        polys = _polygonize_mask(mask, lon_origin, lat_origin, step_dlon, step_dlat)
        if not polys:
            continue
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "bin": bin_id,
                    "rssi_low_dbm": (low if not math.isinf(low) else None),
                    "rssi_high_dbm": (high if not math.isinf(high) else None),
                    "label": label,
                },
                "geometry": {"type": "MultiPolygon", "coordinates": polys},
            }
        )
    return features


def _polygonize_mask(
    mask: np.ndarray,
    lon0: float,
    lat0: float,
    step_dlon: float,
    step_dlat: float,
) -> list[list[list[list[float]]]]:
    """Binary mask → MultiPolygon coords via rasterio.features.shapes (GDAL native).

    GDAL polygonize xử lý hole topology native trong O(cell) thay vì O(poly²)
    pairwise covers của marching-squares assembler. Stair-step pixel boundary
    thay sub-pixel contour — chấp nhận được ở 10m visualization."""
    if mask.sum() == 0:
        return []
    from rasterio.features import shapes  # type: ignore[import-untyped]
    from rasterio.transform import from_origin

    ny, _nx = mask.shape
    lat_max = lat0 + (ny - 1) * step_dlat
    # mask[iy=0] = lat0 (south); rasterio expects north-up → flip vertical.
    mask_u8 = np.ascontiguousarray(mask[::-1, :].astype(np.uint8))
    transform = from_origin(lon0, lat_max, step_dlon, step_dlat)
    polys: list[list[list[list[float]]]] = []
    for geom, val in shapes(mask_u8, mask=mask_u8.astype(bool), transform=transform):
        if val != 1 or geom.get("type") != "Polygon":
            continue
        rings = geom["coordinates"]
        rounded = [[[round(c[0], 6), round(c[1], 6)] for c in ring] for ring in rings]
        polys.append(rounded)
    return polys


def _build_jobs(
    rows: list[dict[str, Any]],
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
    step_dlat: float,
    step_dlon: float,
    nx: int,
    ny: int,
    grid_m: float,
    per_gw_radius_km: float,
    dem_dir: str,
    location_percent: float,
    smooth_px: int,
    skip_masks: dict[str, np.ndarray] | None = None,
) -> list[RssiJob]:
    """Build RssiJob list. If `skip_masks` given (Phase B), skip mỗi gw không có
    mask hoặc mask all-True (dominant nowhere)."""
    jobs: list[RssiJob] = []
    radius_deg_lat = per_gw_radius_km * 1000.0 / 111320.0
    for r in rows:
        gw_lat = float(r["lat"])
        gw_lon = float(r["lon"])
        radius_deg_lon = per_gw_radius_km * 1000.0 / (111320.0 * math.cos(math.radians(gw_lat)))
        sub_lat_lo = max(gw_lat - radius_deg_lat, lat_min)
        sub_lat_hi = min(gw_lat + radius_deg_lat, lat_max)
        sub_lon_lo = max(gw_lon - radius_deg_lon, lon_min)
        sub_lon_hi = min(gw_lon + radius_deg_lon, lon_max)
        if sub_lat_lo >= sub_lat_hi or sub_lon_lo >= sub_lon_hi:
            log.info("[%s] sub-bbox không giao grid — skip", r["code"])
            continue
        iy_start = max(0, math.floor((sub_lat_lo - lat_min) / step_dlat))
        ix_start = max(0, math.floor((sub_lon_lo - lon_min) / step_dlon))
        iy_end = min(ny, math.ceil((sub_lat_hi - lat_min) / step_dlat) + 1)
        ix_end = min(nx, math.ceil((sub_lon_hi - lon_min) / step_dlon) + 1)
        sub_ny = iy_end - iy_start
        sub_nx = ix_end - ix_start
        if sub_ny <= 0 or sub_nx <= 0:
            continue
        sub_lat_origin = lat_min + iy_start * step_dlat
        sub_lon_origin = lon_min + ix_start * step_dlon
        code = str(r["code"])
        gw_skip_mask: np.ndarray | None = None
        if skip_masks is not None:
            gw_skip_mask = skip_masks.get(code)
            if gw_skip_mask is None:
                log.info("[%s] không có skip_mask — gw dominant nowhere, skip Phase B", code)
                continue
            if gw_skip_mask.shape != (sub_ny, sub_nx):
                raise RuntimeError(
                    f"[{code}] skip_mask shape {gw_skip_mask.shape} != ({sub_ny}, {sub_nx})"
                )
            if gw_skip_mask.all():
                log.info("[%s] tất cả cells skip — gw dominant nowhere", code)
                continue
        jobs.append(
            RssiJob(
                code=code,
                name=str(r["name"]),
                lat=gw_lat,
                lon=gw_lon,
                altitude_m=float(r["altitude_m"]),
                antenna_height_m=float(r["antenna_height_m"]),
                antenna_gain_dbi=float(r["antenna_gain_dbi"]),
                tx_power_dbm=float(r["tx_power_dbm"]),
                frequency_mhz=float(r["frequency_mhz"]),
                noise_floor_dbm=(
                    float(r["noise_floor_dbm"]) if r.get("noise_floor_dbm") is not None else None
                ),
                iy_start=iy_start,
                ix_start=ix_start,
                sub_ny=sub_ny,
                sub_nx=sub_nx,
                sub_lat_min=sub_lat_origin,
                sub_lon_min=sub_lon_origin,
                step_dlat=step_dlat,
                step_dlon=step_dlon,
                grid_m=grid_m,
                dem_dir=dem_dir,
                location_percent=location_percent,
                smooth_px=smooth_px,
                skip_mask=gw_skip_mask,
            )
        )
    return jobs


def _run_jobs(jobs: list[RssiJob], workers: int) -> list[dict[str, Any]]:
    """Run a batch of RssiJob via multiprocessing pool (or sequential if workers <= 1)."""
    if not jobs:
        return []
    t_start = time.time()
    if workers <= 1 or len(jobs) <= 1:
        results = [_compute_one_rssi(j) for j in jobs]
    else:
        with mp.Pool(processes=workers) as pool:
            results = pool.map(_compute_one_rssi, jobs)
    log.info("All %d gateway done in %.0fs", len(results), time.time() - t_start)
    return results


def _composite_results(
    results: list[dict[str, Any]],
    ny: int,
    nx: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Stitch per-gw sub-grids onto common (ny, nx) grid.

    Returns (composite_rssi, gw_count, dominant_idx):
      - composite_rssi: max(RSSI) per cell, NaN nếu không gw nào cover
      - gw_count: số gw có RSSI ≥ REDUNDANCY_THRESHOLD_DBM
      - dominant_idx: index vào `results` của gw thắng max (-1 = không gw nào)
    """
    composite = np.full((ny, nx), np.nan, dtype=np.float32)
    gw_count = np.zeros((ny, nx), dtype=np.uint8)
    dominant = np.full((ny, nx), -1, dtype=np.int16)
    for gw_idx, r in enumerate(results):
        sub = r["rssi_grid"]
        iy0, ix0 = r["iy_start"], r["ix_start"]
        iy1, ix1 = iy0 + r["sub_ny"], ix0 + r["sub_nx"]
        block = composite[iy0:iy1, ix0:ix1]
        is_winner = np.isfinite(sub) & (~np.isfinite(block) | (sub > block))
        composite[iy0:iy1, ix0:ix1] = np.fmax(block, sub)
        dom_block = dominant[iy0:iy1, ix0:ix1]
        dominant[iy0:iy1, ix0:ix1] = np.where(is_winner, np.int16(gw_idx), dom_block)
        heard = (np.nan_to_num(sub, nan=-9999.0) >= REDUNDANCY_THRESHOLD_DBM).astype(np.uint8)
        gw_count[iy0:iy1, ix0:ix1] = gw_count[iy0:iy1, ix0:ix1] + heard
    return composite, gw_count, dominant


def _build_skip_masks_fine(
    rows: list[dict[str, Any]],
    dominant_coarse: np.ndarray,
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
    step_dlat_fine: float,
    step_dlon_fine: float,
    nx_fine: int,
    ny_fine: int,
    step_dlat_coarse: float,
    step_dlon_coarse: float,
    ny_coarse: int,
    nx_coarse: int,
    per_gw_radius_km: float,
    dominance_buffer: int,
) -> dict[str, np.ndarray]:
    """For each gw, derive fine-grid skip_mask (True = NOT dominant) by upsampling
    dilated coarse dominance map. Order of `rows` must match `_composite_results`
    gw_idx assignment in Phase A."""
    from scipy.ndimage import binary_dilation  # type: ignore[import-untyped]

    skip_masks: dict[str, np.ndarray] = {}
    radius_deg_lat = per_gw_radius_km * 1000.0 / 111320.0
    for gw_idx, r in enumerate(rows):
        code = str(r["code"])
        gw_lat = float(r["lat"])
        gw_lon = float(r["lon"])
        radius_deg_lon = per_gw_radius_km * 1000.0 / (111320.0 * math.cos(math.radians(gw_lat)))
        sub_lat_lo = max(gw_lat - radius_deg_lat, lat_min)
        sub_lat_hi = min(gw_lat + radius_deg_lat, lat_max)
        sub_lon_lo = max(gw_lon - radius_deg_lon, lon_min)
        sub_lon_hi = min(gw_lon + radius_deg_lon, lon_max)
        if sub_lat_lo >= sub_lat_hi or sub_lon_lo >= sub_lon_hi:
            continue
        iy_start = max(0, math.floor((sub_lat_lo - lat_min) / step_dlat_fine))
        ix_start = max(0, math.floor((sub_lon_lo - lon_min) / step_dlon_fine))
        iy_end = min(ny_fine, math.ceil((sub_lat_hi - lat_min) / step_dlat_fine) + 1)
        ix_end = min(nx_fine, math.ceil((sub_lon_hi - lon_min) / step_dlon_fine) + 1)
        sub_ny = iy_end - iy_start
        sub_nx = ix_end - ix_start
        if sub_ny <= 0 or sub_nx <= 0:
            continue
        gw_dom_coarse = dominant_coarse == np.int16(gw_idx)
        if not gw_dom_coarse.any():
            continue
        if dominance_buffer > 0:
            gw_dom_coarse = binary_dilation(gw_dom_coarse, iterations=dominance_buffer)
        iy_fine_global = (iy_start + np.arange(sub_ny)).astype(np.float64)
        ix_fine_global = (ix_start + np.arange(sub_nx)).astype(np.float64)
        fine_lat = lat_min + iy_fine_global * step_dlat_fine
        fine_lon = lon_min + ix_fine_global * step_dlon_fine
        iy_c = np.clip(((fine_lat - lat_min) / step_dlat_coarse).astype(np.int32), 0, ny_coarse - 1)
        ix_c = np.clip(((fine_lon - lon_min) / step_dlon_coarse).astype(np.int32), 0, nx_coarse - 1)
        in_region = gw_dom_coarse[iy_c[:, None], ix_c[None, :]]
        if not in_region.any():
            continue
        skip_masks[code] = (~in_region).astype(bool)
    return skip_masks


def _upsample_coarse_to_fine(
    coarse: np.ndarray,
    lat_min: float,
    lon_min: float,
    step_dlat_coarse: float,
    step_dlon_coarse: float,
    ny_coarse: int,
    nx_coarse: int,
    step_dlat_fine: float,
    step_dlon_fine: float,
    ny_fine: int,
    nx_fine: int,
) -> np.ndarray:
    """Nearest-neighbor upsample coarse 2D grid → fine. Shared lat_min/lon_min origin."""
    iy_fine = np.arange(ny_fine).astype(np.float64)
    ix_fine = np.arange(nx_fine).astype(np.float64)
    fine_lat = lat_min + iy_fine * step_dlat_fine
    fine_lon = lon_min + ix_fine * step_dlon_fine
    iy_c = np.clip(((fine_lat - lat_min) / step_dlat_coarse).astype(np.int32), 0, ny_coarse - 1)
    ix_c = np.clip(((fine_lon - lon_min) / step_dlon_coarse).astype(np.int32), 0, nx_coarse - 1)
    return coarse[iy_c[:, None], ix_c[None, :]]


def _load_survey_overlay_points(
    db_url: str,
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
    max_link_km: float,
) -> dict[str, list[tuple[float, float, float]]]:
    """Load survey points group theo gw code: {code: [(lat, lon, rssi_dbm), ...]}.

    Per-gw overlay yêu cầu mỗi gw chỉ nhận điểm đo của serving_gateway của mình.
    Filter ST_DistanceSphere < max_link_km để né ETL corruption (Hải Phòng row
    gắn gw Đà Nẵng, ~554 km — xem memory project_survey_etl_corruption_2026_05_27).
    """
    import psycopg

    # Strip SQLAlchemy driver suffix (postgresql+psycopg:// → postgresql://)
    # vì psycopg.connect() raw không parse được "+driver" prefix.
    if "://" in db_url:
        scheme, rest = db_url.split("://", 1)
        if "+" in scheme:
            db_url = scheme.split("+", 1)[0] + "://" + rest

    sql = """
        SELECT gw.code,
               ST_Y(t.location::geometry) AS lat,
               ST_X(t.location::geometry) AS lon,
               t.rssi_dbm
        FROM ts.survey_training t
        JOIN geo.gateways gw ON gw.id = t.serving_gateway_id
        WHERE ST_Y(t.location::geometry) BETWEEN %s AND %s
          AND ST_X(t.location::geometry) BETWEEN %s AND %s
          AND t.rssi_dbm IS NOT NULL
          AND t.serving_gateway_id IS NOT NULL
          AND ST_DistanceSphere(t.location::geometry, gw.location::geometry) < %s
    """
    pts_by_gw: dict[str, list[tuple[float, float, float]]] = {}
    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute(sql, (lat_min, lat_max, lon_min, lon_max, max_link_km * 1000.0))
        for code, lat, lon, rssi in cur.fetchall():
            pts_by_gw.setdefault(str(code), []).append((float(lat), float(lon), float(rssi)))
    return pts_by_gw


def _apply_survey_overlay(
    grid: np.ndarray,
    survey_pts: list[tuple[float, float, float]],
    lat_origin: float,
    lon_origin: float,
    step_dlat: float,
    step_dlon: float,
    ny: int,
    nx: int,
) -> dict[str, Any]:
    """Override grid[iy,ix] với max RSSI survey point rơi vào cell đó.

    "Chỉ chèn đúng cell" — không buffer/spread, không weighted blend. Survey
    luôn thắng nếu cell có ≥1 điểm đo. Caller cung cấp (lat_origin, lon_origin)
    là góc dưới-trái của `grid` để function dùng cho cả composite full grid lẫn
    per-gw sub-grid.
    """
    if not survey_pts:
        return {"n_points": 0, "n_points_in_grid": 0, "n_cells_overlaid": 0}
    lats = np.fromiter((p[0] for p in survey_pts), dtype=np.float64, count=len(survey_pts))
    lons = np.fromiter((p[1] for p in survey_pts), dtype=np.float64, count=len(survey_pts))
    rssi = np.fromiter((p[2] for p in survey_pts), dtype=np.float32, count=len(survey_pts))
    iy = np.floor((lats - lat_origin) / step_dlat).astype(np.int64)
    ix = np.floor((lons - lon_origin) / step_dlon).astype(np.int64)
    in_grid = (iy >= 0) & (iy < ny) & (ix >= 0) & (ix < nx)
    iy = iy[in_grid]
    ix = ix[in_grid]
    rssi = rssi[in_grid]
    n_in_grid = int(in_grid.sum())
    if n_in_grid == 0:
        return {
            "n_points": len(survey_pts),
            "n_points_in_grid": 0,
            "n_cells_overlaid": 0,
        }
    # Per-cell max across all survey points landing there.
    flat_idx = iy * nx + ix
    cell_max: dict[int, float] = {}
    for k in range(n_in_grid):
        f = int(flat_idx[k])
        v = float(rssi[k])
        cur = cell_max.get(f)
        if cur is None or v > cur:
            cell_max[f] = v
    # Strict override: cell có điểm đo → luôn dùng RSSI thực đo, kể cả khi
    # P.1812 dự đoán mạnh hơn. Lý do: ground truth thắng prediction; survey
    # cần lộ ra cả vùng obstruction model đang lạc quan quá mức.
    for f, v in cell_max.items():
        cy, cx = divmod(f, nx)
        grid[cy, cx] = v
    return {
        "n_points": len(survey_pts),
        "n_points_in_grid": n_in_grid,
        "n_cells_overlaid": len(cell_max),
    }


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    _load_dotenv_if_present()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--grid-m", type=float, default=GRID_METERS_DEFAULT)
    parser.add_argument(
        "--coarse-grid-m",
        type=float,
        default=GRID_METERS_DEFAULT,
        help=(
            "Phase A grid (m) cho 2-phase per-gw dominance prefilter. Khi"
            " --grid-m < --coarse-grid-m, Phase A chạy ở --coarse-grid-m để"
            " xác định gateway dominant tại mỗi cell, rồi Phase B chạy"
            " --grid-m chỉ tính cell nơi gateway này dominant (giảm ~N× cost"
            " với N = số gateway). Default = --grid-m (single-phase)."
        ),
    )
    parser.add_argument(
        "--dominance-buffer",
        type=int,
        default=1,
        help=(
            "Buffer coarse cells around mỗi gw's dominant region trong Phase B."
            " Default 1 = dilate ±1 coarse cell để xử lý edge artifact ở boundary."
        ),
    )
    parser.add_argument(
        "--smooth-sigma",
        type=float,
        default=0.0,
        help=(
            "NaN-safe Gaussian smoothing σ (đơn vị cell) áp lên composite RSSI"
            " grid trước khi polygonize. 0 = tắt. Khuyến nghị 2.0 (≈20m @ grid"
            " 10m) để làm mịn tia diffraction artifact của P.1812 trên DSM"
            " building-resolution. NaN cell giữ nguyên (không lan ra biển/no-cov)."
        ),
    )
    parser.add_argument(
        "--opening-size",
        type=int,
        default=0,
        help=(
            "Morphological opening kernel size (cell, vuông) áp lên BIN MASK"
            " trước polygonize. Xoá radial strip thin <N cell rộng (diffraction"
            " wedge artifact mà gaussian không xoá hết). 0=tắt. Khuyến nghị 3-5."
        ),
    )
    parser.add_argument(
        "--bbox",
        default="danang",
        help="'danang' (default) or 'lat_min,lon_min,lat_max,lon_max'",
    )
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--smooth-px",
        type=int,
        default=5,
        help="Median filter kernel on PL grid (px). 0/1 = disabled.",
    )
    parser.add_argument(
        "--location-percent",
        type=float,
        default=10.0,
        help=(
            "P.1812 location %. Default 10 = 'RSSI mà 90% địa điểm vượt' — khớp"
            " survey thực tế (user ưu tiên vị trí thu được sóng). Loc%=50 (median)"
            " quá pessimistic, gây bias -6 dB cho heatmap composite. Min-SF map"
            " vẫn dùng loc%=50 (design margin)."
        ),
    )
    parser.add_argument(
        "--gateway-code",
        default=None,
        help="Filter gw codes (comma-separated). Default = all public.",
    )
    parser.add_argument(
        "--per-gw-radius-km",
        type=float,
        default=15.0,
        help=(
            "Sub-bbox half-side (km) per gateway around its location. Cell xa hơn "
            "khả năng RSSI < -140 dBm vẫn rớt khỏi bin cuối. Default 15."
        ),
    )
    parser.add_argument(
        "--max-radius-km",
        type=float,
        default=0.0,
        help=(
            "Circular clip radius (km) post-composite: cell xa nhất khỏi MỌI"
            " gateway > radius này → NaN. 0=tắt (chỉ giới hạn bởi --per-gw-radius-km"
            " hình vuông). Giúp map gọn như Viana-style. Khuyến nghị 10."
        ),
    )
    parser.add_argument(
        "--sea-mask",
        choices=("none", "dem"),
        default="dem",
        help=(
            "Loại bỏ cell vùng biển: 'dem' (mặc định, Copernicus elevation ≤ "
            "threshold) hoặc 'none'."
        ),
    )
    parser.add_argument(
        "--sea-elev-threshold-m",
        type=float,
        default=0.5,
        help="DEM elevation threshold (m) khi --sea-mask=dem. Default 0.5.",
    )
    parser.add_argument(
        "--sea-mask-dem-path",
        default="",
        help="GeoTIFF DEM cho --sea-mask=dem. Default = {LORA_DEM_DIRECTORY}/copernicus_glo30_danang.tif.",
    )
    parser.add_argument(
        "--survey-max-link-km",
        type=float,
        default=50.0,
        help=(
            "Max link distance (km) để filter survey corrupt (ETL mix-up Hải"
            " Phòng↔Đà Nẵng ~554 km). Default 50."
        ),
    )
    args = parser.parse_args()

    if args.bbox == "danang":
        lat_min, lon_min, lat_max, lon_max = BBOX_DANANG
    else:
        try:
            parts = [float(x) for x in args.bbox.split(",")]
        except ValueError:
            log.error("--bbox phải là 'danang' hoặc 'lat_min,lon_min,lat_max,lon_max'")
            return 2
        if len(parts) != 4:
            log.error("--bbox cần 4 số, got %d", len(parts))
            return 2
        lat_min, lon_min, lat_max, lon_max = parts

    dem_dir = os.environ.get("LORA_DEM_DIRECTORY")
    if not dem_dir or not Path(dem_dir).is_dir():
        log.error("LORA_DEM_DIRECTORY env không set hoặc không phải directory: %r", dem_dir)
        return 2
    # FINAL version: KHÔNG dùng DSM (DTM only) — bỏ qua LORA_SURFACE_DEM_DIRECTORY.

    center_lat = (lat_min + lat_max) / 2.0
    step_dlon, step_dlat = meters_to_degrees(center_lat, args.grid_m, args.grid_m)
    nx = math.ceil((lon_max - lon_min) / step_dlon) + 1
    ny = math.ceil((lat_max - lat_min) / step_dlat) + 1
    log.info(
        "Common grid: %d×%d cell @ %.0fm (bbox lat %.4f..%.4f, lon %.4f..%.4f)",
        nx,
        ny,
        args.grid_m,
        lat_min,
        lat_max,
        lon_min,
        lon_max,
    )

    db_url = _resolve_db_url()
    only_codes: list[str] | None = None
    if args.gateway_code:
        only_codes = [c.strip() for c in args.gateway_code.split(",") if c.strip()]
    rows = _load_gateways(db_url, only_codes)
    if not rows:
        log.error("Không tìm thấy gateway")
        return 1
    log.info("Loaded %d gateway", len(rows))

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    composite_path = out_dir / "composite.geojson"
    redundancy_path = out_dir / "redundancy.geojson"
    manifest_path = out_dir / "manifest.json"
    if composite_path.exists() and not args.force:
        log.info(
            "Output đã có: %s (dùng --force để overwrite)",
            composite_path,
        )
        return 0

    two_phase = args.grid_m < args.coarse_grid_m - 0.1
    if two_phase:
        step_dlon_c, step_dlat_c = meters_to_degrees(
            center_lat, args.coarse_grid_m, args.coarse_grid_m
        )
        nx_c = math.ceil((lon_max - lon_min) / step_dlon_c) + 1
        ny_c = math.ceil((lat_max - lat_min) / step_dlat_c) + 1
        log.info(
            "Phase A coarse grid: %d×%d cell @ %.0fm",
            nx_c,
            ny_c,
            args.coarse_grid_m,
        )
        coarse_jobs = _build_jobs(
            rows,
            lat_min,
            lon_min,
            lat_max,
            lon_max,
            step_dlat_c,
            step_dlon_c,
            nx_c,
            ny_c,
            args.coarse_grid_m,
            args.per_gw_radius_km,
            dem_dir,
            args.location_percent,
            args.smooth_px,
        )
        if not coarse_jobs:
            log.error("Phase A: không có job")
            return 1
        log.info(
            "Phase A: %d job (avg sub-grid %.0f cell)",
            len(coarse_jobs),
            sum(j.sub_ny * j.sub_nx for j in coarse_jobs) / len(coarse_jobs),
        )
        coarse_results = _run_jobs(coarse_jobs, args.workers)
        _, gw_count_coarse, dominant_coarse = _composite_results(coarse_results, ny_c, nx_c)
        n_dom = int((dominant_coarse >= 0).sum())
        log.info(
            "Phase A composite: %d/%d coarse cell có gw dominant",
            n_dom,
            ny_c * nx_c,
        )
        skip_masks = _build_skip_masks_fine(
            rows,
            dominant_coarse,
            lat_min,
            lon_min,
            lat_max,
            lon_max,
            step_dlat,
            step_dlon,
            nx,
            ny,
            step_dlat_c,
            step_dlon_c,
            ny_c,
            nx_c,
            args.per_gw_radius_km,
            args.dominance_buffer,
        )
        total_full = sum(int(m.size) for m in skip_masks.values())
        total_skip = sum(int(m.sum()) for m in skip_masks.values())
        log.info(
            "Phase B: %d gw có dominance region; skip %d/%d sub-grid cell (%.1f%%)",
            len(skip_masks),
            total_skip,
            total_full,
            100.0 * total_skip / max(total_full, 1),
        )
        fine_jobs = _build_jobs(
            rows,
            lat_min,
            lon_min,
            lat_max,
            lon_max,
            step_dlat,
            step_dlon,
            nx,
            ny,
            args.grid_m,
            args.per_gw_radius_km,
            dem_dir,
            args.location_percent,
            args.smooth_px,
            skip_masks=skip_masks,
        )
        if not fine_jobs:
            log.error("Phase B: không có job (dominance prefilter cắt sạch)")
            return 1
        log.info(
            "Phase B: %d job (avg compute %.0f cell sau prefilter)",
            len(fine_jobs),
            sum(
                (j.sub_ny * j.sub_nx) - (int(j.skip_mask.sum()) if j.skip_mask is not None else 0)
                for j in fine_jobs
            )
            / len(fine_jobs),
        )
        fine_results = _run_jobs(fine_jobs, args.workers)
        log.info("Compositing fine grid %d×%d...", ny, nx)
        composite, _, _ = _composite_results(fine_results, ny, nx)
        # gw_count fine = upsample coarse vì Phase B chỉ compute cell dominant
        # → gw_count fine không meaningful nếu lấy từ fine_results.
        gw_count = _upsample_coarse_to_fine(
            gw_count_coarse,
            lat_min,
            lon_min,
            step_dlat_c,
            step_dlon_c,
            ny_c,
            nx_c,
            step_dlat,
            step_dlon,
            ny,
            nx,
        )
        results = fine_results
    else:
        log.info("Single-phase: grid %d×%d @ %.0fm", nx, ny, args.grid_m)
        jobs = _build_jobs(
            rows,
            lat_min,
            lon_min,
            lat_max,
            lon_max,
            step_dlat,
            step_dlon,
            nx,
            ny,
            args.grid_m,
            args.per_gw_radius_km,
            dem_dir,
            args.location_percent,
            args.smooth_px,
        )
        if not jobs:
            log.error("Không có job để chạy")
            return 1
        avg_cells = sum(j.sub_ny * j.sub_nx for j in jobs) / len(jobs)
        log.info(
            "%d job sẵn sàng (per-gw radius %.0f km, sub-grid avg ~%.0f cell)",
            len(jobs),
            args.per_gw_radius_km,
            avg_cells,
        )
        results = _run_jobs(jobs, args.workers)

    # FINAL version: survey overlay LUÔN BẬT. Per-gw: gw có điểm đo → override
    # cell bằng max RSSI thực đo (filter serving_gateway_id = gw.id, d<50km
    # tránh ETL corruption). Gw không có điểm đo → no-op tự nhiên.
    log.info(
        "Loading survey points từ ts.survey_training (bbox + d<%.0fkm) để overlay per-gw...",
        args.survey_max_link_km,
    )
    pts_by_gw = _load_survey_overlay_points(
        db_url, lat_min, lon_min, lat_max, lon_max, args.survey_max_link_km
    )
    total_pts = sum(len(v) for v in pts_by_gw.values())
    log.info("Survey points loaded: %d (gw có data: %d)", total_pts, len(pts_by_gw))
    n_gw_with_data = 0
    n_gw_overlaid = 0
    sum_in_grid = 0
    sum_cells_overlaid = 0
    for r in results:
        code = str(r["code"])
        pts = pts_by_gw.get(code, [])
        if not pts:
            continue
        n_gw_with_data += 1
        iy0, ix0 = r["iy_start"], r["ix_start"]
        sub_lat_origin = lat_min + iy0 * step_dlat
        sub_lon_origin = lon_min + ix0 * step_dlon
        stats = _apply_survey_overlay(
            r["rssi_grid"],
            pts,
            sub_lat_origin,
            sub_lon_origin,
            step_dlat,
            step_dlon,
            r["sub_ny"],
            r["sub_nx"],
        )
        if stats["n_cells_overlaid"] > 0:
            n_gw_overlaid += 1
        sum_in_grid += stats["n_points_in_grid"]
        sum_cells_overlaid += stats["n_cells_overlaid"]
        log.info(
            "  [%s]: %d pts (%d in sub-grid) → %d cell override",
            code,
            len(pts),
            stats["n_points_in_grid"],
            stats["n_cells_overlaid"],
        )
    survey_overlay_meta: dict[str, Any] = {
        "enabled": True,
        "scope": "per_gw",
        "max_link_km": args.survey_max_link_km,
        "n_points": total_pts,
        "n_points_in_grid": sum_in_grid,
        "n_cells_overlaid": sum_cells_overlaid,
        "n_gw_with_data": n_gw_with_data,
        "n_gw_overlaid": n_gw_overlaid,
    }

    log.info("Compositing onto common grid %d×%d...", ny, nx)
    composite, gw_count, _ = _composite_results(results, ny, nx)

    n_covered = int(np.isfinite(composite).sum())
    log.info(
        "Composite: %d/%d cell finite (%.1f%%)",
        n_covered,
        ny * nx,
        100.0 * n_covered / max(ny * nx, 1),
    )

    sea_mask_meta: dict[str, Any] | None = None
    if args.sea_mask == "dem":
        dem_path = args.sea_mask_dem_path or str(Path(dem_dir) / "copernicus_glo30_danang.tif")
        if not Path(dem_path).is_file():
            log.error("DEM cho sea-mask không tồn tại: %s", dem_path)
            return 2
        sea_mask = _build_sea_mask_dem(
            dem_path,
            lat_min,
            lon_min,
            ny,
            nx,
            step_dlat,
            step_dlon,
            args.sea_elev_threshold_m,
        )
        sea_mask_meta = {
            "method": "dem",
            "dem_path": dem_path,
            "elev_threshold_m": args.sea_elev_threshold_m,
            "n_cells_masked": int(sea_mask.sum()),
        }
    else:
        sea_mask = None

    if sea_mask is not None:
        n_before = int(np.isfinite(composite).sum())
        composite[sea_mask] = np.nan
        gw_count[sea_mask] = 0
        n_after = int(np.isfinite(composite).sum())
        log.info(
            "Applied %s sea mask: %d cell finite → %d (%d removed)",
            args.sea_mask,
            n_before,
            n_after,
            n_before - n_after,
        )

    if args.max_radius_km > 0:
        radius_m = args.max_radius_km * 1000.0
        covered = np.zeros((ny, nx), dtype=bool)
        for r in rows:
            gw_lat = float(r["lat"])
            gw_lon = float(r["lon"])
            cos_lat = math.cos(math.radians(gw_lat))
            dlat_deg = radius_m / 111320.0
            dlon_deg = radius_m / (111320.0 * max(cos_lat, 1e-6))
            iy0 = max(0, math.floor((gw_lat - dlat_deg - lat_min) / step_dlat))
            iy1 = min(ny, math.ceil((gw_lat + dlat_deg - lat_min) / step_dlat) + 1)
            ix0 = max(0, math.floor((gw_lon - dlon_deg - lon_min) / step_dlon))
            ix1 = min(nx, math.ceil((gw_lon + dlon_deg - lon_min) / step_dlon) + 1)
            if iy1 <= iy0 or ix1 <= ix0:
                continue
            iy_arr = np.arange(iy0, iy1)
            ix_arr = np.arange(ix0, ix1)
            dy = (lat_min + iy_arr[:, None] * step_dlat - gw_lat) * 111320.0
            dx = (lon_min + ix_arr[None, :] * step_dlon - gw_lon) * 111320.0 * cos_lat
            dist = np.sqrt(dy * dy + dx * dx)
            covered[iy0:iy1, ix0:ix1] |= dist <= radius_m
        n_before = int(np.isfinite(composite).sum())
        composite[~covered] = np.nan
        gw_count[~covered] = 0
        n_after = int(np.isfinite(composite).sum())
        log.info(
            "Applied circular clip radius=%.1f km: %d cell finite → %d (%d removed)",
            args.max_radius_km,
            n_before,
            n_after,
            n_before - n_after,
        )

    if args.smooth_sigma > 0:
        log.info(
            "Applying NaN-safe Gaussian smoothing σ=%.2f cell (~%.0fm @ grid %.0fm)...",
            args.smooth_sigma,
            args.smooth_sigma * args.grid_m,
            args.grid_m,
        )
        composite = _smooth_nan_safe(composite, args.smooth_sigma)

    opening_struct = None
    if args.opening_size > 0:
        opening_struct = np.ones((args.opening_size, args.opening_size), dtype=bool)
        log.info(
            "Morphological opening enabled: kernel %dx%d cell (≈%dm wide)",
            args.opening_size,
            args.opening_size,
            args.opening_size * int(args.grid_m),
        )

    log.info("Polygonizing %d RSSI bins...", len(RSSI_BINS))
    composite_features: list[dict[str, Any]] = []
    for low, high, bin_id, label in RSSI_BINS:
        if math.isinf(high):
            mask = np.isfinite(composite) & (composite >= low)
        else:
            mask = np.isfinite(composite) & (composite >= low) & (composite < high)
        if opening_struct is not None:
            from scipy.ndimage import binary_opening

            mask = binary_opening(mask, structure=opening_struct)
        n_cells = int(mask.sum())
        polys = _polygonize_mask(mask, lon_min, lat_min, step_dlon, step_dlat)
        log.info(
            "  bin %d (%s): %d cells → %d polygon",
            bin_id,
            label,
            n_cells,
            len(polys),
        )
        if not polys:
            continue
        composite_features.append(
            {
                "type": "Feature",
                "properties": {
                    "bin": bin_id,
                    "rssi_low_dbm": (low if not math.isinf(low) else None),
                    "rssi_high_dbm": (high if not math.isinf(high) else None),
                    "label": label,
                },
                "geometry": {"type": "MultiPolygon", "coordinates": polys},
            }
        )

    log.info("Polygonizing 3 redundancy bins...")
    redundancy_features: list[dict[str, Any]] = []
    for low, high, label in GW_COUNT_BINS:
        mask = (gw_count >= low) & (gw_count <= high)
        n_cells = int(mask.sum())
        polys = _polygonize_mask(mask, lon_min, lat_min, step_dlon, step_dlat)
        log.info("  gw_count %s: %d cells → %d polygon", label, n_cells, len(polys))
        if not polys:
            continue
        redundancy_features.append(
            {
                "type": "Feature",
                "properties": {
                    "gw_count_min": low,
                    "gw_count_max": high,
                    "label": label,
                },
                "geometry": {"type": "MultiPolygon", "coordinates": polys},
            }
        )

    composite_path.write_text(
        json.dumps({"type": "FeatureCollection", "features": composite_features}),
        encoding="utf-8",
    )
    log.info(
        "Wrote %s (%d KB, %d feature)",
        composite_path,
        composite_path.stat().st_size // 1024,
        len(composite_features),
    )
    redundancy_path.write_text(
        json.dumps({"type": "FeatureCollection", "features": redundancy_features}),
        encoding="utf-8",
    )
    log.info(
        "Wrote %s (%d KB, %d feature)",
        redundancy_path,
        redundancy_path.stat().st_size // 1024,
        len(redundancy_features),
    )

    per_gw_dir = out_dir / "per_gw"
    per_gw_dir.mkdir(parents=True, exist_ok=True)
    per_gw_paths: dict[str, str] = {}
    log.info("Polygonizing per-gateway grids (%d gw)...", len(results))
    for r in results:
        code = str(r["code"])
        sub = r["rssi_grid"].astype(np.float32, copy=True)
        iy0, ix0 = r["iy_start"], r["ix_start"]
        iy1, ix1 = iy0 + r["sub_ny"], ix0 + r["sub_nx"]
        if sea_mask is not None:
            sub[sea_mask[iy0:iy1, ix0:ix1]] = np.nan
        if args.smooth_sigma > 0:
            sub = _smooth_nan_safe(sub, args.smooth_sigma)
        sub_lat_origin = lat_min + iy0 * step_dlat
        sub_lon_origin = lon_min + ix0 * step_dlon
        per_gw_features = _polygonize_rssi_grid(
            sub, sub_lon_origin, sub_lat_origin, step_dlon, step_dlat, opening_struct
        )
        per_gw_path = per_gw_dir / f"{code}.geojson"
        per_gw_path.write_text(
            json.dumps({"type": "FeatureCollection", "features": per_gw_features}),
            encoding="utf-8",
        )
        per_gw_paths[code] = f"per_gw/{code}.geojson"
        log.info(
            "  [%s]: %d feature → %s (%d KB)",
            code,
            len(per_gw_features),
            per_gw_path.name,
            per_gw_path.stat().st_size // 1024,
        )

    model_parts = [
        "ITU-R P.1812",
        "DTM",
        "per-gw NF",
        "survey overlay (per-gw)",
    ]
    manifest = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "grid_m": args.grid_m,
        "bbox": {
            "lat_min": lat_min,
            "lon_min": lon_min,
            "lat_max": lat_max,
            "lon_max": lon_max,
        },
        "grid_size": {"nx": nx, "ny": ny},
        "model": " + ".join(model_parts),
        "location_percent": args.location_percent,
        "redundancy_threshold_dbm": REDUNDANCY_THRESHOLD_DBM,
        "smooth_sigma_cell": args.smooth_sigma if args.smooth_sigma > 0 else None,
        "opening_size_cell": args.opening_size if args.opening_size > 0 else None,
        "max_radius_km": args.max_radius_km if args.max_radius_km > 0 else None,
        "sea_mask": sea_mask_meta,
        "survey_overlay": survey_overlay_meta,
        "rssi_bins": [
            {
                "bin": bid,
                "rssi_low_dbm": (low if not math.isinf(low) else None),
                "rssi_high_dbm": (high if not math.isinf(high) else None),
                "label": label,
            }
            for low, high, bid, label in RSSI_BINS
        ],
        "gw_count_bins": [
            {"gw_count_min": lo, "gw_count_max": hi, "label": lbl} for lo, hi, lbl in GW_COUNT_BINS
        ],
        "gateways": [
            {
                "code": r["code"],
                "name": r["name"],
                "lat": r["lat"],
                "lon": r["lon"],
                "noise_floor_dbm": r["noise_floor_dbm"],
                "sub_grid": {
                    "iy_start": r["iy_start"],
                    "ix_start": r["ix_start"],
                    "sub_ny": r["sub_ny"],
                    "sub_nx": r["sub_nx"],
                },
                "elapsed_s": r["elapsed_s"],
                "n_finite": r["n_finite"],
                "n_total": r["n_total"],
                "per_gw_geojson": per_gw_paths.get(str(r["code"])),
            }
            for r in sorted(results, key=lambda x: x["code"])
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log.info("Wrote manifest: %s", manifest_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
