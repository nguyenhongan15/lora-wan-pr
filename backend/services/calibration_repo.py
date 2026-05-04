"""
services/calibration_repo.py — Persistence cho path_loss_calibrations.

Phase v3.1 step 1.5.x.

Tuân thủ:
  - SOLID SRP: chỉ DB CRUD, không đụng fit logic
  - rulefordesigndatabase mục 5: soft-delete (deleted_at), không hard-delete
  - rulebackuprecovery: filters snapshot (JSONB) → re-fit từ logs
  - rulemonitoringlogging: log INFO khi save/activate/delete thành công
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.calibration_fit import CalibrationResult

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Save (history append) — KHÔNG tự auto-activate
# ─────────────────────────────────────────────────────────────────────────────

async def save_calibration(
    db: AsyncSession,
    result: CalibrationResult,
    *,
    activate: bool = True,
    correlation_id: str | None = None,
    notes: str | None = None,
) -> uuid.UUID:
    """
    Persist 1 calibration result. Mặc định activate (deactivate row cũ + set new).

    Pattern atomic 2-step:
      1. Update old active rows (same env_type) → is_active=FALSE
      2. Insert new row với is_active=:activate
    Cả 2 bước trong cùng 1 transaction (async session đã có implicit BEGIN).
    """
    cal_id = uuid.uuid4()
    env = result.filters.environment_type

    if activate:
        # Deactivate previous active calibration cho env_type này
        await db.execute(text("""
            UPDATE path_loss_calibrations
            SET is_active = FALSE
            WHERE environment_type = :env
              AND is_active = TRUE
              AND deleted_at IS NULL
        """), {"env": env})

    await db.execute(text("""
        INSERT INTO path_loss_calibrations (
            id, environment_type,
            n_path_loss_exponent, intercept_db, sigma_db,
            r_squared, rmse_db, mae_db,
            n_samples_total, n_samples_fitted, n_outliers_removed,
            distance_min_m, distance_max_m,
            measurement_filters, is_active,
            correlation_id, notes
        ) VALUES (
            :id, :env,
            :n, :intercept, :sigma,
            :r2, :rmse, :mae,
            :n_total, :n_fitted, :n_outliers,
            :d_min, :d_max,
            CAST(:filters AS jsonb), :is_active,
            :correlation_id, :notes
        )
    """), {
        "id":             cal_id,
        "env":            env,
        "n":              result.n_path_loss_exponent,
        "intercept":      result.intercept_db,
        "sigma":          result.sigma_db,
        "r2":             result.r_squared,
        "rmse":           result.rmse_db,
        "mae":            result.mae_db,
        "n_total":        result.n_samples_total,
        "n_fitted":       result.n_samples_fitted,
        "n_outliers":     result.n_outliers_removed,
        "d_min":          result.distance_min_m,
        "d_max":          result.distance_max_m,
        "filters":        json.dumps(result.filters.to_dict()),
        "is_active":      activate,
        "correlation_id": correlation_id,
        "notes":          notes,
    })
    await db.commit()

    logger.info(
        "calibration.saved",
        extra={
            "correlationId":   correlation_id,
            "calibrationId":   str(cal_id),
            "environmentType": env,
            "isActive":        activate,
            "rSquared":        round(result.r_squared, 4),
            "nSamplesFitted":  result.n_samples_fitted,
        },
    )
    return cal_id


# ─────────────────────────────────────────────────────────────────────────────
# Read — runtime lookup (gọi từ path_loss model factory)
# ─────────────────────────────────────────────────────────────────────────────

async def get_active_calibration(
    db: AsyncSession, environment_type: str,
) -> dict[str, Any] | None:
    """
    Trả calibration đang active cho 1 environment_type, hoặc None nếu chưa có.
    Dùng bởi runtime path loss model.
    """
    row = (await db.execute(text("""
        SELECT
            id::text                       AS id,
            environment_type,
            n_path_loss_exponent,
            intercept_db,
            sigma_db,
            r_squared,
            rmse_db,
            mae_db,
            n_samples_fitted,
            measurement_filters,
            created_at
        FROM path_loss_calibrations
        WHERE environment_type = :env
          AND is_active = TRUE
          AND deleted_at IS NULL
        LIMIT 1
    """), {"env": environment_type})).mappings().first()
    return dict(row) if row else None


async def get_calibration(
    db: AsyncSession, calibration_id: uuid.UUID | str,
) -> dict[str, Any] | None:
    """Lấy detail 1 calibration theo ID (kể cả không active)."""
    row = (await db.execute(text("""
        SELECT
            id::text                       AS id,
            environment_type,
            n_path_loss_exponent,
            intercept_db,
            sigma_db,
            r_squared,
            rmse_db,
            mae_db,
            n_samples_total,
            n_samples_fitted,
            n_outliers_removed,
            distance_min_m,
            distance_max_m,
            measurement_filters,
            is_active,
            correlation_id,
            notes,
            created_at,
            updated_at
        FROM path_loss_calibrations
        WHERE id = :id AND deleted_at IS NULL
    """), {"id": calibration_id})).mappings().first()
    return dict(row) if row else None


async def list_calibrations(
    db: AsyncSession,
    *,
    environment_type: str | None = None,
    only_active: bool = False,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List với optional filter env_type / active."""
    where_parts = ["deleted_at IS NULL"]
    params: dict[str, Any] = {"limit": limit}
    if environment_type:
        where_parts.append("environment_type = :env")
        params["env"] = environment_type
    if only_active:
        where_parts.append("is_active = TRUE")

    where_sql = " AND ".join(where_parts)

    rows = (await db.execute(text(f"""
        SELECT
            id::text                  AS id,
            environment_type,
            n_path_loss_exponent,
            intercept_db,
            sigma_db,
            r_squared,
            rmse_db,
            n_samples_fitted,
            is_active,
            correlation_id,
            notes,
            created_at
        FROM path_loss_calibrations
        WHERE {where_sql}
        ORDER BY created_at DESC
        LIMIT :limit
    """), params)).mappings().all()
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Activate / Soft-delete
# ─────────────────────────────────────────────────────────────────────────────

async def set_active_calibration(
    db: AsyncSession,
    calibration_id: uuid.UUID | str,
    *,
    correlation_id: str | None = None,
) -> bool:
    """
    Set 1 calibration làm active. Tự deactivate row đang active cùng env_type.
    Trả True nếu thành công, False nếu calibration_id không tồn tại.
    """
    target = await get_calibration(db, calibration_id)
    if target is None:
        return False

    env = target["environment_type"]

    await db.execute(text("""
        UPDATE path_loss_calibrations
        SET is_active = FALSE
        WHERE environment_type = :env
          AND is_active = TRUE
          AND deleted_at IS NULL
    """), {"env": env})

    await db.execute(text("""
        UPDATE path_loss_calibrations
        SET is_active = TRUE
        WHERE id = :id AND deleted_at IS NULL
    """), {"id": calibration_id})

    await db.commit()

    logger.info(
        "calibration.activated",
        extra={
            "correlationId":   correlation_id,
            "calibrationId":   str(calibration_id),
            "environmentType": env,
        },
    )
    return True


async def soft_delete_calibration(
    db: AsyncSession,
    calibration_id: uuid.UUID | str,
    *,
    correlation_id: str | None = None,
) -> bool:
    """Soft-delete: set deleted_at, đồng thời unset is_active để khỏi chiếm slot."""
    result = await db.execute(text("""
        UPDATE path_loss_calibrations
        SET deleted_at = NOW(), is_active = FALSE
        WHERE id = :id AND deleted_at IS NULL
    """), {"id": calibration_id})
    await db.commit()
    deleted = result.rowcount > 0

    logger.info(
        "calibration.soft_deleted",
        extra={
            "correlationId": correlation_id,
            "calibrationId": str(calibration_id),
            "found":         deleted,
        },
    )
    return deleted