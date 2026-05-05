"""Trace ID + structured logging middleware."""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from fastapi import Request, Response

logger = structlog.get_logger("lora_coverage_api.access")


async def trace_and_log(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    trace_id = request.headers.get("x-trace-id") or str(uuid.uuid4())
    request.state.trace_id = trace_id

    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    response.headers["x-trace-id"] = trace_id

    logger.info(
        "http_request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=round(elapsed_ms, 2),
        trace_id=trace_id,
        client=request.client.host if request.client else None,
    )
    return response
