"""
routers/snapshots.py — Prediction grid version history.

GET    /snapshots/{campaign_id}            (list)
GET    /snapshots/{snapshot_id}/grid       (GeoJSON content)
POST   /snapshots/{snapshot_id}/restore    (restore vào prediction_grids)
DELETE /snapshots/{snapshot_id}            (xoá snapshot)
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import NotFoundError
from core.responses import ok
from database import get_db

router = APIRouter(prefix="/snapshots", tags=["snapshots"])


@router.get("/{campaign_id}")
async def list_snapshots(
    campaign_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """List snapshots cho campaign — không trả payload (cồng kềnh)."""
    rows = (await db.execute(text("""
        SELECT id::text, algorithm, label,
               grid_count AS "gridCount",
               avg_rssi   AS "avgRssi",
               min_rssi   AS "minRssi",
               max_rssi   AS "maxRssi",
               created_at AS "createdAt"
        FROM prediction_grid_snapshots
        WHERE campaign_id = :cid
        ORDER BY created_at DESC
    """), {"cid": str(campaign_id)})).mappings().all()

    return ok([dict(r) for r in rows], meta={"total": len(rows)})


@router.get("/{snapshot_id}/grid")
async def get_snapshot_grid(
    snapshot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Trả GeoJSON FeatureCollection — Mapbox đọc trực tiếp (không wrapper)."""
    row = (await db.execute(text("""
        SELECT payload FROM prediction_grid_snapshots WHERE id = :id
    """), {"id": str(snapshot_id)})).mappings().first()

    if not row:
        raise NotFoundError(f"Snapshot {snapshot_id} không tồn tại.",
                            code="SNAPSHOT_NOT_FOUND")
    return row["payload"]


@router.post("/{snapshot_id}/restore", status_code=status.HTTP_201_CREATED)
async def restore_snapshot(
    snapshot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Restore snapshot → prediction_grids.
    Snapshot grid hiện tại trước (giữ history), rồi insert lại từ snapshot.
    """
    snap = (await db.execute(text("""
        SELECT campaign_id::text AS cid, algorithm, payload
        FROM prediction_grid_snapshots
        WHERE id = :id
    """), {"id": str(snapshot_id)})).mappings().first()

    if not snap:
        raise NotFoundError(f"Snapshot {snapshot_id} không tồn tại.",
                            code="SNAPSHOT_NOT_FOUND")

    # Snapshot grid hiện tại trước (đệ quy lazy import)
    from services.prediction_store import _snapshot_existing_grid
    await _snapshot_existing_grid(
        db, uuid.UUID(snap["cid"]),
        label=f"auto-before-restore {snapshot_id}",
    )

    # Tạo model entry mới
    new_model_id = uuid.uuid4()
    await db.execute(text("""
        INSERT INTO ml_models (id, name, algorithm, version, trained_at)
        VALUES (:id, :name, :algo, '1.0', NOW())
    """), {
        "id":   str(new_model_id),
        "name": f"RESTORED – snapshot {snapshot_id}",
        "algo": snap["algorithm"],
    })

    # Xoá grid hiện tại
    await db.execute(
        text("DELETE FROM prediction_grids WHERE campaign_id = :cid"),
        {"cid": snap["cid"]},
    )

    # Insert lại từ snapshot.payload.features
    payload   = snap["payload"]
    features  = payload.get("features", [])
    records = []
    for f in features:
        coords = f["geometry"]["coordinates"]
        props  = f["properties"]
        records.append({
            "id":       str(uuid.uuid4()),
            "model_id": str(new_model_id),
            "cid":      snap["cid"],
            "lng":      coords[0],
            "lat":      coords[1],
            "rssi":     props["rssi"],
            "unc":      props.get("uncertainty") or 0.0,
            "res":      props.get("resolutionM") or 50,
        })

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

    return ok({
        "snapshotId":  str(snapshot_id),
        "campaignId":  snap["cid"],
        "newModelId":  str(new_model_id),
        "gridPoints":  len(records),
        "message":     f"Đã khôi phục {len(records)} điểm từ snapshot.",
    })


@router.delete("/{snapshot_id}")
async def delete_snapshot(
    snapshot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(text("""
        DELETE FROM prediction_grid_snapshots
        WHERE id = :id
        RETURNING id
    """), {"id": str(snapshot_id)})

    if not res.first():
        raise NotFoundError(f"Snapshot {snapshot_id} không tồn tại.",
                            code="SNAPSHOT_NOT_FOUND")
    await db.commit()
    return ok({"deleted": True, "id": str(snapshot_id)})