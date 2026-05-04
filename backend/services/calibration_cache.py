"""
services/calibration_cache.py — In-memory cache cho calibrated path loss params.

Phase v3.1 step 1.5.x.

Why cache:
  - coverage_matrix.compute_coverage_matrix() được gọi mỗi lần optimizer chạy
    → query DB mỗi lần = thừa
  - Calibration thay đổi rất hiếm (user-triggered explicit refit)
  - In-memory dict đủ; FIFO TTL 5min cho an toàn

Public API:
  - get_calibrated_params(environment_type) → dict | None  (sync, cache)
  - prefetch_all(db) → preload all active calibrations vào cache
  - invalidate(env=None) → xóa cache khi calibration changed

Tuân thủ:
  - SOLID SRP: chỉ cache, không lo fit/persist
  - rulemonitoringlogging: log DEBUG hit/miss, INFO invalidate
"""

from __future__ import annotations

import logging
import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from services import calibration_repo

logger = logging.getLogger(__name__)

_CACHE_TTL_SEC = 300.0   # 5 min — re-fetch tự động phòng case ngoài-process update


# ─── In-memory state ────────────────────────────────────────────────────────

# Format: {env_type: (params_dict, fetched_at_ts)}
# params_dict = None nghĩa là DB confirmed "không có active calibration" → cache miss
_cache: dict[str, tuple[dict[str, Any] | None, float]] = {}


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

async def get_calibrated_params(
    db: AsyncSession,
    environment_type: str,
) -> dict[str, Any] | None:
    """
    Lookup calibrated params (n, intercept, sigma) cho environment_type.

    Returns:
        dict {n, intercept_db, sigma_db, calibration_id, r_squared, ...}
        hoặc None nếu chưa có active calibration cho env này.

    Cache hit if entry < 5 min old; else fetch DB.
    """
    now = time.time()
    cached = _cache.get(environment_type)
    if cached is not None:
        params, fetched_at = cached
        if now - fetched_at < _CACHE_TTL_SEC:
            logger.debug(
                "calibration_cache.hit",
                extra={"environmentType": environment_type, "hasParams": params is not None},
            )
            return params

    # Miss / expired → fetch
    row = await calibration_repo.get_active_calibration(db, environment_type)
    params: dict[str, Any] | None = None
    if row is not None:
        params = {
            "calibration_id":       row["id"],
            "n_path_loss_exponent": float(row["n_path_loss_exponent"]),
            "intercept_db":         float(row["intercept_db"]),
            "sigma_db":             float(row["sigma_db"]),
            "r_squared":            float(row["r_squared"]),
            "n_samples_fitted":     int(row["n_samples_fitted"]),
        }

    _cache[environment_type] = (params, now)
    logger.debug(
        "calibration_cache.miss_fetched",
        extra={"environmentType": environment_type, "hasParams": params is not None},
    )
    return params


async def prefetch_all(db: AsyncSession) -> int:
    """
    Pre-load ALL active calibrations vào cache. Gọi 1 lần khi app startup
    để tránh cold cache ở request đầu tiên (production warmup).

    Returns: số entries đã cache.
    """
    rows = await calibration_repo.list_calibrations(db, only_active=True, limit=20)
    now = time.time()
    count = 0
    for row in rows:
        env = row["environment_type"]
        _cache[env] = (
            {
                "calibration_id":       row["id"],
                "n_path_loss_exponent": float(row["n_path_loss_exponent"]),
                "intercept_db":         float(row["intercept_db"]),
                "sigma_db":             float(row["sigma_db"]),
                "r_squared":            float(row["r_squared"]),
                "n_samples_fitted":     int(row["n_samples_fitted"]),
            },
            now,
        )
        count += 1
    logger.info("calibration_cache.prefetched", extra={"count": count})
    return count


def invalidate(environment_type: str | None = None) -> int:
    """
    Xóa entry trong cache. Gọi sau khi save/activate/delete calibration.
    None → xóa toàn bộ cache.
    Returns: số entries cleared.
    """
    if environment_type is None:
        n = len(_cache)
        _cache.clear()
        logger.info("calibration_cache.invalidated_all", extra={"count": n})
        return n

    if environment_type in _cache:
        del _cache[environment_type]
        logger.info(
            "calibration_cache.invalidated",
            extra={"environmentType": environment_type},
        )
        return 1
    return 0