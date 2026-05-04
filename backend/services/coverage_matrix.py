from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, replace

import numpy as np
from scipy.sparse import csr_matrix
from scipy.spatial import cKDTree
from scipy.special import erf
from sqlalchemy.ext.asyncio import AsyncSession

from services.calibration_cache import get_calibrated_params
from services.grid import DemandCell
from services.path_loss import get_model

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

# LoRa sensitivity (dBm) cho BW=125 kHz, CR=4/5 — typical SX1276/8.
LORA_SENSITIVITY_DBM: dict[int, float] = {
    7:  -123.0,
    8:  -126.0,
    9:  -129.0,
    10: -132.0,
    11: -134.5,
    12: -137.0,
}

# Shadow fading σ (dB) theo môi trường demand cell — fallback khi không có
# calibration. Khi có calibration, sigma_db được override toàn cục từ params.
SHADOWING_SIGMA_DB: dict[str, float] = {
    "urban": 8.0,
    "rural": 6.0,
}

DEFAULT_R_MAX_M = 20_000.0
DEFAULT_MIN_COVERAGE_PROB = 0.5
_CACHE_MAX_SIZE = 10


# ─────────────────────────────────────────────────────────────────────────────
# Data classes (frozen → hashable cho cache key)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CandidatePoint:
    """Subset gateway_candidates row cần cho compute coverage."""
    id:   str
    lat:  float
    lng:  float
    cost: float


@dataclass(frozen=True)
class CoverageConfig:
    """
    Config tính path loss + coverage. Frozen → hashable cho cache key.

    Phase 10: thêm fields support calibrated model:
      - environment_type: dùng lookup calibrated params
      - calibrated_n / calibrated_intercept_db / calibrated_sigma_db:
            SNAPSHOT params từ DB tại runtime (set qua resolve_calibrated_params).
            Khi snapshot embed vào config → cache key thay đổi nếu calibration đổi
            → tự invalidate (đúng theo rulebackuprecovery).
      - calibration_id: audit trail → optimization_runs.coverage_config có ID này.
    """
    model:                str    # "log-distance" | "hata" | "calibrated"
    frequency_mhz:        float
    sf:                   int
    tx_power_dbm:         float
    tx_antenna_height_m:  float
    rx_antenna_height_m:  float
    tx_antenna_gain_dbi:  float
    rx_antenna_gain_dbi:  float
    r_max_m:              float = DEFAULT_R_MAX_M
    min_coverage_prob:    float = DEFAULT_MIN_COVERAGE_PROB

    # Phase 10 — calibration
    environment_type:        str   = "urban"
    calibration_id:          str | None  = None
    calibrated_n:            float | None = None
    calibrated_intercept_db: float | None = None
    calibrated_sigma_db:     float | None = None

    def short_hash(self) -> str:
        """8-char hash cho logging/correlation. Không dùng làm cache key."""
        return f"{abs(hash(self)) % (16 ** 8):08x}"


@dataclass
class CoverageMatrix:
    """Output: P(covered) sparse matrix + index mappings."""
    matrix:            csr_matrix
    candidate_ids:     list[str]
    demand_h3_indices: list[str]
    demand_weights:    np.ndarray
    config:            CoverageConfig
    compute_ms:        float = 0.0

    @property
    def density(self) -> float:
        n, m = self.matrix.shape
        return self.matrix.nnz / (n * m) if n * m > 0 else 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Async helper — resolve calibrated params (caller dùng trước compute)
# ─────────────────────────────────────────────────────────────────────────────

async def resolve_calibrated_params(
    db: AsyncSession,
    config: CoverageConfig,
    *,
    correlation_id: str | None = None,
) -> CoverageConfig:
    """
    Nếu config.model='calibrated', fetch params từ cache + EMBED vào config snapshot.
    Caller (router) gọi trước compute_coverage_matrix.

    Behavior:
      - model != "calibrated"           → return config gốc, không đụng DB.
      - model == "calibrated", có DB    → return new config với calibrated_* fields.
      - model == "calibrated", không DB → fallback model='hata', log warning.

    Tại sao embed snapshot vào config thay vì lookup runtime:
      1. Cache key reflect calibration → calibration đổi → recompute tự động.
      2. Audit trail: coverage_config in DB chứa calibration_id → reproduce được.
      3. Pure function compute_coverage_matrix() vẫn sync, không cần DB.
    """
    if config.model != "calibrated":
        return config

    params = await get_calibrated_params(db, config.environment_type)

    if params is None:
        logger.warning(
            "coverage_matrix.no_calibration_fallback_hata",
            extra={
                "correlationId":   correlation_id,
                "environmentType": config.environment_type,
            },
        )
        # Fallback: dùng Hata theoretical
        return replace(config, model="hata")

    return replace(
        config,
        calibration_id          = params["calibration_id"],
        calibrated_n            = params["n_path_loss_exponent"],
        calibrated_intercept_db = params["intercept_db"],
        calibrated_sigma_db     = params["sigma_db"],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers — projection + vectorized path loss
# ─────────────────────────────────────────────────────────────────────────────

def _project(
    lats: np.ndarray, lngs: np.ndarray,
    ref_lat: float,   ref_lng: float,
) -> np.ndarray:
    """Equirectangular projection tại ref → meters. Sai số <1% trong 50km."""
    cos_ref = math.cos(math.radians(ref_lat))
    x = (lngs - ref_lng) * 111_320.0 * cos_ref
    y = (lats - ref_lat) * 111_320.0
    return np.column_stack([x, y])


def _path_loss_vec(distances_m: np.ndarray, config: CoverageConfig) -> np.ndarray:
    """
    Vectorized path loss.

    Branches:
      - calibrated: PL = intercept + 10·n·log10(d) — params snapshot từ DB.
      - khác:       delegate vào services.path_loss.get_model(name) để đảm bảo
                    Simulator và Optimizer dùng CÙNG công thức (single source of
                    truth, tuân thủ DRY + SOLID DIP).

    Backward-compat: chấp nhận legacy snake_case "log_distance" do data cũ
    có thể còn lưu dạng này; normalize về canonical "log-distance".
    """
    if config.model == "calibrated":
        # Calibrated Log-Distance: PL = intercept + 10·n·log10(d/1m)
        # Snapshot params đã embed vào config qua resolve_calibrated_params.
        if config.calibrated_n is None or config.calibrated_intercept_db is None:
            raise ValueError(
                "model='calibrated' nhưng calibrated_n/intercept chưa được set; "
                "caller phải gọi resolve_calibrated_params() trước compute"
            )
        return (
            config.calibrated_intercept_db
            + 10 * config.calibrated_n * np.log10(distances_m)
        )

    # Legacy "log_distance" → canonical "log-distance" (registry path_loss.py)
    model_name = "log-distance" if config.model == "log_distance" else config.model

    pl_model = get_model(model_name)
    return pl_model.path_loss_db(
        distances_m,
        environment = config.environment_type,
        freq_mhz    = config.frequency_mhz,
        tx_height_m = config.tx_antenna_height_m,
        rx_height_m = config.rx_antenna_height_m,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Public API — compute (pure function, deterministic, sync)
# ─────────────────────────────────────────────────────────────────────────────

def compute_coverage_matrix(
    candidates: list[CandidatePoint],
    demand:     list[DemandCell],
    config:     CoverageConfig,
    *,
    correlation_id: str | None = None,
) -> CoverageMatrix:
    """
    Tính sparse coverage matrix cho 1 cấu hình.

    Deterministic: same (candidates, demand, config) → same matrix.
    Recovery = call lại function với cùng inputs.

    Phase 10: nếu config.model='calibrated', config phải đã được resolve qua
    resolve_calibrated_params() trước (calibrated_n / intercept đã set).
    """
    t_start = time.perf_counter()
    n_cand = len(candidates)
    n_dem  = len(demand)

    # Validate inputs sớm
    sensitivity = LORA_SENSITIVITY_DBM.get(config.sf)
    if sensitivity is None:
        raise ValueError(f"SF={config.sf} không hỗ trợ; chỉ chấp nhận 7-12")

    # Empty inputs → empty matrix (không error)
    if n_cand == 0 or n_dem == 0:
        logger.warning(
            "coverage_matrix.empty_input",
            extra={
                "correlationId": correlation_id,
                "configHash":    config.short_hash(),
                "nCandidates":   n_cand,
                "nDemand":       n_dem,
            },
        )
        return CoverageMatrix(
            matrix            = csr_matrix((n_cand, n_dem)),
            candidate_ids     = [c.id for c in candidates],
            demand_h3_indices = [d.h3_index for d in demand],
            demand_weights    = np.array([d.weight for d in demand]),
            config            = config,
            compute_ms        = 0.0,
        )

    logger.debug(
        "coverage_matrix.compute_started",
        extra={
            "correlationId":  correlation_id,
            "configHash":     config.short_hash(),
            "nCandidates":    n_cand,
            "nDemand":        n_dem,
            "model":          config.model,
            "calibrationId":  config.calibration_id,
            "sf":             config.sf,
            "rMaxM":          config.r_max_m,
        },
    )

    # ── Project → local meters ─────────────────────────────────────────
    cand_lat = np.fromiter((c.lat for c in candidates), dtype=np.float64)
    cand_lng = np.fromiter((c.lng for c in candidates), dtype=np.float64)
    dem_lat  = np.fromiter((d.lat for d in demand),     dtype=np.float64)
    dem_lng  = np.fromiter((d.lng for d in demand),     dtype=np.float64)

    ref_lat = (cand_lat.mean() + dem_lat.mean()) / 2
    ref_lng = (cand_lng.mean() + dem_lng.mean()) / 2
    cand_xy = _project(cand_lat, cand_lng, ref_lat, ref_lng)
    dem_xy  = _project(dem_lat,  dem_lng,  ref_lat, ref_lng)

    # ── KD-tree build + query R_max ────────────────────────────────────
    t_kdtree = time.perf_counter()
    kdtree = cKDTree(dem_xy)
    kdtree_ms = (time.perf_counter() - t_kdtree) * 1000

    t_query = time.perf_counter()
    nearby_per_cand: list[list[int]] = kdtree.query_ball_point(
        cand_xy, r=config.r_max_m,
    )
    query_ms = (time.perf_counter() - t_query) * 1000

    # ── Path loss + P(covered) per candidate, vectorized ───────────────
    t_compute = time.perf_counter()
    max_allowed_pl = (
        config.tx_power_dbm
        + config.tx_antenna_gain_dbi
        + config.rx_antenna_gain_dbi
        - sensitivity
    )

    # Sigma cho shadow fading:
    #   - calibrated → dùng calibrated_sigma_db (override toàn bộ)
    #   - else       → dùng SHADOWING_SIGMA_DB[density_class] per demand cell
    if config.model == "calibrated" and config.calibrated_sigma_db is not None:
        # Same sigma cho mọi demand → broadcast
        dem_sigmas = np.full(n_dem, config.calibrated_sigma_db, dtype=np.float64)
    else:
        dem_sigmas = np.fromiter(
            (SHADOWING_SIGMA_DB.get(d.density_class, 7.0) for d in demand),
            dtype=np.float64, count=n_dem,
        )

    rows:   list[int]   = []
    cols:   list[int]   = []
    values: list[float] = []
    sqrt2 = math.sqrt(2.0)

    for i, dem_js in enumerate(nearby_per_cand):
        if not dem_js:
            continue
        js = np.asarray(dem_js, dtype=np.int64)

        dx = dem_xy[js, 0] - cand_xy[i, 0]
        dy = dem_xy[js, 1] - cand_xy[i, 1]
        d_m = np.maximum(np.sqrt(dx * dx + dy * dy), 1.0)

        mean_pl = _path_loss_vec(d_m, config)
        sigmas  = dem_sigmas[js]
        z = (max_allowed_pl - mean_pl) / sigmas
        p_cov = 0.5 * (1.0 + erf(z / sqrt2))

        keep = p_cov >= config.min_coverage_prob
        if not keep.any():
            continue

        kept_js = js[keep]
        kept_p  = p_cov[keep]
        rows.extend([i] * kept_js.size)
        cols.extend(kept_js.tolist())
        values.extend(kept_p.tolist())

    compute_ms = (time.perf_counter() - t_compute) * 1000

    # ── Assemble sparse matrix ─────────────────────────────────────────
    t_assemble = time.perf_counter()
    matrix = csr_matrix(
        (values, (rows, cols)),
        shape=(n_cand, n_dem),
        dtype=np.float32,
    )
    assemble_ms = (time.perf_counter() - t_assemble) * 1000

    total_ms = (time.perf_counter() - t_start) * 1000

    # ── Single INFO event với full metrics (RED + custom) ──
    logger.info(
        "coverage_matrix.computed",
        extra={
            "correlationId":  correlation_id,
            "configHash":     config.short_hash(),
            "nCandidates":    n_cand,
            "nDemand":        n_dem,
            "nnz":            matrix.nnz,
            "densityPct":     round(matrix.nnz / (n_cand * n_dem) * 100, 3),
            "totalMs":        round(total_ms, 1),
            "kdtreeMs":       round(kdtree_ms, 1),
            "queryMs":        round(query_ms, 1),
            "computeMs":      round(compute_ms, 1),
            "assembleMs":     round(assemble_ms, 1),
            "model":          config.model,
            "calibrationId":  config.calibration_id,
            "sf":             config.sf,
            "frequencyMhz":   config.frequency_mhz,
            "txPowerDbm":     config.tx_power_dbm,
            "rMaxM":          config.r_max_m,
            "minCovProb":     config.min_coverage_prob,
            "envType":        config.environment_type,
        },
    )

    return CoverageMatrix(
        matrix            = matrix,
        candidate_ids     = [c.id for c in candidates],
        demand_h3_indices = [d.h3_index for d in demand],
        demand_weights    = np.fromiter(
            (d.weight for d in demand), dtype=np.float64, count=n_dem,
        ),
        config            = config,
        compute_ms        = total_ms,
    )


# ─────────────────────────────────────────────────────────────────────────────
# In-memory cache (FIFO eviction)
# ─────────────────────────────────────────────────────────────────────────────

_MATRIX_CACHE: dict[tuple, CoverageMatrix] = {}


def _cache_key(
    candidates: list[CandidatePoint],
    demand:     list[DemandCell],
    config:     CoverageConfig,
) -> tuple:
    """
    Cache key = (sorted candidate IDs, sorted demand h3, config hash).
    Config hash gồm CẢ calibrated snapshot → calibration đổi → cache miss.
    """
    cand_hash = hash(tuple(sorted(c.id        for c in candidates)))
    dem_hash  = hash(tuple(sorted(d.h3_index  for d in demand)))
    return (cand_hash, dem_hash, hash(config))


def get_or_compute_coverage_matrix(
    candidates: list[CandidatePoint],
    demand:     list[DemandCell],
    config:     CoverageConfig,
    *,
    correlation_id: str | None = None,
) -> CoverageMatrix:
    """
    Cache wrapper. FIFO eviction khi >_CACHE_MAX_SIZE entries.

    Cache key tự động invalidate khi candidate set / demand set / config thay đổi.
    Phase 10: config.calibrated_* fields được hash → calibration cập nhật →
    cache miss → recompute với params mới (đúng theo rulebackuprecovery).
    """
    key = _cache_key(candidates, demand, config)
    cached = _MATRIX_CACHE.get(key)
    if cached is not None:
        logger.debug(
            "coverage_matrix.cache_hit",
            extra={
                "correlationId": correlation_id,
                "configHash":    config.short_hash(),
            },
        )
        return cached

    matrix = compute_coverage_matrix(
        candidates, demand, config, correlation_id=correlation_id,
    )

    if len(_MATRIX_CACHE) >= _CACHE_MAX_SIZE:
        oldest_key = next(iter(_MATRIX_CACHE))
        del _MATRIX_CACHE[oldest_key]
        logger.debug(
            "coverage_matrix.cache_evicted",
            extra={"correlationId": correlation_id, "evictedSize": _CACHE_MAX_SIZE},
        )

    _MATRIX_CACHE[key] = matrix
    return matrix


def clear_cache() -> int:
    """Xóa toàn bộ cache. Returns số entries cleared."""
    count = len(_MATRIX_CACHE)
    _MATRIX_CACHE.clear()
    logger.info("coverage_matrix.cache_cleared", extra={"clearedCount": count})
    return count