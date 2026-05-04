"""
services/webhook_dispatcher.py — Outbound webhook delivery với retry/backoff.

Pattern:
  1. fire_event() → tạo delivery record + thử POST ngay
  2. Fail → set final_status='pending', next_retry_at = NOW() + backoff
  3. Background worker (services/webhook_retry.py) quét queue retry

Backoff: 30s, 2m, 10m, 30m → max 4 attempts → 'failed_giveup'

Tái dùng HMAC sign style từ core/webhook_security.py để client verify
cùng cách (X-Signature: sha256=<hex>).
"""

from __future__ import annotations

import hmac
import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from hashlib import sha256

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

DELIVERY_TIMEOUT_SEC = 5.0
MAX_ATTEMPTS         = 4

# Backoff: attempt 1 fail → wait 30s, attempt 2 fail → 2m, ...
RETRY_DELAYS_SEC = [30, 120, 600, 1800]


def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, sha256).hexdigest()


def _next_retry_at(attempt_no: int) -> datetime | None:
    """attempt_no=1 vừa fail → trả thời điểm thử lại lần 2."""
    if attempt_no >= MAX_ATTEMPTS:
        return None
    delay = RETRY_DELAYS_SEC[attempt_no - 1]
    return datetime.now(timezone.utc) + timedelta(seconds=delay)


# ─────────────────────────────────────────────────────────────
# fire_event — public entry
# ─────────────────────────────────────────────────────────────

async def fire_event(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    event_type: str,
    payload:    dict,
) -> dict:
    """Gửi event ra mọi subscription matching. Fail → enqueue retry."""
    subs = (await db.execute(text("""
        SELECT id::text, target_url, secret, event_types
        FROM webhook_subscriptions
        WHERE project_id = :pid
          AND deleted_at IS NULL
          AND is_active  = TRUE
    """), {"pid": str(project_id)})).mappings().all()

    matching = [
        s for s in subs
        if not s["event_types"]
        or event_type in s["event_types"]
    ]

    body_dict = {
        "eventType":  event_type,
        "projectId":  str(project_id),
        "timestamp":  datetime.now(timezone.utc).isoformat(),
        "payload":    payload,
    }
    body_bytes = json.dumps(body_dict, default=str).encode()

    delivered = 0
    failed    = 0

    for s in matching:
        result = await _deliver_one(
            target_url=s["target_url"], secret=s["secret"], body_bytes=body_bytes,
        )
        ok = result["status_code"] is not None and 200 <= result["status_code"] < 300

        await _log_delivery(
            db,
            subscription_id=s["id"],
            event_type=event_type,
            payload=body_dict,
            attempt_no=1,
            final_status="success" if ok else "pending",
            next_retry_at=None if ok else _next_retry_at(1),
            **result,
        )

        if ok: delivered += 1
        else:  failed    += 1

    await db.commit()
    return {
        "eventType":   event_type,
        "subscribers": len(matching),
        "delivered":   delivered,
        "failed":      failed,
    }


# ─────────────────────────────────────────────────────────────
# Retry job — gọi từ services/webhook_retry.py
# ─────────────────────────────────────────────────────────────

async def process_retry_queue(db: AsyncSession, *, batch_size: int = 50) -> dict:
    """
    Quét delivery có final_status='pending' AND next_retry_at <= NOW().
    Mỗi cái: thử POST lại; cập nhật final_status hoặc enqueue lần kế.
    """
    rows = (await db.execute(text("""
        SELECT d.id::text          AS id,
               d.subscription_id::text AS sub_id,
               d.event_type        AS event_type,
               d.payload           AS payload,
               d.attempt_no        AS attempt_no,
               s.target_url, s.secret
        FROM webhook_deliveries d
        JOIN webhook_subscriptions s ON s.id = d.subscription_id
        WHERE d.final_status = 'pending'
          AND d.next_retry_at <= NOW()
          AND s.deleted_at IS NULL
          AND s.is_active  = TRUE
        ORDER BY d.next_retry_at ASC
        LIMIT :n
    """), {"n": batch_size})).mappings().all()

    retried, succeeded, given_up = 0, 0, 0

    for r in rows:
        retried += 1
        next_attempt = r["attempt_no"] + 1
        body_bytes   = json.dumps(r["payload"], default=str).encode()

        result = await _deliver_one(
            target_url=r["target_url"], secret=r["secret"], body_bytes=body_bytes,
        )
        ok = result["status_code"] is not None and 200 <= result["status_code"] < 300

        if ok:
            final_status   = "success"
            next_retry_at  = None
            succeeded     += 1
        elif next_attempt >= MAX_ATTEMPTS:
            final_status   = "failed_giveup"
            next_retry_at  = None
            given_up      += 1
        else:
            final_status   = "pending"
            next_retry_at  = _next_retry_at(next_attempt)

        # Insert NEW delivery row (giữ history)
        await _log_delivery(
            db,
            subscription_id=r["sub_id"],
            event_type=r["event_type"],
            payload=r["payload"],
            attempt_no=next_attempt,
            final_status=final_status,
            next_retry_at=next_retry_at,
            **result,
        )
        # Đánh dấu row gốc đã xử lý (chuyển final_status để khỏi retry lặp)
        await db.execute(text("""
            UPDATE webhook_deliveries
            SET final_status = CASE WHEN :ok THEN 'success' ELSE 'failed_giveup' END,
                next_retry_at = NULL
            WHERE id = :id
              AND final_status = 'pending'
        """), {"ok": ok or next_attempt >= MAX_ATTEMPTS, "id": r["id"]})

    await db.commit()
    return {"retried": retried, "succeeded": succeeded, "givenUp": given_up}


# ─────────────────────────────────────────────────────────────
# Internals
# ─────────────────────────────────────────────────────────────

async def _deliver_one(*, target_url: str, secret: str, body_bytes: bytes) -> dict:
    headers = {
        "Content-Type": "application/json",
        "X-Signature":  _sign(secret, body_bytes),
    }

    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=DELIVERY_TIMEOUT_SEC) as client:
            resp = await client.post(target_url, content=body_bytes, headers=headers)
        return {
            "status_code":   resp.status_code,
            "response_body": resp.text[:1000],
            "error_message": None,
            "duration_ms":   int((time.perf_counter() - t0) * 1000),
        }
    except httpx.HTTPError as e:
        return {
            "status_code":   None,
            "response_body": None,
            "error_message": str(e)[:500],
            "duration_ms":   int((time.perf_counter() - t0) * 1000),
        }


async def _log_delivery(
    db: AsyncSession, *,
    subscription_id: str,
    event_type:      str,
    payload:         dict,
    status_code:     int | None,
    response_body:   str | None,
    error_message:   str | None,
    duration_ms:     int,
    attempt_no:      int,
    final_status:    str,
    next_retry_at:   datetime | None,
) -> None:
    await db.execute(text("""
        INSERT INTO webhook_deliveries (
            subscription_id, event_type, payload, status_code,
            response_body, error_message, duration_ms,
            attempt_no, final_status, next_retry_at
        ) VALUES (
            :sid::uuid, :etype, CAST(:payload AS jsonb), :status,
            :resp, :err, :dur,
            :att, :fin, :nra
        )
    """), {
        "sid":     subscription_id,
        "etype":   event_type,
        "payload": json.dumps(payload, default=str),
        "status":  status_code,
        "resp":    response_body,
        "err":     error_message,
        "dur":     duration_ms,
        "att":     attempt_no,
        "fin":     final_status,
        "nra":     next_retry_at,
    })