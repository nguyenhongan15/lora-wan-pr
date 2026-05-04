"""
routers/webhook_subscriptions.py — Outbound webhook management (P4 / P2).

GET    /webhook-subscriptions          (filter project_id)
POST   /webhook-subscriptions          (create)
DELETE /webhook-subscriptions/{id}     (soft delete)
POST   /webhook-subscriptions/{id}/test (fire test event)
GET    /webhook-subscriptions/{id}/deliveries (lịch sử 50 gần nhất)
"""

from __future__ import annotations

import secrets
import uuid

from fastapi import APIRouter, Depends, status
from pydantic import Field, UUID4
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import NotFoundError
from core.responses import CamelModel, ok
from core.tenant import current_project_id
from database import get_db
from services.webhook_dispatcher import fire_event

router = APIRouter(prefix="/webhook-subscriptions", tags=["webhook-subscriptions"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class SubscriptionCreate(CamelModel):
    project_id:  UUID4
    name:        str = Field(..., min_length=1, max_length=255)
    target_url:  str = Field(..., pattern=r"^https?://")
    event_types: list[str] = Field(default_factory=list)


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/")
async def list_subscriptions(
    db: AsyncSession = Depends(get_db),
    project_id: uuid.UUID | None = Depends(current_project_id),
):
    """Liệt kê. Nếu có header X-Project-Id → filter theo project."""
    where  = "deleted_at IS NULL"
    params: dict = {}
    if project_id:
        where = "deleted_at IS NULL AND project_id = :pid"
        params["pid"] = str(project_id)

    rows = (await db.execute(text(f"""
        SELECT id::text, project_id::text AS "projectId",
               name, target_url AS "targetUrl",
               event_types AS "eventTypes",
               is_active AS "isActive",
               created_at AS "createdAt"
        FROM webhook_subscriptions
        WHERE {where}
        ORDER BY created_at DESC
    """), params)).mappings().all()

    return ok([dict(r) for r in rows], meta={"total": len(rows)})


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_subscription(
    body: SubscriptionCreate,
    db:   AsyncSession = Depends(get_db),
):
    """
    Tạo subscription mới — secret được auto-gen (32 byte hex).
    Trả về secret đúng MỘT LẦN để client lưu (mai sau không xem lại được).
    """
    new_id = uuid.uuid4()
    secret = secrets.token_hex(32)

    await db.execute(text("""
        INSERT INTO webhook_subscriptions
            (id, project_id, name, target_url, secret, event_types)
        VALUES
            (:id::uuid, :pid::uuid, :name, :url, :secret, CAST(:etypes AS jsonb))
    """), {
        "id":     str(new_id),
        "pid":    str(body.project_id),
        "name":   body.name,
        "url":    body.target_url,
        "secret": secret,
        "etypes": __import__("json").dumps(body.event_types),
    })
    await db.commit()

    return ok({
        "id":         str(new_id),
        "name":       body.name,
        "targetUrl":  body.target_url,
        "eventTypes": body.event_types,
        "secret":     secret,        # ⚠️ chỉ trả 1 lần
        "warning":    "Lưu lại secret — không thể xem lại.",
    })


@router.delete("/{subscription_id}")
async def delete_subscription(
    subscription_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(text("""
        UPDATE webhook_subscriptions
        SET deleted_at = NOW()
        WHERE id = :id AND deleted_at IS NULL
        RETURNING id
    """), {"id": str(subscription_id)})

    if not res.first():
        raise NotFoundError(
            f"Subscription {subscription_id} không tồn tại.",
            code="SUBSCRIPTION_NOT_FOUND",
        )
    await db.commit()
    return ok({"deleted": True, "id": str(subscription_id)})


@router.post("/{subscription_id}/test")
async def test_fire(
    subscription_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Gửi test event để verify endpoint subscriber đang nhận đúng."""
    sub = (await db.execute(text("""
        SELECT project_id::text AS pid
        FROM webhook_subscriptions
        WHERE id = :id AND deleted_at IS NULL
    """), {"id": str(subscription_id)})).mappings().first()

    if not sub:
        raise NotFoundError(
            f"Subscription {subscription_id} không tồn tại.",
            code="SUBSCRIPTION_NOT_FOUND",
        )

    result = await fire_event(
        db,
        project_id=uuid.UUID(sub["pid"]),
        event_type="webhook.test",
        payload={"message": "Test event from LoRa Coverage API"},
    )
    return ok(result)


@router.get("/{subscription_id}/deliveries")
async def list_deliveries(
    subscription_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(text("""
        SELECT id::text, event_type AS "eventType",
               status_code AS "statusCode",
               error_message AS "errorMessage",
               duration_ms AS "durationMs",
               delivered_at AS "deliveredAt"
        FROM webhook_deliveries
        WHERE subscription_id = :sid
        ORDER BY delivered_at DESC
        LIMIT 50
    """), {"sid": str(subscription_id)})).mappings().all()

    return ok([dict(r) for r in rows], meta={"total": len(rows)})