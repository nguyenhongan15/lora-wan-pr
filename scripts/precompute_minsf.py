"""Precompute min-SF coverage maps per gateway (ITU-R P.1812 + P.2108 + P.2109).

Vẽ giống Figure 11 của paper "A Study on LoRa Signal Propagation Models in
Urban Environments" (ITU-R model with clutter losses). Cho mỗi gateway: sample
50 m grid trong square (2·r)×(2·r) km tâm gw với r = auto-radius từ link
budget (DL Friis - 30 dB clutter margin, cap [5, 50] km), tính path loss
P.1812 + clutter P.2108, optionally cộng BEL P.2109 (indoor), derive min-SF
(SF nhỏ nhất vẫn link 2 chiều OK), polygonize 6 band SF7..SF12, output
GeoJSON.

Mặc định location percentage = 95% (conservative: band biên siết, 95%
locations có PL ≤ giá trị tính được). Đổi xuống 50 nếu cần median lạc quan.

Một lần chạy là forever-cached: FE fetch trực tiếp file tĩnh, không qua API.

Usage:
    uv run --project services/api-service python scripts/precompute_minsf.py
    uv run --project services/api-service python scripts/precompute_minsf.py --gateway-code XYZ
    uv run --project services/api-service python scripts/precompute_minsf.py --workers 4 --grid-m 100
    uv run --project services/api-service python scripts/precompute_minsf.py --environment indoor
    uv run --project services/api-service python scripts/precompute_minsf.py --location-percent 50
    uv run --project services/api-service python scripts/precompute_minsf.py --force  # overwrite existing

Env:
    LORA_DEM_DIRECTORY          Path tới DEM (terrain) GeoTIFF tiles (bắt buộc)
    LORA_SURFACE_DEM_DIRECTORY  Path tới Surface DEM (DTM+buildings) tiles (optional)
    DATABASE_URL                Postgres URL (mặc định: lấy từ Settings)
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
for _p in (str(API_SRC),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

log = logging.getLogger("precompute_minsf")

OUTPUT_DIR = REPO_ROOT / "apps" / "web-app" / "public" / "coverage" / "minsf"

GRID_METERS_DEFAULT = 50.0
SF_LEVELS = (7, 8, 9, 10, 11, 12)

# Auto-radius parameters (link-budget driven, per-gateway).
# Friis công thức cho biết free-space distance — thực tế suburban LoRa có
# excess loss ~25-35 dB vs free-space ở edge-of-coverage (do diffraction +
# clutter). Trừ margin này để có outer bound thực tế thay vì Friis lý
# tưởng vài trăm km. Cap cứng 50 km cho gateway TX power cực cao.
_FRIIS_CLUTTER_MARGIN_DB = 30.0
_MAX_RADIUS_KM = 50.0
_MIN_RADIUS_KM = 5.0


def _auto_radius_km(tx_power_dbm: float, antenna_gain_dbi: float, freq_mhz: float) -> float:
    """Compute search radius từ DL link budget (downlink-limited).

    Downlink limiting vì device sensitivity SF12 = -134 dBm — kém UL gw
    sensitivity -137 dBm khoảng 3 dB. Budget thực dụng:

      PL_usable = tx_power + g_tx - device_sensitivity_sf12 - margin_clutter
      d_km = 10^((PL_usable - 32.45 - 20·log10(freq_mhz)) / 20)

    P.1812 + P.2108 sẽ tự kết luận no-coverage cho cell ngoài link budget
    thật; auto-radius chỉ thu nhỏ bbox search để khỏi quét vùng chắc chắn
    không liên kết được.
    """
    from lora_coverage_api.application.path_loss import DEVICE_SENSITIVITY_DBM_125KHZ

    sens = DEVICE_SENSITIVITY_DBM_125KHZ[12]
    pl_usable = tx_power_dbm + antenna_gain_dbi - sens - _FRIIS_CLUTTER_MARGIN_DB
    log_d = (pl_usable - 32.45 - 20.0 * math.log10(freq_mhz)) / 20.0
    d_km = 10.0**log_d
    return max(_MIN_RADIUS_KM, min(d_km, _MAX_RADIUS_KM))


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
    # Confidence level cho P.1812 + P.2108: 50% = median, 95% = conservative
    # ("95% locations có PL ≤ giá trị này"). Mặc định 95 → coverage map siết
    # band biên → engineer triển khai có buffer thay vì lạc quan median.
    location_percent: float = 95.0
    # P.2109 BEL probability — 0 = outdoor (skip BEL), 50 = indoor, 90 =
    # indoor_deep. Khớp _ENV_PROBABILITY_PERCENT của Stage1ItuModel.
    environment_prob_pct: float = 0.0
    environment: str = "outdoor"


def _compute_pl_grid(
    job: GatewayJob,
    nx: int,
    ny: int,
    lat_min: float,
    lon_min: float,
    step_dlat: float,
    step_dlon: float,
) -> np.ndarray:
    """Sample P.1812 path-loss + P.2108 clutter trên grid nx×ny.

    Per-cell rebuild Simulation: tốn ~4 ms/cell nhưng crc-covlib API
    GenerateReceptionAreaResults yêu cầu corners rectangular trong projected
    coordinates, không nhất quán với grid lat/lon trải đều ở vĩ độ cố định.
    Loop point-by-point đơn giản hơn và đủ nhanh khi parallelize 8 core.
    """
    from crc_covlib import simulation as covlib  # type: ignore[import-untyped]
    from crc_covlib.helper import itur_p2108  # type: ignore[import-untyped]

    pl_grid = np.full((ny, nx), np.nan, dtype=np.float32)

    # PATH_LOSS_DB intrinsic không phụ thuộc TX power, nhưng set giá trị thật
    # để code self-document — dòng "SetTransmitterPower(0.025…)" cũ gây hiểu lầm
    # là device-side EIRP. Convert dBm → Watts: EIRP_W = 10^((dBm - 30) / 10).
    eirp_dbm = job.tx_power_dbm + job.antenna_gain_dbi
    eirp_w = 10.0 ** ((eirp_dbm - 30.0) / 10.0)

    t0 = time.time()
    n_done = 0
    n_total = nx * ny

    for iy in range(ny):
        lat = lat_min + iy * step_dlat
        for ix in range(nx):
            lon = lon_min + ix * step_dlon
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
            sim.SetResultType(covlib.ResultType.PATH_LOSS_DB)
            sim.SetTerrainElevDataSamplingResolution(30)

            try:
                pl = sim.GenerateReceptionPointResult(lat, lon)
                if not math.isfinite(pl):
                    continue
                d_km = _haversine_km(job.lat, job.lon, lat, lon)
                if d_km >= 0.25:
                    clutter = itur_p2108.TerrestrialPathClutterLoss(
                        job.frequency_mhz / 1000.0, d_km, job.location_percent
                    )
                    pl = pl + clutter
                pl_grid[iy, ix] = pl
            except Exception:
                # DEM gap / non-finite → leave NaN
                pass

            n_done += 1
        if (iy + 1) % 50 == 0 or iy == ny - 1:
            elapsed = time.time() - t0
            rate = n_done / max(elapsed, 1e-3)
            eta = (n_total - n_done) / max(rate, 1e-3)
            log.info(
                "[%s] %d/%d (%.0f%%) %.0f cells/s ETA %.0fs",
                job.code,
                n_done,
                n_total,
                100.0 * n_done / n_total,
                rate,
                eta,
            )

    # ITU-R P.2109 Building Entry Loss — constant offset per-frequency, không
    # phụ thuộc khoảng cách → tính 1 lần, cộng vectorized vào cell finite.
    # Outdoor (prob_pct == 0) → skip; khớp Stage1ItuModel.predict():96-99.
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


def _derive_min_sf(pl_grid: np.ndarray, job: GatewayJob) -> np.ndarray:
    """Vectorized link-budget UL+DL per SF → min_sf (0 = no coverage)."""
    from lora_coverage_api.application.path_loss import (
        DEVICE_SENSITIVITY_DBM_125KHZ,
        GW_SENSITIVITY_DBM_125KHZ,
        NOISE_FLOOR_DBM_125KHZ,
        SF_SNR_LIMITS_DB,
    )

    # Device defaults — khớp Stage1ItuModel
    device_tx_power = 14.0
    device_tx_gain = 2.0
    device_rx_gain = 0.0

    min_sf = np.zeros(pl_grid.shape, dtype=np.uint8)
    valid = np.isfinite(pl_grid)

    # Start from highest SF (12 = most sensitive) and check downward.
    # min_sf assigned = smallest SF where link works.
    # Loop low→high; first SF that works → set min_sf.
    for sf in SF_LEVELS:
        ul_rssi = device_tx_power + device_tx_gain + job.antenna_gain_dbi - pl_grid
        ul_margin = ul_rssi - GW_SENSITIVITY_DBM_125KHZ[sf]
        ul_snr = ul_rssi - NOISE_FLOOR_DBM_125KHZ

        dl_rssi = job.tx_power_dbm + job.antenna_gain_dbi + device_rx_gain - pl_grid
        dl_margin = dl_rssi - DEVICE_SENSITIVITY_DBM_125KHZ[sf]
        dl_snr = dl_rssi - NOISE_FLOOR_DBM_125KHZ

        sf_limit = SF_SNR_LIMITS_DB[sf]
        works = (
            valid
            & (ul_margin >= 0.0)
            & (dl_margin >= 0.0)
            & (ul_snr >= sf_limit)
            & (dl_snr >= sf_limit)
        )
        # Chỉ set cho cell chưa được assign (min_sf == 0)
        assign = works & (min_sf == 0)
        min_sf[assign] = sf

    return min_sf


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _build_features(
    min_sf: np.ndarray, lon0: float, lat0: float, step_dlon: float, step_dlat: float
) -> list[dict[str, Any]]:
    """Convert min_sf grid → 6 GeoJSON features (cumulative band per SF).

    Cho mỗi SF s: polygon "SF≤s" = vùng tất cả cell có min_sf ∈ [1, s].
    Bands nested (SF12 ⊃ SF11 ⊃ ... ⊃ SF7). Thứ tự feature: SF12 trước, SF7
    sau cùng → MapLibre render SF12 ở dưới, SF7 trên cùng (hiệu ứng phân
    tầng giống Figure 11). FE cũng có fill-sort-key dự phòng nếu loader tự
    đảo thứ tự.
    """
    from skimage import measure  # type: ignore[import-untyped]

    features: list[dict[str, Any]] = []
    for s in reversed(SF_LEVELS):
        mask = ((min_sf > 0) & (min_sf <= s)).astype(np.uint8)
        if mask.sum() == 0:
            continue
        # Pad 1 px constant 0 để contour boundary luôn close
        padded = np.pad(mask, 1, mode="constant", constant_values=0)
        contours = measure.find_contours(padded.astype(float), 0.5)
        polygons: list[list[list[list[float]]]] = []
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
            if len(ring) >= 4:
                polygons.append([ring])
        if not polygons:
            continue
        features.append(
            {
                "type": "Feature",
                "properties": {"min_sf": int(s)},
                "geometry": {"type": "MultiPolygon", "coordinates": polygons},
            }
        )
    return features


def _compute_one(job: GatewayJob) -> dict[str, Any]:
    """Worker: tính toàn bộ pipeline cho 1 gateway, dump GeoJSON."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    t0 = time.time()

    dlon, dlat = meters_to_degrees(job.lat, job.radius_km * 1000.0, job.radius_km * 1000.0)
    lon_min, lon_max = job.lon - dlon, job.lon + dlon
    lat_min, lat_max = job.lat - dlat, job.lat + dlat
    step_dlon, step_dlat = meters_to_degrees(job.lat, job.grid_m, job.grid_m)
    nx = math.ceil((lon_max - lon_min) / step_dlon) + 1
    ny = math.ceil((lat_max - lat_min) / step_dlat) + 1

    log.info("[%s] start grid %d×%d (%d cells)", job.code, nx, ny, nx * ny)

    pl_grid = _compute_pl_grid(job, nx, ny, lat_min, lon_min, step_dlat, step_dlon)
    min_sf = _derive_min_sf(pl_grid, job)
    features = _build_features(min_sf, lon_min, lat_min, step_dlon, step_dlat)

    model_parts = ["ITU-R P.1812", "P.2108"]
    if job.environment_prob_pct > 0.0:
        model_parts.append("P.2109")
    fc = {
        "type": "FeatureCollection",
        "properties": {
            "gateway_code": job.code,
            "gateway_name": job.name,
            "gateway_lat": job.lat,
            "gateway_lon": job.lon,
            "grid_m": job.grid_m,
            "radius_km": job.radius_km,
            "model": " + ".join(model_parts),
            "location_percent": job.location_percent,
            "environment": job.environment,
            "bands": "min-SF (SF7..SF12), nested cumulative",
        },
        "features": features,
    }

    out = Path(job.output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(fc), encoding="utf-8")
    elapsed = time.time() - t0
    log.info("[%s] done %.0fs → %s", job.code, elapsed, out)
    return {
        "code": job.code,
        "name": job.name,
        "lat": job.lat,
        "lon": job.lon,
        "elapsed_s": round(elapsed, 1),
        "cells": int(nx * ny),
        "covered_cells": int((min_sf > 0).sum()),
        "location_percent": job.location_percent,
        "environment": job.environment,
    }


def _load_gateways(db_url: str, only_code: str | None) -> list[dict[str, Any]]:
    import psycopg

    sql = """
        SELECT code, name,
               ST_Y(location::geometry) AS lat,
               ST_X(location::geometry) AS lon,
               altitude_m, antenna_height_m, antenna_gain_dbi,
               tx_power_dbm, frequency_mhz
        FROM geo.gateways
        WHERE is_public = true
    """
    params: list[Any] = []
    if only_code:
        sql += " AND code = %s"
        params.append(only_code)
    sql += " ORDER BY code"

    # psycopg không hiểu prefix SQLAlchemy
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
    # Fallback: load Settings — fill min env to avoid validation errors khi
    # script chạy ngoài Docker (jwt_secret, fernet_keys, dem_dir đều required).
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
    cần `$env:LORA_DEM_DIRECTORY=…` thủ công. python-dotenv có sẵn (transitive
    qua pydantic-settings). Không override env đã set sẵn ngoài shell —
    người dùng vẫn có thể override bằng `$env:…` khi cần.
    """
    env_path = REPO_ROOT / ".env"
    if not env_path.is_file():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        log.warning("python-dotenv không khả dụng — skip auto-load .env")
        return
    load_dotenv(env_path, override=False)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    _load_dotenv_if_present()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--grid-m", type=float, default=GRID_METERS_DEFAULT)
    parser.add_argument(
        "--radius-km",
        type=float,
        default=None,
        help=(
            "Override per-gateway auto-radius. Mặc định auto = link-budget "
            "Friis − 30 dB clutter margin, cap [5, 50] km."
        ),
    )
    parser.add_argument("--gateway-code", default=None, help="Compute 1 gw only")
    parser.add_argument("--force", action="store_true", help="Recompute even if output exists")
    parser.add_argument(
        "--output-dir",
        default=str(OUTPUT_DIR),
        help=f"Default: {OUTPUT_DIR}",
    )
    parser.add_argument(
        "--location-percent",
        type=float,
        default=95.0,
        help=(
            "P.1812 + P.2108 location percentage. 50 = median (lạc quan), "
            "95 = conservative (band biên siết, 95%% locations có PL ≤ giá "
            "trị này). Mặc định 95."
        ),
    )
    parser.add_argument(
        "--environment",
        choices=("outdoor", "indoor", "indoor_deep"),
        default="outdoor",
        help=(
            "Receiver environment cho P.2109 BEL. outdoor → skip (default). "
            "indoor = 50%% probability (sàn 1, có cửa sổ). indoor_deep = 90%% "
            "(tầng trong, tường gạch dày)."
        ),
    )
    args = parser.parse_args()

    env_prob_pct_map = {"outdoor": 0.0, "indoor": 50.0, "indoor_deep": 90.0}
    env_prob_pct = env_prob_pct_map[args.environment]
    if not 0.0 <= args.location_percent <= 100.0:
        log.error("--location-percent ngoài [0, 100]: %.2f", args.location_percent)
        return 2

    dem_dir = os.environ.get("LORA_DEM_DIRECTORY")
    if not dem_dir or not Path(dem_dir).is_dir():
        log.error("LORA_DEM_DIRECTORY env không set hoặc không phải directory: %r", dem_dir)
        return 2
    surface_dem_dir = os.environ.get("LORA_SURFACE_DEM_DIRECTORY", "")
    if surface_dem_dir and not Path(surface_dem_dir).is_dir():
        log.error("LORA_SURFACE_DEM_DIRECTORY set nhưng không phải directory: %r", surface_dem_dir)
        return 2
    if surface_dem_dir:
        log.info("Surface DEM (DTM+buildings): %s", surface_dem_dir)
    else:
        log.info("Surface DEM không set → P.1812 dùng terrain làm surface (no buildings)")

    db_url = _resolve_db_url()
    rows = _load_gateways(db_url, args.gateway_code)
    if not rows:
        log.error("Không tìm thấy gateway (code=%r)", args.gateway_code)
        return 1
    log.info("Tìm thấy %d gateway", len(rows))

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    jobs: list[GatewayJob] = []
    skipped = 0
    for r in rows:
        out_path = out_dir / f"{r['code']}.geojson"
        if out_path.exists() and not args.force:
            log.info("[%s] skip (đã có %s, dùng --force để recompute)", r["code"], out_path.name)
            skipped += 1
            continue
        tx_power = float(r["tx_power_dbm"])
        gain = float(r["antenna_gain_dbi"])
        freq = float(r["frequency_mhz"])
        if args.radius_km is not None:
            radius_km = float(args.radius_km)
        else:
            radius_km = _auto_radius_km(tx_power, gain, freq)
            log.info(
                "[%s] auto-radius %.1f km (tx=%.1f dBm, gain=%.1f dBi, f=%.1f MHz)",
                r["code"],
                radius_km,
                tx_power,
                gain,
                freq,
            )
        jobs.append(
            GatewayJob(
                code=str(r["code"]),
                name=str(r["name"]),
                lat=float(r["lat"]),
                lon=float(r["lon"]),
                altitude_m=float(r["altitude_m"]),
                antenna_height_m=float(r["antenna_height_m"]),
                antenna_gain_dbi=gain,
                tx_power_dbm=tx_power,
                frequency_mhz=freq,
                radius_km=radius_km,
                grid_m=args.grid_m,
                dem_dir=dem_dir,
                surface_dem_dir=surface_dem_dir,
                output_path=str(out_path),
                location_percent=float(args.location_percent),
                environment_prob_pct=env_prob_pct,
                environment=str(args.environment),
            )
        )

    if not jobs:
        log.info("Không có job để chạy (%d skipped)", skipped)
        return 0

    radius_summary = (
        f"override {args.radius_km:.0f}km"
        if args.radius_km is not None
        else f"auto per-gw [{min(j.radius_km for j in jobs):.1f}..{max(j.radius_km for j in jobs):.1f}]km"
    )
    log.info(
        "Bắt đầu %d job trên %d worker (grid %dm × radius %s)",
        len(jobs),
        args.workers,
        int(args.grid_m),
        radius_summary,
    )
    t_start = time.time()
    if args.workers <= 1 or len(jobs) <= 1:
        results = [_compute_one(j) for j in jobs]
    else:
        with mp.Pool(processes=args.workers) as pool:
            results = pool.map(_compute_one, jobs)

    total = time.time() - t_start
    log.info("Hoàn tất: %d job, %.0fs (%.1f phút)", len(jobs), total, total / 60)

    # Merge với manifest cũ (nếu có) để không mất gateway từ lần chạy trước.
    manifest_path = out_dir / "manifest.json"
    existing: dict[str, dict[str, Any]] = {}
    if manifest_path.exists():
        try:
            old = json.loads(manifest_path.read_text(encoding="utf-8"))
            for gw in old.get("gateways", []):
                existing[gw["code"]] = gw
        except Exception:
            pass
    for r in results:
        existing[r["code"]] = r
    model_str = "ITU-R P.1812 + P.2108"
    if env_prob_pct > 0.0:
        model_str += " + P.2109"
    manifest = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "grid_m": args.grid_m,
        "radius_km": args.radius_km if args.radius_km is not None else "auto",
        "model": model_str,
        "location_percent": float(args.location_percent),
        "environment": str(args.environment),
        "gateways": sorted(existing.values(), key=lambda g: g["code"]),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log.info("Ghi manifest: %s (%d gateway)", manifest_path, len(manifest["gateways"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
