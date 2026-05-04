"""
services/prediction_store.py — Lưu prediction grid + version snapshot.

Phase 6: trước khi xoá grid cũ, snapshot vào prediction_grid_snapshots
để có thể rollback / so sánh nội bộ campaign qua thời gian.
"""

from __future__ import annotations

import json
import logging
import uuid

import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def _snapshot_existing_grid(
    db: AsyncSession,
    campaign_id: uuid.UUID,
    label: str | None = None,
) -> uuid.UUID | None:
    """
    Lấy grid hiện có → bundle thành GeoJSON-ish JSON → insert snapshot row.
    Return: snapshot_id mới hoặc None (nếu không có grid để snapshot).
    """
    rows = (await db.execute(text("""
        SELECT
            ST_X(pg.location::geometry) AS lng,
            ST_Y(pg.location::geometry) AS lat,
            pg.predicted_rssi_dbm,
            pg.uncertainty,
            pg.grid_resolution_m,
            m.algorithm
        FROM prediction_grids pg
        JOIN ml_models m ON m.id = pg.model_id
        WHERE pg.campaign_id = :cid
        LIMIT 50000
    """), {"cid": str(campaign_id)})).mappings().all()

    if not rows:
        return None

    rssis     = [float(r["predicted_rssi_dbm"]) for r in rows]
    algorithm = rows[0]["algorithm"]

    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(r["lng"]), float(r["lat"])]},
            "properties": {
                "rssi":        float(r["predicted_rssi_dbm"]),
                "uncertainty": float(r["uncertainty"]) if r["uncertainty"] is not None else None,
                "resolutionM": r["grid_resolution_m"],
            },
        }
        for r in rows
    ]
    payload = {"type": "FeatureCollection", "features": features}

    snap_id = uuid.uuid4()
    await db.execute(text("""
        INSERT INTO prediction_grid_snapshots (
            id, campaign_id, algorithm, label,
            grid_count, avg_rssi, min_rssi, max_rssi, payload
        ) VALUES (
            :id::uuid, :cid::uuid, :algo, :label,
            :cnt, :avg, :min, :max, CAST(:payload AS jsonb)
        )
    """), {
        "id":      str(snap_id),
        "cid":     str(campaign_id),
        "algo":    algorithm,
        "label":   label,
        "cnt":     len(rows),
        "avg":     sum(rssis) / len(rssis),
        "min":     min(rssis),
        "max":     max(rssis),
        "payload": json.dumps(payload),
    })

    logger.info("prediction_grid_snapshot_created", extra={
        "campaign_id": str(campaign_id),
        "snapshot_id": str(snap_id),
        "grid_count":  len(rows),
    })
    return snap_id


async def save_prediction_grid(
    db: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    algorithm:   str,
    grid_lats:   np.ndarray,
    grid_lngs:   np.ndarray,
    predicted:   np.ndarray,
    uncertainty: np.ndarray,
    grid_resolution_m: int,
    snapshot_label: str | None = None,
    ml_model_id: str | None = None,
) -> uuid.UUID:
    """
    Phase 6: snapshot grid cũ trước → insert grid mới.
    Return: model_db_id mới.

    ml_model_id:
      - None  → tự tạo UUID + INSERT ml_models row (cho IDW/Kriging ad-hoc).
      - str   → reuse model đã được persist_trained_model insert
                (tránh duplicate row cho ML algo).
    """
    # 1) Snapshot (nếu có grid cũ)
    await _snapshot_existing_grid(db, campaign_id, snapshot_label)

    # 2) Resolve model_id
    if ml_model_id is not None:
        model_id = uuid.UUID(ml_model_id)
    else:
        model_id = uuid.uuid4()
        await db.execute(text("""
            INSERT INTO ml_models (id, name, algorithm, version, trained_at)
            VALUES (:id, :name, :algo, '1.0', NOW())
        """), {
            "id":   str(model_id),
            "name": f"{algorithm.upper()} – campaign {campaign_id}",
            "algo": algorithm,
        })

    # 3) Xoá grid cũ
    await db.execute(
        text("DELETE FROM prediction_grids WHERE campaign_id = :cid"),
        {"cid": str(campaign_id)},
    )

    # 4) Bulk insert grid mới
    records = [
        {
            "id":       str(uuid.uuid4()),
            "model_id": str(model_id),
            "cid":      str(campaign_id),
            "lng":      float(grid_lngs[i]),
            "lat":      float(grid_lats[i]),
            "rssi":     float(predicted[i]),
            "unc":      float(uncertainty[i]),
            "res":      grid_resolution_m,
        }
        for i in range(len(grid_lats))
    ]

    await db.execute(text("""
        INSERT INTO prediction_grids
            (id, model_id, campaign_id, location,
             predicted_rssi_dbm, uncertainty, grid_resolution_m, created_at)
        SELECT
            r.id::uuid, r.model_id::uuid, r.cid::uuid,
            ST_SetSRID(ST_MakePoint(r.lng::float, r.lat::float), 4326),
            r.rssi::float, r.unc::float, r.res::int, NOW()
        FROM jsonb_to_recordset(CAST(:records AS jsonb))
          AS r(id text, model_id text, cid text,
               lng text, lat text, rssi text, unc text, res text)
    """), {"records": json.dumps(records)})

    await db.commit()

    logger.info("prediction_grid_saved", extra={
        "campaign_id": str(campaign_id),
        "model_db_id": str(model_id),
        "algorithm":   algorithm,
        "grid_points": len(records),
    })
    return model_id


async def persist_trained_model(
    db: AsyncSession,
    *,
    model_id:   str,
    algorithm:  str,
    campaign_id: uuid.UUID,
    metrics:    dict,
    hyperparameters: dict,
    feature_importance: dict,
) -> None:
    await db.execute(text("""
        INSERT INTO ml_models
            (id, name, algorithm, version,
             rmse_db, mae_db, r2_score,
             hyperparameters, feature_importance, trained_at)
        VALUES
            (:id, :name, :algo, :ver,
             :rmse, :mae, :r2,
             CAST(:hp AS jsonb), CAST(:fi AS jsonb), NOW())
    """), {
        "id":   model_id,
        "name": f"{algorithm.upper()} – campaign {campaign_id}",
        "algo": algorithm,
        "ver":  "2.0",
        "rmse": metrics.get("rmse_db"),
        "mae":  metrics.get("mae_db"),
        "r2":   metrics.get("r2_score"),
        "hp":   json.dumps(hyperparameters),
        "fi":   json.dumps(feature_importance),
    })
    await db.commit()