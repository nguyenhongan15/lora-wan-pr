"""
services/webhook_retry.py — Background worker quét retry queue.

Pattern: asyncio task spawn từ FastAPI lifespan. Loop mỗi N giây
gọi process_retry_queue.

Đơn giản, không cần Celery/RQ vì:
  - Chạy 1 worker uvicorn → không có race condition
  - Volume thấp (vài chục delivery / phút)
  - In-process → không cần Redis
"""

from __future__ import annotations

import asyncio
import logging

from database import AsyncSessionLocal
from services.webhook_dispatcher import process_retry_queue

logger = logging.getLogger(__name__)

POLL_INTERVAL_SEC = 30   # quét queue mỗi 30s


async def _retry_loop():
    """Loop chính — đặt trong asyncio task."""
    while True:
        try:
            async with AsyncSessionLocal() as db:
                stats = await process_retry_queue(db)

            if stats["retried"] > 0:
                logger.info("webhook_retry_batch", extra=stats)
        except asyncio.CancelledError:
            logger.info("webhook_retry_cancelled")
            raise
        except Exception as e:
            # Không để loop chết vì 1 lỗi tạm thời
            logger.exception("webhook_retry_error", extra={"reason": str(e)})

        await asyncio.sleep(POLL_INTERVAL_SEC)


def start_retry_worker() -> asyncio.Task:
    """Spawn task. Caller giữ reference để cancel khi shutdown."""
    return asyncio.create_task(_retry_loop(), name="webhook-retry-worker")