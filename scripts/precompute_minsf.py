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

# ITU-R P.2108-1 §3.2 — Terrestrial path clutter loss model chỉ valid cho
# distance ≥ 0.25 km. Cell gần hơn skip clutter (pure P.1812 path loss).
_P2108_MIN_DISTANCE_KM = 0.25

# Auto-radius parameters (link-budget driven, per-gateway).
# Friis công thức cho biết free-space distance — thực tế suburban LoRa có
# excess loss ~25-35 dB vs free-space ở edge-of-coverage (do diffraction +
# clutter). Trừ margin này để có outer bound thực tế thay vì Friis lý
# tưởng vài trăm km. Cap cứng 50 km cho gateway TX power cực cao.
_FRIIS_CLUTTER_MARGIN_DB = 30.0
_MAX_RADIUS_KM = 50.0
_MIN_RADIUS_KM = 5.0


def _auto_radius_km(
    tx_power_dbm: float,
    antenna_gain_dbi: float,
    freq_mhz: float,
    margin_db: float = _FRIIS_CLUTTER_MARGIN_DB,
) -> tuple[float, bool]:
    """Compute search radius từ DL link budget (downlink-limited).

    Returns `(radius_km, capped_at_max)`. `capped=True` khi Friis tính ra
    radius vượt `_MAX_RADIUS_KM` — caller log warning để user biết có thể
    đang under-estimate excess loss (margin_db quá thấp).

    Downlink limiting vì device sensitivity SF12 = -134 dBm — kém UL gw
    sensitivity -137 dBm khoảng 3 dB. Budget thực dụng:

      PL_usable = tx_power + g_tx - device_sensitivity_sf12 - margin_db
      d_km = 10^((PL_usable - 32.45 - 20·log10(freq_mhz)) / 20)
    """
    from lora_coverage_api.application.path_loss import DEVICE_SENSITIVITY_DBM_125KHZ

    sens = DEVICE_SENSITIVITY_DBM_125KHZ[12]
    pl_usable = tx_power_dbm + antenna_gain_dbi - sens - margin_db
    log_d = (pl_usable - 32.45 - 20.0 * math.log10(freq_mhz)) / 20.0
    d_km = 10.0**log_d
    if d_km > _MAX_RADIUS_KM:
        return _MAX_RADIUS_KM, True
    if d_km < _MIN_RADIUS_KM:
        return _MIN_RADIUS_KM, False
    return d_km, False


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
    # Confidence level cho P.1812 + P.2108. Mặc định 50 = median, khớp
    # validate_stage1_itu.py để bias derive từ residual có thể apply ngược
    # về precompute không lệch tham số. Trước default 95 (conservative) gây
    # mismatch — đổi xuống 50, operator vẫn override --location-percent.
    location_percent: float = 50.0
    # P.2109 BEL probability — 0 = outdoor (skip BEL), 50 = indoor, 90 =
    # indoor_deep. Khớp _ENV_PROBABILITY_PERCENT của Stage1ItuModel.
    environment_prob_pct: float = 0.0
    environment: str = "outdoor"
    # Per-class clutter via ESA WorldCover (Radio Planner Figure 7 style):
    # set → wire vào Simulation, σ_L sẽ modulate theo class (DENSE_URBAN siết
    # band biên, OPEN_RURAL mở rộng). Rỗng = pure P.1812 single-class.
    landcover_dir: str = ""
    # Distance-binned bias file (output của validate_stage1_itu.py
    # --dump-bias-dir). Rỗng = không apply bias correction.
    bias_path: str = ""
    # Median-filter kernel size (px) trên pl_grid sau bias/BEL, trước derive
    # SF. Khử spike PL từ DSM building-receiver artifact (cell rơi vào building
    # bị penalty đột biến). 0 = disabled. Default 5 → ~500m radius khi grid 100m.
    smooth_px: int = 5
    # Per-gateway UL noise floor (dBm). None = fallback DEFAULT_NOISE_FLOOR_DBM
    # ở app layer. DL vẫn dùng NOISE_FLOOR_DBM_125KHZ thermal (~-117).
    noise_floor_dbm: float | None = None
    # Thư mục dump GeoTIFF raster min_sf (uint8, EPSG:4326). Rỗng = skip.
    # Song song với GeoJSON contour — không thay thế.
    raster_dir: str = ""


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
        trong surface elevation; cộng P.2108 nữa = double-count (xem fix
        crc_covlib_backend.py:151 + verify 2026-05-31).

    Simulation lifecycle: build **1 Simulation per gateway** (không phải per
    cell). TX coord, antenna height, freq, DEM dirs, landcover wiring đều
    fixed per gw → set ngoài 2 vòng for. Loop cell chỉ gọi
    `GenerateReceptionPointResult(lat, lon)` (RX coord là argument, không phải
    state). Tiết kiệm ~17 setter × 1.6M cell ≈ ~27M Python→C++ trip.

    `skip_mask` (optional bool ndarray shape (ny, nx)): True = bỏ qua cell
    (giữ NaN). Dùng cho Phase B của 2-phase dominance prefilter — chỉ compute
    cell nơi gateway này là dominant từ pass thô.
    """
    from crc_covlib import simulation as covlib  # type: ignore[import-untyped]
    from crc_covlib.helper import itur_p2108  # type: ignore[import-untyped]

    pl_grid = np.full((ny, nx), np.nan, dtype=np.float32)

    # PATH_LOSS_DB intrinsic không phụ thuộc TX power, nhưng set giá trị thật
    # để code self-document. Convert dBm → Watts: EIRP_W = 10^((dBm - 30) / 10).
    eirp_dbm = job.tx_power_dbm + job.antenna_gain_dbi
    eirp_w = 10.0 ** ((eirp_dbm - 30.0) / 10.0)

    # ── Per-gateway setup (chạy 1 lần) ─────────────────────────────────────
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
    # Per-class clutter (modulate σ_L theo land-cover). DSM intact — building
    # heights vẫn vào surface elevation. Helper chỉ gọi setter, không reset
    # state → an toàn move ra ngoài loop.
    if job.landcover_dir:
        from lora_coverage_api.infrastructure.itu.landcover_mapping import (
            apply_esa_worldcover_mapping,
        )

        apply_esa_worldcover_mapping(sim, job.landcover_dir)
    sim.SetResultType(covlib.ResultType.PATH_LOSS_DB)
    sim.SetTerrainElevDataSamplingResolution(30)

    # ── Per-cell loop (chỉ thay đổi RX coord) ──────────────────────────────
    t0 = time.time()
    n_done = 0
    n_finite = 0
    n_errors = 0
    n_total = nx * ny
    freq_ghz = job.frequency_mhz / 1000.0
    # P.2108 statistical clutter chỉ áp khi KHÔNG có DSM. Có DSM → P.1812 đã
    # model nhiễu xạ qua building/canopy bằng surface elevation thật → cộng
    # P.2108 = double-count (verify n=500 Đà Nẵng 2026-05-31: WITH P.2108+DSM
    # bias +26.27 dB; WITHOUT +2.66 dB). Mirror logic crc_covlib_backend.py.
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
                # crc-covlib raises khi DEM gap hoặc geometry pathological. Log
                # 3 cell đầu để debug nếu config sai; còn lại đếm vào n_errors,
                # giữ NaN. 1.6M cell → không spam log từng cái.
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

    # Distance-binned bias (survey residual khử bias trung bình theo bin
    # khoảng cách). Vectorize: load bin table 1 lần, dùng numpy.searchsorted
    # map distance → bin index → mean_residual. Cap |bias| khớp DistanceBinnedBias.
    if job.bias_path:
        bias_path = Path(job.bias_path)
        if bias_path.is_file():
            d_grid_km = _distance_grid_km(job, nx, ny, lat_min, lon_min, step_dlat, step_dlon)
            offset_grid = _bias_offset_grid(bias_path, d_grid_km)
            finite_mask = np.isfinite(pl_grid)
            pl_grid[finite_mask] += offset_grid[finite_mask].astype(np.float32)
            non_zero = int(np.count_nonzero(offset_grid))
            log.info(
                "[%s] bias applied từ %s (%d/%d cell ≠ 0, range [%.1f, %.1f] dB)",
                job.code,
                bias_path.name,
                non_zero,
                nx * ny,
                float(offset_grid.min()),
                float(offset_grid.max()),
            )
        else:
            log.warning("[%s] bias_path không tồn tại: %s — skip", job.code, bias_path)

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


def _smooth_pl_grid(pl_grid: np.ndarray, kernel_px: int) -> np.ndarray:
    """NaN-safe median filter trên PL grid.

    DSM (DTM+building) gây spike PL ở cell rơi vào tòa nhà (receiver bị
    chôn trong wall) — band SF sau cùng vỡ vụn thành patch nhỏ. Median
    filter kernel_px×kernel_px khử spike mà preserve edge band tốt hơn
    Gaussian (Gaussian bleed SF7↔SF12).

    NaN cell (no DEM) giữ nguyên NaN sau filter — thay tạm bằng median
    của finite cells để scipy.ndimage.median_filter không crash, restore
    NaN mask sau cùng.
    """
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


def _derive_min_sf(pl_grid: np.ndarray, job: GatewayJob) -> np.ndarray:
    """Vectorized link-budget UL+DL per SF → min_sf (0 = no coverage)."""
    from lora_coverage_api.application.path_loss import (
        DEFAULT_NOISE_FLOOR_DBM,
        DEVICE_SENSITIVITY_DBM_125KHZ,
        GW_SENSITIVITY_DBM_125KHZ,
        NOISE_FLOOR_DBM_125KHZ,
        SF_SNR_LIMITS_DB,
    )
    from lora_coverage_api.domain.coverage import (
        AS923_DEVICE_TX_POWER_CAP_DBM,
        DEVICE_DEFAULT_RX_GAIN_DBI,
        DEVICE_DEFAULT_TX_GAIN_DBI,
    )

    # Device defaults — single source of truth ở domain.coverage, khớp Target.
    device_tx_power = AS923_DEVICE_TX_POWER_CAP_DBM
    device_tx_gain = DEVICE_DEFAULT_TX_GAIN_DBI
    device_rx_gain = DEVICE_DEFAULT_RX_GAIN_DBI

    min_sf = np.zeros(pl_grid.shape, dtype=np.uint8)
    valid = np.isfinite(pl_grid)

    # UL NF: per-gateway nếu calibrated, else fallback ~-104 (interference
    # floor empirical). DL vẫn dùng thermal floor cho đến khi có DL telemetry.
    ul_noise_floor = (
        job.noise_floor_dbm if job.noise_floor_dbm is not None else DEFAULT_NOISE_FLOOR_DBM
    )

    # Start from highest SF (12 = most sensitive) and check downward.
    # min_sf assigned = smallest SF where link works.
    # Loop low→high; first SF that works → set min_sf.
    for sf in SF_LEVELS:
        ul_rssi = device_tx_power + device_tx_gain + job.antenna_gain_dbi - pl_grid
        ul_margin = ul_rssi - GW_SENSITIVITY_DBM_125KHZ[sf]
        ul_snr = ul_rssi - ul_noise_floor

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


def _bias_offset_grid(bias_path: Path, d_grid_km: np.ndarray) -> np.ndarray:
    """Load bias_<gw>.json và vectorize lookup theo distance grid.

    File schema: `{"bins": [{"d_min_km":..., "d_max_km":..., "mean_residual_db":...}]}`.
    Bins giả định disjoint, increasing theo d_min_km (không overlap). Cell ngoài
    range tất cả bin → clamp về bin gần nhất (extrapolate flat). Sign convention:
    offset cộng vào PL_raw = `-mean_residual_db` (khử bias).
    """
    from lora_coverage_api.application.bias.distance_binned import MAX_ABS_BIAS_DB

    raw = json.loads(bias_path.read_text(encoding="utf-8"))
    bins = raw.get("bins", [])
    if not bins:
        return np.zeros_like(d_grid_km)
    bins_sorted = sorted(bins, key=lambda b: float(b["d_min_km"]))
    d_mins = np.array([float(b["d_min_km"]) for b in bins_sorted], dtype=np.float64)
    d_maxs = np.array([float(b["d_max_km"]) for b in bins_sorted], dtype=np.float64)
    residuals = np.array([float(b["mean_residual_db"]) for b in bins_sorted], dtype=np.float64)
    # searchsorted trả index của bin có d_min <= d_km < (next bin's d_min)
    idx = np.searchsorted(d_mins, d_grid_km, side="right") - 1
    idx = np.clip(idx, 0, len(d_mins) - 1)
    residual_grid = residuals[idx]
    # Cells ngoài range của bin cuối (d > d_max_last) vẫn clamp về bin cuối — match
    # DistanceBinnedBias.residual_db behavior. Không cần xử lý riêng.
    _ = d_maxs  # giữ tham chiếu cho future overlap-check, không dùng vectorized
    residual_grid = np.clip(residual_grid, -MAX_ABS_BIAS_DB, MAX_ABS_BIAS_DB)
    return -residual_grid  # offset cộng vào PL


def _distance_grid_km(
    job: GatewayJob,
    nx: int,
    ny: int,
    lat_min: float,
    lon_min: float,
    step_dlat: float,
    step_dlon: float,
) -> np.ndarray:
    """Vectorized haversine từ gateway tới mọi cell trong grid. Trả mảng (ny, nx).

    Dùng cho bias lookup (cần distance per-cell để map vào bin). Lat/lon grid
    đều, nên compute 1 lần thay vì gọi `_haversine_km` trong vòng lặp.
    """
    iy = np.arange(ny, dtype=np.float64).reshape(-1, 1)
    ix = np.arange(nx, dtype=np.float64).reshape(1, -1)
    lats = lat_min + iy * step_dlat
    lons = lon_min + ix * step_dlon
    p1 = math.radians(job.lat)
    p2 = np.radians(lats)
    dp = np.radians(lats - job.lat)
    dl = np.radians(lons - job.lon)
    a = np.sin(dp / 2.0) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2.0) ** 2
    return 2.0 * 6371.0088 * np.arcsin(np.sqrt(a))


def _build_features(
    min_sf: np.ndarray, lon0: float, lat0: float, step_dlon: float, step_dlat: float
) -> list[dict[str, Any]]:
    """Convert min_sf grid → 6 GeoJSON features (cumulative band per SF).

    Cho mỗi SF s: polygon "SF≤s" = vùng tất cả cell có min_sf ∈ [1, s].
    Bands nested (SF12 ⊃ SF11 ⊃ ... ⊃ SF7). Thứ tự feature: SF12 trước, SF7
    sau cùng → MapLibre render SF12 ở dưới, SF7 trên cùng (hiệu ứng phân
    tầng giống Figure 11). FE cũng có fill-sort-key dự phòng nếu loader tự
    đảo thứ tự.

    Hole detection: dùng shapely.Polygon.contains để build forest contour
    (parent = ring có area nhỏ nhất chứa ring đó). Depth chẵn = outer, lẻ =
    hole của outer parent. Terrain shadow ("đảo SF12 giữa vùng SF7") sẽ
    được punch ra khỏi outer polygon thay vì bị fill SF7 sai.
    """
    from shapely.geometry import Polygon as ShapelyPoly
    from skimage import measure  # type: ignore[import-untyped]

    features: list[dict[str, Any]] = []
    for s in reversed(SF_LEVELS):
        mask = ((min_sf > 0) & (min_sf <= s)).astype(np.uint8)
        if mask.sum() == 0:
            continue
        # Pad 1 px constant 0 để contour boundary luôn close
        padded = np.pad(mask, 1, mode="constant", constant_values=0)
        contours = measure.find_contours(padded.astype(float), 0.5)

        rings: list[list[list[float]]] = []
        polys: list[ShapelyPoly] = []
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
            continue
        polygons = _assemble_polygons_with_holes(rings, polys)
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


def _assemble_polygons_with_holes(
    rings: list[list[list[float]]],
    polys: list[Any],
) -> list[list[list[list[float]]]]:
    """Build MultiPolygon coordinates với hole detection recursive.

    Containment qua `polys[j].covers(polys[i])` (polygon-in-polygon thay vì
    point-in-polygon). Point-based test fails khi outer nearly-concentric
    với inner: `outer.representative_point()` rơi vào inner → inner bị
    nhầm là parent của outer. `covers` cho phép boundary touch — an toàn
    hơn `contains` cho marching-squares output có cùng level.

    Parent của ring i = ring j có smallest area còn cover i (strictly lớn
    hơn để loại self-match). Depth = số tổ tiên; chẵn = outer ring, lẻ =
    hole của outer parent.

    Complexity: O(n²) pairwise covers. P.1812 typical <100 ring/band × 6
    band → <60k shapely calls, <1s overhead.
    """
    n = len(polys)
    parent = [-1] * n
    for i in range(n):
        best_j, best_area = -1, math.inf
        for j in range(n):
            if i == j:
                continue
            # Parent strictly lớn hơn để tránh tie-break tự match khi 2 ring
            # cùng area (degenerate, không thực tế với marching squares).
            if polys[j].area <= polys[i].area:
                continue
            if polys[j].covers(polys[i]) and polys[j].area < best_area:
                best_j, best_area = j, polys[j].area
        parent[i] = best_j

    depth = [0] * n
    for i in range(n):
        cur, d = i, 0
        while parent[cur] != -1:
            cur = parent[cur]
            d += 1
        depth[i] = d

    polygons: list[list[list[list[float]]]] = []
    for i in range(n):
        if depth[i] % 2 != 0:
            continue
        holes = [rings[k] for k in range(n) if parent[k] == i]
        polygons.append([rings[i], *holes])
    return polygons


def _dump_raster(
    min_sf: np.ndarray,
    job: GatewayJob,
    lon_min: float,
    lat_min: float,
    step_dlon: float,
    step_dlat: float,
) -> None:
    """Dump min_sf grid → GeoTIFF uint8 EPSG:4326. North-up (flip row order)."""
    import rasterio  # type: ignore[import-untyped]
    from rasterio.transform import from_origin  # type: ignore[import-untyped]

    out = Path(job.raster_dir) / f"{job.code}.tif"
    out.parent.mkdir(parents=True, exist_ok=True)
    # min_sf rows: row 0 = lat_min (south). GeoTIFF north-up → flipud.
    data = np.flipud(min_sf).astype(np.uint8)
    ny, nx = data.shape
    lat_max = lat_min + step_dlat * (ny - 1)
    transform = from_origin(lon_min, lat_max, step_dlon, step_dlat)
    with rasterio.open(
        out,
        "w",
        driver="GTiff",
        height=ny,
        width=nx,
        count=1,
        dtype="uint8",
        crs="EPSG:4326",
        transform=transform,
        compress="deflate",
        predictor=2,
        nodata=0,
    ) as dst:
        dst.write(data, 1)
    log.info("[%s] raster → %s (%d×%d uint8)", job.code, out, nx, ny)


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
    if job.smooth_px > 1:
        pl_grid = _smooth_pl_grid(pl_grid, job.smooth_px)
        log.info("[%s] PL smoothed (median kernel %dpx)", job.code, job.smooth_px)
    min_sf = _derive_min_sf(pl_grid, job)
    if job.raster_dir:
        _dump_raster(min_sf, job, lon_min, lat_min, step_dlon, step_dlat)
    features = _build_features(min_sf, lon_min, lat_min, step_dlon, step_dlat)

    # Sanity check — fail-fast thay vì dump file rỗng/vô nghĩa. 3 case
    # chắc chắn là config bug (DEM thiếu bbox, TX power sai, polygonize lỗi):
    n_total = nx * ny
    n_finite = int(np.isfinite(pl_grid).sum())
    n_covered = int((min_sf > 0).sum())
    if n_finite < 0.1 * n_total:
        raise RuntimeError(
            f"[{job.code}] chỉ {n_finite}/{n_total} cell finite (< 10%). "
            f"DEM ({job.dem_dir}) có cover bbox quanh gw không?"
        )
    if n_covered == 0:
        raise RuntimeError(
            f"[{job.code}] min_sf toàn 0 — không cell nào link được. "
            f"Check tx_power={job.tx_power_dbm} dBm, gain={job.antenna_gain_dbi} dBi, "
            f"radius={job.radius_km:.1f} km."
        )
    if not features:
        raise RuntimeError(
            f"[{job.code}] _build_features trả empty — min_sf có {n_covered} "
            f"covered cell nhưng không polygonize được (find_contours bug?)."
        )

    model_parts = ["ITU-R P.1812", "P.2108"]
    if job.environment_prob_pct > 0.0:
        model_parts.append("P.2109")
    if job.landcover_dir:
        model_parts.append("LandCover")
    if job.bias_path:
        model_parts.append("Bias")
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
            "Friis − margin clutter, cap [5, 50] km (xem --auto-radius-margin-db)."
        ),
    )
    parser.add_argument(
        "--auto-radius-margin-db",
        type=float,
        default=_FRIIS_CLUTTER_MARGIN_DB,
        help=(
            "Excess loss margin (dB) trừ vào Friis khi compute auto-radius. "
            "Default 30 = suburban LoRa typical (P.1812 + clutter ở edge). "
            "Tăng (vd 40) → radius nhỏ hơn, an toàn (ít quét vùng chắc no-cov). "
            "Giảm (vd 20) → bbox rộng hơn, nhiều cell sẽ tự fail link budget."
        ),
    )
    parser.add_argument(
        "--gateway-code",
        default=None,
        help="Filter gateway codes (single or comma-separated). Empty = all public gw.",
    )
    parser.add_argument("--force", action="store_true", help="Recompute even if output exists")
    parser.add_argument(
        "--output-dir",
        default=str(OUTPUT_DIR),
        help=f"Default: {OUTPUT_DIR}",
    )
    parser.add_argument(
        "--location-percent",
        type=float,
        default=50.0,
        help=(
            "P.1812 + P.2108 location percentage. 50 = median (default, khớp "
            "validate_stage1_itu.py để bias derive được apply lại nhất quán). "
            "95 = conservative (band biên siết). Trước default 95 → đổi 50 "
            "tránh mismatch validate vs precompute."
        ),
    )
    parser.add_argument(
        "--enable-clutter",
        action="store_true",
        help=(
            "Wire ESA WorldCover (per-class clutter, σ_L modulate theo "
            "built-up vs rural) vào Simulation. Cần --landcover-dir hoặc env "
            "LORA_LANDCOVER_DIRECTORY."
        ),
    )
    parser.add_argument(
        "--landcover-dir",
        default=None,
        help=(
            "Folder chứa ESA WorldCover GeoTIFF tiles. Mặc định lấy từ env "
            "LORA_LANDCOVER_DIRECTORY khi --enable-clutter."
        ),
    )
    parser.add_argument(
        "--enable-bias",
        action="store_true",
        help=(
            "Apply distance-binned bias từ survey residual. Tìm file "
            "bias_<gw_code>.json trong --bias-dir."
        ),
    )
    parser.add_argument(
        "--bias-dir",
        default=None,
        help=(
            "Folder chứa bias_<gw_code>.json. Mặc định = --output-dir "
            "(bias nằm cạnh geojson cùng gateway code)."
        ),
    )
    parser.add_argument(
        "--output-suffix",
        default="",
        help=(
            "Suffix chèn trước .geojson trong filename output. VD "
            "--output-suffix=.clutter → <code>.clutter.geojson. Dùng cho "
            "A/B ablation runs (baseline vs +clutter vs +clutter+bias) mà "
            "không overwrite file gốc."
        ),
    )
    parser.add_argument(
        "--smooth-px",
        type=int,
        default=5,
        help=(
            "Median filter kernel size (px) trên pl_grid sau bias/BEL trước "
            "derive SF. Khử spike từ DSM building artifact. 0 hoặc 1 = "
            "disabled. Default 5 = ~500m tại grid 100m."
        ),
    )
    parser.add_argument(
        "--raster-dir",
        default=None,
        help=(
            "Dump min_sf grid → GeoTIFF uint8 EPSG:4326 vào folder này "
            "(<code>.tif). Song song GeoJSON contour, không thay thế. "
            "0 = no-coverage, 7..12 = min SF."
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
        log.warning(
            "LORA_SURFACE_DEM_DIRECTORY không set — P.1812 sẽ dùng terrain "
            "elevation làm surface (no buildings). Min-SF sẽ optimistic ~5-10 dB "
            "so với survey ở vùng đô thị. Set env này để dùng DSM (DTM+buildings)."
        )

    landcover_dir = ""
    if args.enable_clutter:
        landcover_dir = args.landcover_dir or os.environ.get("LORA_LANDCOVER_DIRECTORY", "")
        if not landcover_dir or not Path(landcover_dir).is_dir():
            log.error(
                "--enable-clutter cần --landcover-dir hoặc env LORA_LANDCOVER_DIRECTORY: %r",
                landcover_dir,
            )
            return 2
        log.info("Per-class clutter ESA WorldCover: %s", landcover_dir)

    bias_dir: Path | None = None
    if args.enable_bias:
        bias_dir_str = args.bias_dir or args.output_dir
        bias_dir = Path(bias_dir_str)
        if not bias_dir.is_dir():
            log.error("--enable-bias cần --bias-dir tồn tại: %r", bias_dir)
            return 2
        log.info("Distance-binned bias dir: %s", bias_dir)

    db_url = _resolve_db_url()
    only_codes: list[str] | None = None
    if args.gateway_code:
        only_codes = [c.strip() for c in args.gateway_code.split(",") if c.strip()]
    rows = _load_gateways(db_url, only_codes)
    if not rows:
        log.error("Không tìm thấy gateway (code=%r)", args.gateway_code)
        return 1
    log.info("Tìm thấy %d gateway", len(rows))

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    jobs: list[GatewayJob] = []
    skipped = 0
    suffix = args.output_suffix or ""
    for r in rows:
        # Filename: <code>.geojson hoặc <code><suffix>.geojson (vd .clutter).
        # Suffix bắt đầu bằng "." để parse rõ hơn; nếu user quên thì tự thêm.
        if suffix and not suffix.startswith("."):
            suffix = "." + suffix
        out_path = out_dir / f"{r['code']}{suffix}.geojson"
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
            radius_km, capped = _auto_radius_km(tx_power, gain, freq, args.auto_radius_margin_db)
            if capped:
                log.warning(
                    "[%s] auto-radius cap %.1f km (Friis tính lớn hơn %.0f km). "
                    "Tăng --auto-radius-margin-db để siết, hoặc --radius-km override.",
                    r["code"],
                    radius_km,
                    _MAX_RADIUS_KM,
                )
            else:
                log.info(
                    "[%s] auto-radius %.1f km (tx=%.1f dBm, gain=%.1f dBi, f=%.1f MHz, margin=%.0f dB)",
                    r["code"],
                    radius_km,
                    tx_power,
                    gain,
                    freq,
                    args.auto_radius_margin_db,
                )
        bias_path_str = ""
        if bias_dir is not None:
            cand = bias_dir / f"bias_{r['code']}.json"
            if cand.is_file():
                bias_path_str = str(cand)
            else:
                log.warning(
                    "[%s] --enable-bias nhưng không tìm thấy %s — chạy không bias",
                    r["code"],
                    cand.name,
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
                landcover_dir=landcover_dir,
                bias_path=bias_path_str,
                smooth_px=int(args.smooth_px),
                noise_floor_dbm=(
                    float(r["noise_floor_dbm"]) if r.get("noise_floor_dbm") is not None else None
                ),
                raster_dir=str(args.raster_dir) if args.raster_dir else "",
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
        except (json.JSONDecodeError, OSError, KeyError, TypeError) as exc:
            log.warning(
                "Manifest cũ %s không đọc được (%s) — bắt đầu từ trống, "
                "entry gateway lần chạy trước sẽ mất.",
                manifest_path,
                exc,
            )
    for r in results:
        existing[r["code"]] = r
    model_str = "ITU-R P.1812 + P.2108"
    if env_prob_pct > 0.0:
        model_str += " + P.2109"
    if args.enable_clutter:
        model_str += " + LandCover"
    if args.enable_bias:
        model_str += " + Bias"
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
