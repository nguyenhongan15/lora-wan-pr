"""
services/calibration_fit.py — Fit Log-Distance path loss từ measurements thật.

Phase v3.1 step 1.5.x (Phase 10) — Production Option C:
  - Calibration framework BUILD ĐẦY ĐỦ
  - DEFAULT: not auto-active (chỉ save vào history)
  - User PHẢI explicit activate qua POST /path-loss/{id}/activate
  - Range n strict [1.6, 6.0] theo physics RF (ITU-R P.1411, Rappaport)

Pipeline:
  1. Fetch (distance, rssi, tx_power) từ measurements + gateways + campaigns
  2. Filter "good gateways" (near + far + gradient)
  3. Compute observed PL: PL = TxPower_dBm - RSSI_dBm
  4. Initial fit (raw) → residuals
  5. Outlier removal (IQR)
  6. Re-fit linear regression: PL = a + b·log10(d_m)
  7. Compute R², RMSE, MAE, sigma
  8. Validate n trong physics range; classify quality_tier

Tuân thủ:
  - Physics: ITU-R P.1411, Rappaport "Wireless Communications" Ch.4
    n typical: free space=2.0, urban LOS=2.7-3.5, urban NLOS=3.0-5.0,
               suburban=3.0-4.0, rural=2.0-3.0, indoor LOS=1.6-1.8,
               indoor multifloor=4.0-6.0
    → safe range: [1.6, 6.0]
  - SOLID SRP: pure compute, không đụng DB write
  - rulemonitoringlogging: full metrics + quality_tier trong INFO log
  - rulebackuprecovery: deterministic + filters snapshot
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from typing import Any

import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_MIN_DISTANCE_M = 50.0
DEFAULT_MAX_DISTANCE_M = 15_000.0
DEFAULT_MIN_RSSI_DBM   = -150.0
DEFAULT_MAX_RSSI_DBM   = -30.0

DEFAULT_OUTLIER_IQR_K = 1.5
MIN_SAMPLES_FOR_FIT   = 30

DEFAULT_TX_POWER_DBM_FALLBACK  = 14.0
DEFAULT_FREQUENCY_MHZ_FALLBACK = 923.0

# Gateway quality filter
GW_QUALITY_NEAR_DISTANCE_M = 500.0
GW_QUALITY_FAR_DISTANCE_M  = 2000.0
GW_QUALITY_MIN_NEAR        = 10
GW_QUALITY_MIN_FAR         = 10
GW_QUALITY_MIN_GRADIENT_DB = -10.0

# Range cho phép sau fit — ĐÚNG PHYSICS
# Reference: ITU-R P.1411-12 (2023), Rappaport (2002), IEEE 802.11n
# n < 1.6: vô lý vật lý (suy hao ít hơn free space)
# n > 6.0: gần như block (multifloor + thick walls extreme)
N_PATH_LOSS_MIN = 1.6
N_PATH_LOSS_MAX = 6.0

# Quality tier thresholds
R2_GOOD_THRESHOLD   = 0.5
R2_MEDIUM_THRESHOLD = 0.3


# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CalibrationFilters:
    """Snapshot filters for reproducibility (rulebackuprecovery)."""
    environment_type:           str
    min_distance_m:             float = DEFAULT_MIN_DISTANCE_M
    max_distance_m:             float = DEFAULT_MAX_DISTANCE_M
    min_rssi_dbm:               float = DEFAULT_MIN_RSSI_DBM
    max_rssi_dbm:               float = DEFAULT_MAX_RSSI_DBM
    outlier_method:             str   = "iqr"
    outlier_iqr_k:              float = DEFAULT_OUTLIER_IQR_K
    frequency_mhz:              float = DEFAULT_FREQUENCY_MHZ_FALLBACK
    spreading_factor:           int | None = None
    use_gateway_quality_filter: bool   = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "environmentType":          self.environment_type,
            "minDistanceM":             self.min_distance_m,
            "maxDistanceM":             self.max_distance_m,
            "minRssiDbm":               self.min_rssi_dbm,
            "maxRssiDbm":               self.max_rssi_dbm,
            "outlierMethod":            self.outlier_method,
            "outlierIqrK":              self.outlier_iqr_k,
            "frequencyMhz":             self.frequency_mhz,
            "spreadingFactor":          self.spreading_factor,
            "useGatewayQualityFilter":  self.use_gateway_quality_filter,
        }


@dataclass(frozen=True)
class CalibrationResult:
    n_path_loss_exponent: float
    intercept_db:         float
    sigma_db:             float

    r_squared:            float
    rmse_db:              float
    mae_db:               float

    n_samples_total:      int
    n_samples_fitted:     int
    n_outliers_removed:   int

    distance_min_m:       float
    distance_max_m:       float

    filters:              CalibrationFilters
    quality_tier:         str = "poor"
    fit_compute_ms:       float = 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Quality classification
# ─────────────────────────────────────────────────────────────────────────────

def classify_quality_tier(
    n_path_loss: float, r_squared: float, n_samples: int,
) -> str:
    """
    Production decision matrix (Option C):
      - 'good':   R² ≥ 0.5 AND n in [1.6, 5.5] AND samples ≥ 100  → recommend auto-active
      - 'medium': R² ≥ 0.3 AND n in [1.6, 6.0] AND samples ≥ 50   → manual review
      - 'poor':   else                                              → require force activate
    """
    if (r_squared >= R2_GOOD_THRESHOLD
            and 1.6 <= n_path_loss <= 5.5
            and n_samples >= 100):
        return "good"

    if (r_squared >= R2_MEDIUM_THRESHOLD
            and N_PATH_LOSS_MIN <= n_path_loss <= N_PATH_LOSS_MAX
            and n_samples >= 50):
        return "medium"

    return "poor"


# ─────────────────────────────────────────────────────────────────────────────
# Step 1: Fetch data (with optional gateway quality filter)
# ─────────────────────────────────────────────────────────────────────────────

async def fetch_calibration_data(
    db: AsyncSession,
    filters: CalibrationFilters,
    *,
    correlation_id: str | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Query DB → trả (distances_m, observed_pls_db) đã filter."""
    sql_quality_filter = ""
    if filters.use_gateway_quality_filter:
        sql_quality_filter = """
            AND m.gateway_id IN (
                SELECT g.id
                FROM gateways g
                JOIN measurements m2 ON m2.gateway_id = g.id
                JOIN campaigns c2    ON c2.id = m2.campaign_id
                WHERE m2.deleted_at IS NULL
                  AND g.deleted_at IS NULL AND g.location IS NOT NULL
                  AND c2.environment_type = :env
                GROUP BY g.id
                HAVING
                    COUNT(*) FILTER (
                        WHERE ST_Distance(m2.location::geography, g.location::geography)
                              < :gw_near_d
                    ) >= :gw_min_near
                AND COUNT(*) FILTER (
                        WHERE ST_Distance(m2.location::geography, g.location::geography)
                              > :gw_far_d
                    ) >= :gw_min_far
                AND (
                    AVG(m2.rssi_dbm) FILTER (
                        WHERE ST_Distance(m2.location::geography, g.location::geography)
                              > :gw_far_d
                    )
                    -
                    AVG(m2.rssi_dbm) FILTER (
                        WHERE ST_Distance(m2.location::geography, g.location::geography)
                              < :gw_near_d
                    )
                ) < :gw_min_grad
            )
        """

    sql_sf_filter = ""
    if filters.spreading_factor is not None:
        sql_sf_filter = "AND m.spreading_factor = :sf"

    rows = (await db.execute(text(f"""
        SELECT
            ST_Distance(m.location::geography, g.location::geography) AS distance_m,
            m.rssi_dbm                                                AS rssi_dbm,
            COALESCE(m.tx_power_dbm, g.tx_power_dbm, :default_tx)     AS tx_power_dbm
        FROM measurements m
        JOIN gateways  g ON g.id = m.gateway_id
        JOIN campaigns c ON c.id = m.campaign_id
        WHERE m.deleted_at IS NULL
          AND g.deleted_at IS NULL
          AND c.deleted_at IS NULL
          AND g.location  IS NOT NULL
          AND m.location  IS NOT NULL
          AND c.environment_type = :env
          AND m.rssi_dbm BETWEEN :min_rssi AND :max_rssi
          AND ST_Distance(m.location::geography, g.location::geography) BETWEEN :min_d AND :max_d
          {sql_sf_filter}
          {sql_quality_filter}
    """), {
        "env":          filters.environment_type,
        "min_rssi":     filters.min_rssi_dbm,
        "max_rssi":     filters.max_rssi_dbm,
        "min_d":        filters.min_distance_m,
        "max_d":        filters.max_distance_m,
        "sf":           filters.spreading_factor,
        "default_tx":   DEFAULT_TX_POWER_DBM_FALLBACK,
        "gw_near_d":    GW_QUALITY_NEAR_DISTANCE_M,
        "gw_far_d":     GW_QUALITY_FAR_DISTANCE_M,
        "gw_min_near":  GW_QUALITY_MIN_NEAR,
        "gw_min_far":   GW_QUALITY_MIN_FAR,
        "gw_min_grad":  GW_QUALITY_MIN_GRADIENT_DB,
    })).mappings().all()

    if not rows:
        logger.warning(
            "calibration.no_data",
            extra={
                "correlationId":           correlation_id,
                "environmentType":         filters.environment_type,
                "spreadingFactor":         filters.spreading_factor,
                "useGatewayQualityFilter": filters.use_gateway_quality_filter,
            },
        )
        return np.array([]), np.array([])

    distances = np.fromiter((float(r["distance_m"])    for r in rows),
                            dtype=np.float64, count=len(rows))
    rssis     = np.fromiter((float(r["rssi_dbm"])      for r in rows),
                            dtype=np.float64, count=len(rows))
    tx_powers = np.fromiter((float(r["tx_power_dbm"])  for r in rows),
                            dtype=np.float64, count=len(rows))

    observed_pls = tx_powers - rssis
    return distances, observed_pls


# ─────────────────────────────────────────────────────────────────────────────
# Outlier IQR
# ─────────────────────────────────────────────────────────────────────────────

def _iqr_outlier_mask(residuals: np.ndarray, k: float) -> np.ndarray:
    q1 = np.percentile(residuals, 25)
    q3 = np.percentile(residuals, 75)
    iqr = q3 - q1
    lower = q1 - k * iqr
    upper = q3 + k * iqr
    return (residuals >= lower) & (residuals <= upper)


# ─────────────────────────────────────────────────────────────────────────────
# Linear regression + metrics
# ─────────────────────────────────────────────────────────────────────────────

def _fit_linear(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    x_mean = x.mean()
    y_mean = y.mean()
    denom = ((x - x_mean) ** 2).sum()
    if denom < 1e-12:
        raise ValueError("x has zero variance; cannot fit")
    b = ((x - x_mean) * (y - y_mean)).sum() / denom
    a = y_mean - b * x_mean
    return float(a), float(b)


def _metrics(
    y_true: np.ndarray, y_pred: np.ndarray,
) -> tuple[float, float, float, float]:
    residuals = y_true - y_pred
    ss_res = float((residuals ** 2).sum())
    ss_tot = float(((y_true - y_true.mean()) ** 2).sum())
    r2     = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0
    rmse   = math.sqrt(ss_res / len(y_true))
    mae    = float(np.abs(residuals).mean())
    sigma  = float(residuals.std(ddof=1)) if len(residuals) > 1 else 0.0
    return r2, rmse, mae, sigma


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

async def fit_path_loss(
    db: AsyncSession,
    filters: CalibrationFilters,
    *,
    correlation_id: str | None = None,
) -> CalibrationResult | None:
    """
    Pipeline: fetch → outlier → fit → metrics → classify.

    Returns:
        CalibrationResult với quality_tier ∈ {'good', 'medium', 'poor'}
        None nếu:
          - n_total < MIN_SAMPLES_FOR_FIT
          - n_kept < MIN_SAMPLES_FOR_FIT (sau outlier)
          - zero variance trong distance → không fit được
          - n_path_loss out of physics range [1.6, 6.0] → data fundamentally invalid

    Note: n out of range LOG ERROR + return None (KHÔNG raise) để caller
    (router) handle gracefully.
    """
    t_start = time.perf_counter()

    distances, observed_pls = await fetch_calibration_data(
        db, filters, correlation_id=correlation_id,
    )
    n_total = len(distances)

    if n_total < MIN_SAMPLES_FOR_FIT:
        logger.warning(
            "calibration.insufficient_samples",
            extra={
                "correlationId":   correlation_id,
                "environmentType": filters.environment_type,
                "spreadingFactor": filters.spreading_factor,
                "nTotal":          n_total,
                "minRequired":     MIN_SAMPLES_FOR_FIT,
            },
        )
        return None

    log_d = np.log10(distances)

    try:
        a_raw, b_raw = _fit_linear(log_d, observed_pls)
    except ValueError:
        logger.warning(
            "calibration.zero_variance",
            extra={"correlationId": correlation_id,
                   "environmentType": filters.environment_type},
        )
        return None
    pred_raw     = a_raw + b_raw * log_d
    residual_raw = observed_pls - pred_raw

    keep_mask = _iqr_outlier_mask(residual_raw, filters.outlier_iqr_k)
    n_kept = int(keep_mask.sum())
    n_removed = n_total - n_kept

    if n_kept < MIN_SAMPLES_FOR_FIT:
        logger.warning(
            "calibration.too_many_outliers",
            extra={
                "correlationId":   correlation_id,
                "environmentType": filters.environment_type,
                "nTotal":          n_total,
                "nKept":           n_kept,
                "nRemoved":        n_removed,
            },
        )
        return None

    log_d_clean      = log_d[keep_mask]
    pl_clean         = observed_pls[keep_mask]
    distances_clean  = distances[keep_mask]
    a_fit, b_fit     = _fit_linear(log_d_clean, pl_clean)

    intercept_db         = a_fit
    n_path_loss_exponent = b_fit / 10.0

    # Validate physics range — strict per ITU-R P.1411 / Rappaport
    if not (N_PATH_LOSS_MIN <= n_path_loss_exponent <= N_PATH_LOSS_MAX):
        logger.error(
            "calibration.invalid_exponent",
            extra={
                "correlationId":     correlation_id,
                "environmentType":   filters.environment_type,
                "spreadingFactor":   filters.spreading_factor,
                "nPathLossExponent": round(n_path_loss_exponent, 3),
                "interceptDb":       round(intercept_db, 2),
                "validRange":        [N_PATH_LOSS_MIN, N_PATH_LOSS_MAX],
                "reason":            "Out of physics range — data quality issue: "
                                     "gateway location sai, ADR distorting RSSI, "
                                     "hoặc tx_power không thực tế",
            },
        )
        return None

    pred_clean = a_fit + b_fit * log_d_clean
    r2, rmse, mae, sigma = _metrics(pl_clean, pred_clean)

    quality_tier = classify_quality_tier(
        n_path_loss=n_path_loss_exponent,
        r_squared=max(0.0, r2),
        n_samples=n_kept,
    )

    fit_ms = (time.perf_counter() - t_start) * 1000

    result = CalibrationResult(
        n_path_loss_exponent = n_path_loss_exponent,
        intercept_db         = intercept_db,
        sigma_db             = sigma,
        r_squared            = max(0.0, min(1.0, r2)),
        rmse_db              = rmse,
        mae_db               = mae,
        n_samples_total      = n_total,
        n_samples_fitted     = n_kept,
        n_outliers_removed   = n_removed,
        distance_min_m       = float(distances_clean.min()),
        distance_max_m       = float(distances_clean.max()),
        filters              = filters,
        quality_tier         = quality_tier,
        fit_compute_ms       = fit_ms,
    )

    log_method = logger.info if quality_tier == "good" else logger.warning
    log_method(
        "calibration.fitted",
        extra={
            "correlationId":     correlation_id,
            "environmentType":   filters.environment_type,
            "spreadingFactor":   filters.spreading_factor,
            "qualityTier":       quality_tier,
            "nPathLossExponent": round(result.n_path_loss_exponent, 3),
            "interceptDb":       round(result.intercept_db, 2),
            "sigmaDb":           round(result.sigma_db, 2),
            "rSquared":          round(result.r_squared, 4),
            "rmseDb":            round(result.rmse_db, 2),
            "maeDb":             round(result.mae_db, 2),
            "nSamplesTotal":     n_total,
            "nSamplesFitted":    n_kept,
            "nOutliersRemoved":  n_removed,
            "distanceRangeM":    [
                round(result.distance_min_m, 1),
                round(result.distance_max_m, 1),
            ],
            "fitComputeMs":      round(fit_ms, 1),
        },
    )

    return result