"""
routers/calibration.py — Calibration endpoints.

Phase 6 (CSV upload): unchanged.

Phase 10 (path-loss linear regression — Phase v3.1 step 1.5.x — Option C):
  POST   /calibration/path-loss/fit/{environment_type}   (DEFAULT: activate=False)
  GET    /calibration/path-loss
  GET    /calibration/path-loss/{cal_id}
  POST   /calibration/path-loss/{cal_id}/activate         (manual gate)
  DELETE /calibration/path-loss/{cal_id}

Strategy: build framework đầy đủ, KHÔNG auto-activate sau fit (Option C).
User phải explicit POST /path-loss/{id}/activate sau khi review quality_tier.
"""

from __future__ import annotations

import logging
import uuid
from typing import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import AppError, NotFoundError, ValidationError
from core.responses import ok
from database import AsyncSessionLocal

from services.calibration import compute_metrics, parse_groundtruth_csv
from services.calibration_fit import CalibrationFilters, fit_path_loss
from services.calibration_repo import (
    get_calibration,
    list_calibrations,
    save_calibration,
    set_active_calibration,
    soft_delete_calibration,
)
from services.calibration_cache import invalidate as invalidate_calibration_cache

try:
    from core.rate_limit import rate_limit_default          # type: ignore
except ImportError:  # pragma: no cover
    def rate_limit_default(_request: Request) -> None:
        pass


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/calibration", tags=["calibration"])


MAX_CSV_BYTES = 10 * 1024 * 1024


# ─── DB dependency ──────────────────────────────────────────────────────────

async def get_db() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session


# ════════════════════════════════════════════════════════════════════════════
# Phase 6 — CSV ground-truth upload + metrics (UNCHANGED)
# ════════════════════════════════════════════════════════════════════════════

@router.post("/{campaign_id}/upload", status_code=status.HTTP_201_CREATED)
async def upload_groundtruth(
    campaign_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(..., description="CSV ground-truth (lat,lng,rssi_dbm,...)"),
    db:   AsyncSession = Depends(get_db),
):
    rate_limit_default(request)

    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise ValidationError("File phải có đuôi .csv", code="INVALID_FILE_TYPE")

    raw = await file.read()
    if len(raw) > MAX_CSV_BYTES:
        raise ValidationError(
            f"File quá lớn (> {MAX_CSV_BYTES // 1_000_000} MB)",
            code="FILE_TOO_LARGE",
        )

    campaign_row = (await db.execute(text("""
        SELECT c.id::text AS cid,
               (SELECT g.id::text
                FROM measurements m
                JOIN gateways g ON g.id = m.gateway_id
                WHERE m.campaign_id = c.id AND g.deleted_at IS NULL
                LIMIT 1) AS default_gateway_id
        FROM campaigns c
        WHERE c.id = :cid AND c.deleted_at IS NULL
    """), {"cid": str(campaign_id)})).mappings().first()

    if not campaign_row:
        raise NotFoundError(
            f"Campaign {campaign_id} không tồn tại.",
            code="CAMPAIGN_NOT_FOUND",
        )
    default_gateway_id = campaign_row["default_gateway_id"]

    try:
        rows = list(parse_groundtruth_csv(raw))
    except ValueError as e:
        raise ValidationError(str(e), code="INVALID_CSV_FORMAT")

    if not rows:
        raise ValidationError("CSV không có row hợp lệ.", code="EMPTY_CSV")

    gw_cache: dict[str, str | None] = {}
    inserted = 0
    skipped: list[dict] = []

    for r in rows:
        eui = r["gateway_eui"]
        if eui and eui not in gw_cache:
            gw = (await db.execute(text(
                "SELECT id::text FROM gateways "
                "WHERE gateway_eui = :eui AND deleted_at IS NULL"
            ), {"eui": eui})).scalar()
            gw_cache[eui] = gw

        gateway_id = gw_cache.get(eui) if eui else default_gateway_id
        if not gateway_id:
            skipped.append({"reason": "gateway_not_found", "gatewayEui": eui})
            continue

        await db.execute(text("""
            INSERT INTO measurements (
                gateway_id, campaign_id, location, rssi_dbm, snr_db,
                spreading_factor, measured_at, data_source
            ) VALUES (
                :gid::uuid, :cid::uuid,
                ST_SetSRID(ST_MakePoint(:lng, :lat), 4326),
                :rssi, :snr, :sf, :ts, 'csv_import'
            )
        """), {
            "gid":  gateway_id,
            "cid":  str(campaign_id),
            "lng":  r["lng"],
            "lat":  r["lat"],
            "rssi": r["rssi_dbm"],
            "snr":  r["snr_db"],
            "sf":   r["spreading_factor"],
            "ts":   r["measured_at"],
        })
        inserted += 1

    await db.commit()
    metrics = await _compute_campaign_metrics(db, campaign_id)

    logger.info("calibration_uploaded", extra={
        "campaign_id": str(campaign_id),
        "inserted":    inserted,
        "skipped":     len(skipped),
        "rmse_db":     metrics.get("rmseDb"),
    })

    return ok({
        "campaignId":         str(campaign_id),
        "rowsInFile":         len(rows),
        "inserted":           inserted,
        "skipped":            len(skipped),
        "skippedDetails":     skipped[:20],
        "calibrationMetrics": metrics,
    })


@router.get("/{campaign_id}/metrics")
async def get_calibration_metrics(
    campaign_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    metrics = await _compute_campaign_metrics(db, campaign_id)
    return ok({
        "campaignId": str(campaign_id),
        **metrics,
    })


async def _compute_campaign_metrics(
    db: AsyncSession,
    campaign_id: uuid.UUID,
) -> dict:
    rows = (await db.execute(text("""
        SELECT p.predicted_rssi_dbm AS pred,
               m.rssi_dbm           AS meas
        FROM ml_predictions p
        JOIN measurements   m ON m.id = p.measurement_id
        WHERE m.campaign_id = :cid
          AND m.deleted_at IS NULL
    """), {"cid": str(campaign_id)})).mappings().all()

    pairs = [(float(r["pred"]), float(r["meas"])) for r in rows]
    return compute_metrics(pairs)


# ════════════════════════════════════════════════════════════════════════════
# Phase 10 — Path-loss linear regression calibration (Option C)
# ════════════════════════════════════════════════════════════════════════════

VALID_ENVS = ("urban", "suburban", "rural", "forest", "coastal", "mountain")


@router.post("/path-loss/fit/{environment_type}")
async def fit_path_loss_calibration(
    environment_type: str,
    request: Request,
    spreading_factor: int | None = Query(
        None, ge=7, le=12,
        description="Optional: fit chỉ cho 1 SF (None = gộp tất cả)",
    ),
    activate: bool = Query(
        False,
        description="DEFAULT False (Option C): KHÔNG auto-activate. "
                    "User phải explicit POST /activate sau khi review quality_tier.",
    ),
    use_gateway_quality_filter: bool = Query(
        True,
        description="Lọc gateway có near-field + far-field + RSSI gradient",
    ),
    notes: str | None = Query(None, max_length=500),
    db: AsyncSession = Depends(get_db),
):
    """
    Fit Log-Distance path loss từ measurements thật trong DB.

    Option C strategy:
      - Luôn save vào history (audit + reproducibility)
      - Auto-active CHỈ khi: activate=True AND quality_tier='good'
      - quality_tier='medium'/'poor' → save nhưng response cảnh báo,
        user explicit POST /path-loss/{id}/activate nếu cần dùng
    """
    if environment_type not in VALID_ENVS:
        raise AppError(
            f"environment_type='{environment_type}' không hợp lệ. "
            f"Chấp nhận: {VALID_ENVS}",
            code="INVALID_ENVIRONMENT_TYPE",
            http_status=400,
        )

    cid = getattr(request.state, "request_id", None)
    filters = CalibrationFilters(
        environment_type           = environment_type,
        spreading_factor           = spreading_factor,
        use_gateway_quality_filter = use_gateway_quality_filter,
    )

    result = await fit_path_loss(db, filters, correlation_id=cid)
    if result is None:
        raise AppError(
            f"Không fit được calibration cho '{environment_type}'"
            f"{f' (SF={spreading_factor})' if spreading_factor else ''}. "
            f"Data có thể không đủ samples (min 30) hoặc fundamentally không phù hợp "
            f"physics Log-Distance (n < 0.3 hoặc > 6.0). Check log để biết chi tiết.",
            code="CALIBRATION_FIT_FAILED",
            http_status=400,
        )

    # Option C: chỉ auto-activate khi quality_tier='good' VÀ user explicit request
    should_activate = activate and result.quality_tier == "good"

    cal_id = await save_calibration(
        db, result,
        activate=should_activate,
        correlation_id=cid,
        notes=notes,
    )

    if should_activate:
        invalidate_calibration_cache(environment_type)

    detail = await get_calibration(db, cal_id)
    response_data = _calibration_row_to_dict(detail)
    response_data["qualityTier"]      = result.quality_tier
    response_data["activatedOnFit"]   = should_activate
    response_data["activationGate"]   = _gate_message(result, activate)

    return ok(data=response_data)


def _gate_message(result, requested_activate: bool) -> str:
    """Giải thích cho user vì sao auto-activate hay không (Option C semantics)."""
    if not requested_activate:
        return "User KHÔNG yêu cầu activate (default Option C)."
    if result.quality_tier == "good":
        return "Auto-activated (quality_tier='good')."
    return (
        f"NOT activated dù user request: quality_tier='{result.quality_tier}' "
        f"(R²={result.r_squared:.3f}, n={result.n_path_loss_exponent:.2f}). "
        f"Manual review + explicit POST /path-loss/{{id}}/activate nếu vẫn muốn dùng."
    )


@router.get("/path-loss")
async def list_path_loss_calibrations(
    request: Request,
    environment_type: str | None = Query(None),
    only_active:      bool       = Query(False),
    limit:            int        = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    if environment_type and environment_type not in VALID_ENVS:
        raise AppError(
            f"environment_type='{environment_type}' không hợp lệ",
            code="INVALID_ENVIRONMENT_TYPE",
            http_status=400,
        )

    rows = await list_calibrations(
        db,
        environment_type=environment_type,
        only_active=only_active,
        limit=limit,
    )
    return ok(data=[_calibration_row_to_summary(r) for r in rows])


@router.get("/path-loss/{cal_id}")
async def get_path_loss_calibration(
    cal_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    row = await get_calibration(db, cal_id)
    if row is None:
        raise NotFoundError(
            f"Không tìm thấy calibration id='{cal_id}'",
            code="CALIBRATION_NOT_FOUND",
        )
    return ok(data=_calibration_row_to_dict(row))


@router.post("/path-loss/{cal_id}/activate")
async def activate_path_loss_calibration(
    cal_id: UUID,
    request: Request,
    force: bool = Query(
        False,
        description="True = activate dù quality_tier='poor' "
                    "(user nhận trách nhiệm)",
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Set 1 calibration thành active (deactivate row active cùng env).

    Option C gate: nếu quality_tier='poor' và force=False → reject.
    User phải pass force=true để confirm dùng dù quality thấp.
    """
    cid = getattr(request.state, "request_id", None)
    detail = await get_calibration(db, cal_id)
    if detail is None:
        raise NotFoundError(
            f"Không tìm thấy calibration id='{cal_id}'",
            code="CALIBRATION_NOT_FOUND",
        )

    # Re-classify từ stored metrics (snapshot tại fit time)
    quality_tier = _infer_quality_tier(detail)

    if quality_tier == "poor" and not force:
        raise AppError(
            f"Calibration id='{cal_id}' có quality_tier='poor' "
            f"(R²={float(detail['r_squared']):.3f}, "
            f"n={float(detail['n_path_loss_exponent']):.2f}). "
            f"Pass ?force=true để activate dù quality thấp.",
            code="CALIBRATION_QUALITY_TOO_LOW",
            http_status=400,
        )

    ok_set = await set_active_calibration(db, cal_id, correlation_id=cid)
    if not ok_set:
        raise NotFoundError(
            f"Không tìm thấy calibration id='{cal_id}'",
            code="CALIBRATION_NOT_FOUND",
        )

    detail = await get_calibration(db, cal_id)
    invalidate_calibration_cache(detail["environment_type"])

    response_data = _calibration_row_to_dict(detail)
    response_data["qualityTier"] = quality_tier
    response_data["forceActivated"] = (quality_tier == "poor" and force)
    return ok(data=response_data)


@router.delete("/path-loss/{cal_id}")
async def delete_path_loss_calibration(
    cal_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    cid = getattr(request.state, "request_id", None)
    detail_before = await get_calibration(db, cal_id)
    if detail_before is None:
        raise NotFoundError(
            f"Không tìm thấy calibration id='{cal_id}'",
            code="CALIBRATION_NOT_FOUND",
        )

    deleted = await soft_delete_calibration(db, cal_id, correlation_id=cid)
    if deleted:
        invalidate_calibration_cache(detail_before["environment_type"])
    return ok(data={"id": str(cal_id), "deleted": deleted})


# ── Helpers ─────────────────────────────────────────────────────────────────

def _infer_quality_tier(row: dict) -> str:
    """Infer quality_tier từ stored metrics (cho activate endpoint)."""
    from services.calibration_fit import classify_quality_tier
    return classify_quality_tier(
        n_path_loss = float(row["n_path_loss_exponent"]),
        r_squared   = float(row["r_squared"]),
        n_samples   = int(row["n_samples_fitted"]),
    )


def _calibration_row_to_summary(row: dict) -> dict:
    return {
        "id":                row["id"],
        "environmentType":   row["environment_type"],
        "nPathLossExponent": float(row["n_path_loss_exponent"]),
        "interceptDb":       float(row["intercept_db"]),
        "sigmaDb":           float(row["sigma_db"]),
        "rSquared":          float(row["r_squared"]),
        "rmseDb":            float(row["rmse_db"]),
        "nSamplesFitted":    row["n_samples_fitted"],
        "qualityTier":       _infer_quality_tier(row),
        "isActive":          row["is_active"],
        "correlationId":     row.get("correlation_id"),
        "notes":             row.get("notes"),
        "createdAt":         row["created_at"],
    }


def _calibration_row_to_dict(row: dict) -> dict:
    return {
        "id":                  row["id"],
        "environmentType":     row["environment_type"],
        "nPathLossExponent":   float(row["n_path_loss_exponent"]),
        "interceptDb":         float(row["intercept_db"]),
        "sigmaDb":             float(row["sigma_db"]),
        "rSquared":            float(row["r_squared"]),
        "rmseDb":              float(row["rmse_db"]),
        "maeDb":               float(row["mae_db"]),
        "nSamplesTotal":       row["n_samples_total"],
        "nSamplesFitted":      row["n_samples_fitted"],
        "nOutliersRemoved":    row["n_outliers_removed"],
        "distanceMinM":        float(row["distance_min_m"]) if row.get("distance_min_m") is not None else None,
        "distanceMaxM":        float(row["distance_max_m"]) if row.get("distance_max_m") is not None else None,
        "measurementFilters":  row["measurement_filters"],
        "qualityTier":         _infer_quality_tier(row),
        "isActive":            row["is_active"],
        "correlationId":       row.get("correlation_id"),
        "notes":               row.get("notes"),
        "createdAt":           row["created_at"],
        "updatedAt":           row.get("updated_at"),
    }