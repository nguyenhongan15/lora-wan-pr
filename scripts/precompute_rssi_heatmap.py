"""Precompute composite RSSI heatmap cho Đà Nẵng (mode='estimate').

Cho mỗi cell 50m × 50m trong bbox Đà Nẵng, tính UL RSSI ước lượng tại mỗi
gateway (Stage 1 ITU P.1812 + DSM + per-gw noise floor + Stage 2 XGBoost
residual clip ±15 dB). Composite = max(RSSI) toàn 11 gw; overlay gw_count =
số gateway nghe được tín hiệu ≥ -130 dBm.

Output:
  - composite.geojson   : 4 dải RSSI (≥-100, -100~-110, -110~-120, -120~-140)
  - redundancy.geojson  : 3 dải gw_count (1, 2, ≥3)
  - manifest.json       : generated_at, model, bbox, gateway list

Tái sử dụng helper từ precompute_minsf.py (Stage 1 setup, contour assembly,
gateway loader). Khác min-SF:
  - Common bbox toàn Đà Nẵng (1 grid chung). Per-gw chỉ compute trong sub-bbox
    snapped vào common grid (tiết kiệm compute, stitch chính xác).
  - Apply Stage 2 XGBoost residual (joblib load 1 lần per worker, cache module).
  - Composite max + gw_count overlay.

Usage (chạy trong api-service container, đã có crc-covlib + DEM + xgboost):
    docker exec lora-wan-api bash -c "PYTHONPATH=/install/lib/python3.12/site-packages \\
        python /tmp/precompute_rssi_heatmap.py"

    # disable Stage 2 (pure physics):
    python scripts/precompute_rssi_heatmap.py --no-stage2

    # bbox custom:
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
for _p in (str(API_SRC), str(REPO_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from precompute_minsf import (  # noqa: E402
    GatewayJob,
    _assemble_polygons_with_holes,
    _compute_pl_grid,
    _load_dotenv_if_present,
    _load_gateways,
    _resolve_db_url,
    _smooth_pl_grid,
    meters_to_degrees,
)

log = logging.getLogger("precompute_rssi")

OUTPUT_DIR = REPO_ROOT / "apps" / "web-app" / "public" / "coverage" / "rssi"
DEFAULT_STAGE2_MODEL = REPO_ROOT / "services" / "ml-service" / "data" / "stage2_xgb.joblib"
STAGE2_MODEL_VERSION = "stage2-xgb-v0.6.0"

# Đà Nẵng bbox: lat 15.80..16.30, lon 107.90..108.50 (~55km × 65km).
BBOX_DANANG = (15.80, 107.90, 16.30, 108.50)

GRID_METERS_DEFAULT = 50.0
# SF cố định cho Stage 2 feature (heatmap không lặp SF). SF7..SF12 sensitivity
# chênh ~3 dB, không đổi bin RSSI 10 dB. Chọn SF10 = median khoảng.
HEATMAP_SF_DEFAULT = 10
# Empirical eval (n=1500 Đà Nẵng survey, 2026-05-31): clip ±15 dB ngắt cụt
# ~7 dB residual cần thiết ở 5–10 km → bias map −4 dB tổng, 73% diện tích "weak".
# Bỏ clip giảm RMSE 6.54→5.47 (B0) hoặc 5.22→4.02 (B0+loc%=10). Không gây spike
# vì XGBoost residual đã bounded bởi distribution training data.
RESIDUAL_CLIP_DB = float("inf")
# Ngưỡng "gateway có nghe được" cho overlay gw_count. -130 = SF12 limit + margin.
REDUNDANCY_THRESHOLD_DBM = -130.0

# 4 visible RSSI bins (low_dbm, high_dbm, bin_id, label). Cell < -140 dBm KHÔNG
# polygonize → transparent, basemap lộ ra.
RSSI_BINS: list[tuple[float, float, int, str]] = [
    (-100.0, math.inf, 1, ">= -100 dBm"),
    (-110.0, -100.0, 2, "-110 .. -100 dBm"),
    (-120.0, -110.0, 3, "-120 .. -110 dBm"),
    (-140.0, -120.0, 4, "-140 .. -120 dBm"),
]
GW_COUNT_BINS: list[tuple[int, int, str]] = [
    (1, 1, "1 gateway"),
    (2, 2, "2 gateways"),
    (3, 99, ">= 3 gateways"),
]


@dataclass(frozen=True, slots=True)
class RssiJob:
    """Per-gateway compute spec: sub-bbox snapped to common grid indices."""

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
    surface_dem_dir: str
    location_percent: float
    smooth_px: int
    stage2_model_path: str
    heatmap_sf: int


# Worker-process cache: joblib model load 1 lần, reuse cho tất cả gw trên cùng
# worker. Multiprocessing fork → child process kế thừa global, nhưng joblib có
# thể không pickle clean → lazy-load trong worker rồi cache.
_WORKER_MODEL: Any = None
_WORKER_MODEL_PATH: str = ""


def _get_worker_model(path: str) -> Any:
    global _WORKER_MODEL, _WORKER_MODEL_PATH
    if not path:
        return None
    if _WORKER_MODEL is None or _WORKER_MODEL_PATH != path:
        import joblib

        _WORKER_MODEL = joblib.load(path)
        _WORKER_MODEL_PATH = path
        log.info("worker pid=%d loaded Stage 2 model from %s", os.getpid(), path)
    return _WORKER_MODEL


def _compute_one_rssi(job: RssiJob) -> dict[str, Any]:
    """Worker: tính UL RSSI sub-grid cho 1 gateway, áp Stage 2 residual nếu có."""
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
        surface_dem_dir=job.surface_dem_dir,
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

    model = _get_worker_model(job.stage2_model_path)
    if model is not None:
        import pandas as pd

        iy_arr = np.arange(job.sub_ny, dtype=np.float64).reshape(-1, 1)
        ix_arr = np.arange(job.sub_nx, dtype=np.float64).reshape(1, -1)
        lat_grid = job.sub_lat_min + iy_arr * job.step_dlat
        lon_grid = job.sub_lon_min + ix_arr * job.step_dlon
        lat_grid_b = np.broadcast_to(lat_grid, (job.sub_ny, job.sub_nx))
        lon_grid_b = np.broadcast_to(lon_grid, (job.sub_ny, job.sub_nx))

        p1 = math.radians(job.lat)
        p2 = np.radians(lat_grid_b)
        dp = np.radians(lat_grid_b - job.lat)
        dl = np.radians(lon_grid_b - job.lon)
        a = np.sin(dp / 2.0) ** 2 + math.cos(p1) * np.cos(p2) * np.sin(dl / 2.0) ** 2
        d_km = 2.0 * 6371.0088 * np.arcsin(np.sqrt(a))

        finite_mask = np.isfinite(rssi_grid)
        n_finite = int(finite_mask.sum())
        if n_finite > 0:
            df = pd.DataFrame(
                {
                    "lat": lat_grid_b[finite_mask].astype(np.float32),
                    "lon": lon_grid_b[finite_mask].astype(np.float32),
                    "sf": np.full(n_finite, float(job.heatmap_sf), dtype=np.float32),
                    "gw_lat": np.full(n_finite, job.lat, dtype=np.float32),
                    "gw_lon": np.full(n_finite, job.lon, dtype=np.float32),
                    "distance_km": d_km[finite_mask].astype(np.float32),
                    "log_distance_km": np.log1p(d_km[finite_mask]).astype(np.float32),
                    "delta_alt_m": np.full(
                        n_finite,
                        job.altitude_m + job.antenna_height_m,
                        dtype=np.float32,
                    ),
                }
            )
            residual = model.predict(df).astype(np.float32)
            if math.isfinite(RESIDUAL_CLIP_DB):
                residual = np.clip(residual, -RESIDUAL_CLIP_DB, RESIDUAL_CLIP_DB)
                clip_str = f"clip +/-{RESIDUAL_CLIP_DB:.0f} dB"
            else:
                clip_str = "no clip"
            tmp = rssi_grid.copy()
            tmp[finite_mask] = tmp[finite_mask] + residual
            rssi_grid = tmp
            log.info(
                "[%s] Stage 2 applied: %d cell, residual range [%.2f, %.2f] dB (%s)",
                job.code,
                n_finite,
                float(residual.min()),
                float(residual.max()),
                clip_str,
            )

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


def _polygonize_mask(
    mask: np.ndarray,
    lon0: float,
    lat0: float,
    step_dlon: float,
    step_dlat: float,
) -> list[list[list[list[float]]]]:
    """Binary mask → MultiPolygon coords via marching squares + hole detection."""
    if mask.sum() == 0:
        return []
    from shapely.geometry import Polygon as ShapelyPoly
    from skimage import measure  # type: ignore[import-untyped]

    padded = np.pad(mask.astype(np.uint8), 1, mode="constant", constant_values=0)
    contours = measure.find_contours(padded.astype(float), 0.5)
    rings: list[list[list[float]]] = []
    polys: list[Any] = []
    for contour in contours:
        ring: list[list[float]] = []
        for row, col in contour:
            r = row - 1
            c = col - 1
            lon = lon0 + c * step_dlon
            lat = lat0 + r * step_dlat
            ring.append([round(lon, 6), round(lat, 6)])
        if ring and ring[0] != ring[-1]:
            ring.append(ring[0])
        if len(ring) < 4:
            continue
        rings.append(ring)
        polys.append(ShapelyPoly(ring))
    if not polys:
        return []
    return _assemble_polygons_with_holes(rings, polys)


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
        "--bbox",
        default="danang",
        help="'danang' (default) or 'lat_min,lon_min,lat_max,lon_max'",
    )
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--no-stage2",
        action="store_true",
        help="Disable Stage 2 XGBoost (pure physics RSSI from Stage 1)",
    )
    parser.add_argument(
        "--stage2-model",
        default=str(DEFAULT_STAGE2_MODEL),
        help=f"Path to joblib. Default: {DEFAULT_STAGE2_MODEL}",
    )
    parser.add_argument(
        "--heatmap-sf",
        type=int,
        default=HEATMAP_SF_DEFAULT,
        help=f"Fixed SF for Stage 2 feature (default {HEATMAP_SF_DEFAULT})",
    )
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
            " quá pessimistic, gây bias −6 dB cho heatmap composite. Min-SF map"
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
            "khả năng RSSI < -140 dBm vẫn rớt khỏi bin 4. Default 15."
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
    surface_dem_dir = os.environ.get("LORA_SURFACE_DEM_DIRECTORY", "")
    if surface_dem_dir and not Path(surface_dem_dir).is_dir():
        log.error("LORA_SURFACE_DEM_DIRECTORY set nhưng không phải directory: %r", surface_dem_dir)
        return 2
    if not surface_dem_dir:
        log.warning(
            "LORA_SURFACE_DEM_DIRECTORY chưa set — Stage 1 sẽ optimistic ~5-10 dB ở đô thị "
            "(không có DSM buildings). Set env để dùng DSM."
        )

    stage2_path = ""
    if not args.no_stage2:
        stage2_path = args.stage2_model
        if not Path(stage2_path).is_file():
            log.error("Stage 2 model không tồn tại: %s (dùng --no-stage2 để skip)", stage2_path)
            return 2
        clip_str = (
            "no clip"
            if not math.isfinite(RESIDUAL_CLIP_DB)
            else f"clip +/-{RESIDUAL_CLIP_DB:.0f} dB"
        )
        log.info("Stage 2 model: %s (%s)", stage2_path, clip_str)

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

    jobs: list[RssiJob] = []
    radius_deg_lat = args.per_gw_radius_km * 1000.0 / 111320.0
    for r in rows:
        gw_lat = float(r["lat"])
        gw_lon = float(r["lon"])
        radius_deg_lon = (
            args.per_gw_radius_km * 1000.0 / (111320.0 * math.cos(math.radians(gw_lat)))
        )
        sub_lat_lo = max(gw_lat - radius_deg_lat, lat_min)
        sub_lat_hi = min(gw_lat + radius_deg_lat, lat_max)
        sub_lon_lo = max(gw_lon - radius_deg_lon, lon_min)
        sub_lon_hi = min(gw_lon + radius_deg_lon, lon_max)
        if sub_lat_lo >= sub_lat_hi or sub_lon_lo >= sub_lon_hi:
            log.info("[%s] sub-bbox không giao common grid — skip", r["code"])
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
        jobs.append(
            RssiJob(
                code=str(r["code"]),
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
                grid_m=args.grid_m,
                dem_dir=dem_dir,
                surface_dem_dir=surface_dem_dir,
                location_percent=args.location_percent,
                smooth_px=args.smooth_px,
                stage2_model_path=stage2_path,
                heatmap_sf=args.heatmap_sf,
            )
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

    t_start = time.time()
    if args.workers <= 1 or len(jobs) <= 1:
        results = [_compute_one_rssi(j) for j in jobs]
    else:
        with mp.Pool(processes=args.workers) as pool:
            results = pool.map(_compute_one_rssi, jobs)
    log.info("All %d gateway done in %.0fs", len(results), time.time() - t_start)

    log.info("Compositing onto common grid %d×%d...", ny, nx)
    composite = np.full((ny, nx), np.nan, dtype=np.float32)
    gw_count = np.zeros((ny, nx), dtype=np.uint8)
    for r in results:
        sub = r["rssi_grid"]
        iy0, ix0 = r["iy_start"], r["ix_start"]
        iy1, ix1 = iy0 + r["sub_ny"], ix0 + r["sub_nx"]
        block = composite[iy0:iy1, ix0:ix1]
        composite[iy0:iy1, ix0:ix1] = np.fmax(block, sub)
        heard = (np.nan_to_num(sub, nan=-9999.0) >= REDUNDANCY_THRESHOLD_DBM).astype(np.uint8)
        gw_count[iy0:iy1, ix0:ix1] = gw_count[iy0:iy1, ix0:ix1] + heard

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

    log.info("Polygonizing 4 RSSI bins...")
    composite_features: list[dict[str, Any]] = []
    for low, high, bin_id, label in RSSI_BINS:
        if math.isinf(high):
            mask = np.isfinite(composite) & (composite >= low)
        else:
            mask = np.isfinite(composite) & (composite >= low) & (composite < high)
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

    model_parts = ["ITU-R P.1812", "DSM" if surface_dem_dir else "DTM-only", "per-gw NF"]
    if stage2_path:
        s2_part = "Stage2 XGBoost"
        if math.isfinite(RESIDUAL_CLIP_DB):
            s2_part += f" clip+/-{int(RESIDUAL_CLIP_DB)}dB"
        else:
            s2_part += " (no clip)"
        model_parts.append(s2_part)
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
        "stage2_model_version": STAGE2_MODEL_VERSION if stage2_path else None,
        "heatmap_sf": args.heatmap_sf,
        "location_percent": args.location_percent,
        "redundancy_threshold_dbm": REDUNDANCY_THRESHOLD_DBM,
        "sea_mask": sea_mask_meta,
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
            }
            for r in sorted(results, key=lambda x: x["code"])
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log.info("Wrote manifest: %s", manifest_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
