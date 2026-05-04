"""
routers/predict.py — ML + interpolation endpoints.

Router siêu gọn theo SOLID SRP:
  - Nhận request + validate (Pydantic)
  - Gọi service layer (services/*)
  - Trả response wrapper {success, data}

Endpoints (mount dưới /api/v1):
  POST   /predict/train/{campaign_id}   → train XGB / RF / GP
  POST   /predict/run/{campaign_id}     → IDW | Kriging | ML predict
  GET    /predict/grid/{campaign_id}    → GeoJSON prediction grid
  GET    /predict/status/{campaign_id}  → trạng thái grid
  GET    /predict/models                → list model đã train
  DELETE /predict/models/{model_id}     → xoá model
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import NotFoundError, ValidationError
from core.rate_limit import rate_limit_default, rate_limit_train
from core.responses import ok
from database import get_db
from schemas import RunRequest, TrainRequest
from services.interpolation import interpolate
from services.measurement_repo import (
    fetch_all_gateways_for_campaign,
    fetch_measurement_points,
    fetch_training_rows,
)
from services.ml_inference import infer_on_grid
from services.ml_training import train_from_rows
from services.prediction_store import persist_trained_model, save_prediction_grid
from services.grid import bbox_with_padding, make_grid

import numpy as np

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/predict", tags=["predict"])

ML_ALGOS      = {"xgboost", "random_forest", "gaussian_process"}
INTERP_ALGOS  = {"idw", "kriging", "rbf", "delaunay"}


# ─────────────────────────────────────────────────────────────────────────────
# POST /predict/train/{campaign_id}
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/train/{campaign_id}", status_code=status.HTTP_201_CREATED)
async def train_model(
    campaign_id: uuid.UUID,
    body:        TrainRequest,
    request:     Request,
    db:          AsyncSession = Depends(get_db),
):
    """Train model và trả về model_id để dùng trong /predict/run."""
    rate_limit_train(request)
    t0 = datetime.now(timezone.utc)

    rows = await fetch_training_rows(db, campaign_id, default_sf=body.spreading_factor or 9)

    if len(rows) < body.min_measurements:
        raise ValidationError(
            f"Chỉ có {len(rows)} điểm đo, cần ít nhất {body.min_measurements}.",
            code="INSUFFICIENT_DATA",
        )

    if body.freq_mhz:
        for r in rows:
            r["freq_mhz"] = body.freq_mhz

    # CPU-bound → thread pool để không block event loop
    loop   = asyncio.get_running_loop()
    bundle = await loop.run_in_executor(
        None,
        lambda: train_from_rows(
            rows,
            algorithm=body.algorithm,
            hyperparameters=body.hyperparameters,
            n_cv_splits=body.n_cv_splits,
        ),
    )

    await persist_trained_model(
        db,
        model_id=bundle.model_id,
        algorithm=bundle.algorithm,
        campaign_id=campaign_id,
        metrics=bundle.metrics,
        hyperparameters=bundle.hyperparameters,
        feature_importance=bundle.feature_importance,
    )

    duration = (datetime.now(timezone.utc) - t0).total_seconds()
    return ok({
        "modelId":           bundle.model_id,
        "algorithm":         bundle.algorithm,
        "nSamples":          len(rows),
        "metrics":           bundle.metrics,
        "featureImportance": bundle.feature_importance,
        "trainedAt":         bundle.trained_at,
        "durationSec":       round(duration, 2),
        "message": (
            f"Train xong {body.algorithm.upper()} trên {len(rows)} điểm. "
            f"RMSE={bundle.metrics.get('rmse_db', 0):.2f} dB, "
            f"R²={bundle.metrics.get('r2_score', 0):.4f}."
        ),
    })


# ─────────────────────────────────────────────────────────────────────────────
# POST /predict/run/{campaign_id}
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/run/{campaign_id}", status_code=status.HTTP_201_CREATED)
async def run_prediction(
    campaign_id: uuid.UUID,
    body:        RunRequest,
    request:     Request,
    db:          AsyncSession = Depends(get_db),
):
    """Chạy IDW/Kriging/ML predict → lưu vào prediction_grid."""
    rate_limit_default(request)
    t0 = datetime.now(timezone.utc)

    if body.algorithm in ML_ALGOS and not body.ml_model_id:
        raise ValidationError(
            "Khi dùng XGBoost/RF/GP phải truyền mlModelId (lấy từ POST /predict/train).",
            code="MISSING_MODEL_ID",
        )

    if body.algorithm not in INTERP_ALGOS and body.algorithm not in ML_ALGOS:
        raise ValidationError(
            f"algorithm '{body.algorithm}' không hợp lệ. "
            f"Interpolation: {sorted(INTERP_ALGOS)}. ML: {sorted(ML_ALGOS)}.",
            code="UNKNOWN_ALGORITHM",
        )

    rows = await fetch_measurement_points(db, campaign_id)

    if len(rows) < body.min_measurements:
        raise ValidationError(
            f"Campaign chỉ có {len(rows)} điểm, cần ít nhất {body.min_measurements}.",
            code="INSUFFICIENT_DATA",
        )

    lats  = [r["lat"]      for r in rows]
    lngs  = [r["lng"]      for r in rows]
    rssis = [r["rssi_dbm"] for r in rows]
    loop  = asyncio.get_running_loop()

    # ── IDW / Kriging / RBF / Delaunay ──────────────────────────────────────
    if body.algorithm in INTERP_ALGOS:
        grid_lats, grid_lngs, predicted, uncertainty = await loop.run_in_executor(
            None,
            lambda: interpolate(
                lats, lngs, rssis,
                method=body.algorithm,
                resolution_m=body.grid_resolution_m,
                idw_power=body.idw_power,
                idw_neighbors=body.idw_neighbors,
                kriging_model=body.kriging_model,
                rbf_function=body.rbf_function,
                rbf_smoothing=body.rbf_smoothing,
                rbf_anchoring=body.rbf_anchoring,
                delaunay_method=body.delaunay_method,
                delaunay_fill=body.delaunay_fill,
            ),
        )
    # ── ML predict ──────────────────────────────────────────────────────────
    else:
        gws = await fetch_all_gateways_for_campaign(db, campaign_id)
        if not gws:
            raise NotFoundError("Không tìm thấy gateway cho campaign này.", code="GATEWAY_NOT_FOUND")

        arr_lat = np.asarray(lats, dtype=float)
        arr_lng = np.asarray(lngs, dtype=float)
        la_min, la_max, lo_min, lo_max = bbox_with_padding(arr_lat, arr_lng)
        grid_lats, grid_lngs = make_grid(la_min, la_max, lo_min, lo_max, body.grid_resolution_m)

        campaign_defaults = {
            "spreading_factor": 9,
            "freq_mhz":         868.0,
            "building_density": 0.3,
            "land_use":         "rural",
        }

        predicted, uncertainty = await loop.run_in_executor(
            None,
            lambda: infer_on_grid(
                body.ml_model_id, grid_lats, grid_lngs, gws, campaign_defaults,
            ),
        )

    # ── Persist ─────────────────────────────────────────────────────────────
    model_db_id = await save_prediction_grid(
        db,
        campaign_id=campaign_id,
        algorithm=body.algorithm,
        grid_lats=grid_lats,
        grid_lngs=grid_lngs,
        predicted=predicted,
        uncertainty=uncertainty,
        grid_resolution_m=body.grid_resolution_m,
        ml_model_id=body.ml_model_id if body.algorithm in ML_ALGOS else None,
    )

    duration = (datetime.now(timezone.utc) - t0).total_seconds()
    return ok({
        "campaignId":  str(campaign_id),
        "algorithm":   body.algorithm,
        "gridPoints":  len(grid_lats),
        "modelDbId":   str(model_db_id),
        "durationSec": round(duration, 2),
        "message":     f"Đã tạo {len(grid_lats)} điểm lưới bằng {body.algorithm.upper()}.",
    })


# ─────────────────────────────────────────────────────────────────────────────
# GET /predict/grid/{campaign_id}  —  GeoJSON cho Mapbox
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/grid/{campaign_id}")
async def get_prediction_grid(
    campaign_id: uuid.UUID,
    min_rssi: Optional[float] = Query(None),
    limit:    int             = Query(20_000, ge=1, le=50_000),
    db:       AsyncSession    = Depends(get_db),
):
    """Trả GeoJSON FeatureCollection để Mapbox vẽ heatmap phủ sóng."""
    filters = ["pg.campaign_id = :cid"]
    params: dict = {"cid": str(campaign_id), "limit": limit}

    if min_rssi is not None:
        filters.append("pg.predicted_rssi_dbm >= :min_rssi")
        params["min_rssi"] = min_rssi

    rows = (await db.execute(text(f"""
        SELECT
            ST_X(pg.location::geometry) AS lon,
            ST_Y(pg.location::geometry) AS lat,
            pg.predicted_rssi_dbm,
            pg.uncertainty,
            pg.grid_resolution_m
        FROM prediction_grids pg
        WHERE {" AND ".join(filters)}
        ORDER BY pg.predicted_rssi_dbm DESC
        LIMIT :limit
    """), params)).mappings().all()

    if not rows:
        raise NotFoundError(
            "Chưa có grid. Hãy chạy POST /predict/run/{campaign_id} trước.",
            code="GRID_NOT_FOUND",
        )

    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
            "properties": {
                "rssi":        r["predicted_rssi_dbm"],
                "uncertainty": r["uncertainty"],
                "resolutionM": r["grid_resolution_m"],
                "intensity":   max(0.0, min(1.0, (r["predicted_rssi_dbm"] + 120) / 80)),
            },
        }
        for r in rows
    ]
    # GeoJSON format là chuẩn quốc tế, KHÔNG bọc vào response wrapper
    # (Mapbox đọc thẳng FeatureCollection).
    return {"type": "FeatureCollection", "features": features}


# ─────────────────────────────────────────────────────────────────────────────
# GET /predict/status/{campaign_id}
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/status/{campaign_id}")
async def prediction_status(
    campaign_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(text("""
        SELECT
            COUNT(*)                AS total_points,
            AVG(predicted_rssi_dbm) AS avg_rssi,
            MIN(predicted_rssi_dbm) AS min_rssi,
            MAX(predicted_rssi_dbm) AS max_rssi,
            AVG(uncertainty)        AS avg_uncertainty,
            MAX(created_at)         AS last_generated
        FROM prediction_grids WHERE campaign_id = :cid
    """), {"cid": str(campaign_id)})).mappings().one()

    if not row["total_points"]:
        return ok({"hasGrid": False, "campaignId": str(campaign_id)})

    return ok({
        "hasGrid":          True,
        "campaignId":       str(campaign_id),
        "totalPoints":      row["total_points"],
        "avgRssiDbm":       round(float(row["avg_rssi"]),        2),
        "minRssiDbm":       round(float(row["min_rssi"]),        2),
        "maxRssiDbm":       round(float(row["max_rssi"]),        2),
        "avgUncertaintyDb": round(float(row["avg_uncertainty"]), 2),
        "lastGenerated":    str(row["last_generated"]),
    })


# ─────────────────────────────────────────────────────────────────────────────
# GET/DELETE /predict/models
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/models")
async def list_models():
    from ml.model_store import list_models as _list
    return ok({"models": _list()})


@router.delete("/models/{model_id}")
async def delete_model(model_id: str):
    from ml.model_store import delete as _delete
    if not _delete(model_id):
        raise NotFoundError(f"Model {model_id} không tồn tại.", code="MODEL_NOT_FOUND")
    return ok({"deleted": True, "modelId": model_id})