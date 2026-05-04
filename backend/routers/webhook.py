"""
routers/webhook.py
──────────────────
Nhận uplink từ ChirpStack qua HTTP Webhook.

Security:
  - Verify HMAC-SHA256 signature (header `X-Signature: sha256=<hex>`)
    → chống ai đó POST rác vào endpoint công khai
  - Idempotency qua (devEui, fCnt, gatewayEui): cùng uplink đến
    từ nhiều gateway thì vẫn lưu, nhưng cùng (dev, fCnt, gw) chỉ lưu 1 lần
    → tuân thủ LoRaWAN DedupWindowSize spec

Response: 201 Created khi có measurement mới được lưu, 200 OK khi dedup.

Note: parse + persist logic dùng chung với MQTT listener — xem
services/uplink_ingest.py.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from core.webhook_security import verify_webhook_signature
from core.exceptions import UnauthorizedError, ValidationError
from core.responses import ok
from database import get_db
from services.uplink_ingest import InvalidUplinkError, persist_chirpstack_uplink

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook", tags=["webhook"])


@router.post("/{slug}", status_code=status.HTTP_201_CREATED)
async def receive_uplink(
    slug:        str,
    request:     Request,
    x_signature: Optional[str] = Header(default=None, alias="X-Signature"),
    db:          AsyncSession  = Depends(get_db),
):
    """
    Nhận uplink từ ChirpStack.

    Phải có header `X-Signature: sha256=<hex>` (HMAC-SHA256 của body).
    Secret dùng chung đặt ở env `WEBHOOK_SECRET`.
    """
    settings = get_settings()
    body_bytes = await request.body()

    # ── HMAC verification ───────────────────────────────────────────────────
    if settings.webhook_secret:
        if not verify_webhook_signature(body_bytes, x_signature, settings.webhook_secret):
            logger.warning("webhook_invalid_signature", extra={"slug": slug})
            raise UnauthorizedError(
                "HMAC signature không hợp lệ.",
                code="INVALID_SIGNATURE",
            )
    else:
        logger.warning("webhook_no_secret_configured — accepting all uplinks")

    try:
        body = await request.json()
    except Exception:
        raise ValidationError("Body không phải JSON hợp lệ.", code="INVALID_BODY")

    try:
        result = await persist_chirpstack_uplink(
            db, body, data_source=f"webhook:{slug}",
        )
    except InvalidUplinkError as e:
        raise ValidationError(
            "Thiếu devEui hoặc rxInfo trong payload.",
            code="INCOMPLETE_PAYLOAD",
        ) from e

    await db.commit()

    data = {
        "slug":              slug,
        "devEui":            result["devEui"],
        "measurementsSaved": result["saved"],
        "deduplicated":      result["deduplicated"],
        "gps":               result["gps"],
        "warnings":          result["errors"],
    }

    # 200 OK nếu không có bản ghi mới (chỉ dedup), 201 nếu đã lưu
    if result["saved"] == 0:
        return JSONResponse(status_code=status.HTTP_200_OK, content=ok(data))
    return ok(data)
