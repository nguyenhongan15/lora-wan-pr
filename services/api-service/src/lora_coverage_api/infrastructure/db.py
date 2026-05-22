"""SQLAlchemy engine factory."""

from __future__ import annotations

import logging
import time

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import DBAPIError

logger = logging.getLogger(__name__)

# Exponential backoff: 100 → 200 → 400 → 800 → 1600 ms (≈3.1s tổng cho 5 retry)
_RETRY_DELAYS_MS: tuple[int, ...] = (100, 200, 400, 800, 1600)


def make_engine(database_url: str) -> Engine:
    engine = create_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        future=True,
    )
    _verify_connection(engine)
    return engine


def _verify_connection(engine: Engine) -> None:
    """Ping DB sau create_engine với exponential backoff.

    pool_pre_ping=True xử lý stale connection lúc borrow, nhưng nếu DB chưa
    sẵn sàng lúc app boot (failover, container cold start) thì process crash
    ngay. Retry ở đây sống sót qua blip ngắn mà không cần wrapper bên ngoài.
    """
    last_exc: DBAPIError | None = None
    for attempt in range(len(_RETRY_DELAYS_MS) + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            if attempt:
                logger.info("db_connect_recovered attempts=%d", attempt + 1)
            return
        except DBAPIError as exc:
            last_exc = exc
            if attempt == len(_RETRY_DELAYS_MS):
                break
            delay_ms = _RETRY_DELAYS_MS[attempt]
            logger.warning(
                "db_connect_retry attempt=%d delay_ms=%d err=%s",
                attempt + 1,
                delay_ms,
                exc.__class__.__name__,
            )
            time.sleep(delay_ms / 1000.0)
    raise RuntimeError("Database unavailable after retries") from last_exc
