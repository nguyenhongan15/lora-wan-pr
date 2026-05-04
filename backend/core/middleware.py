"""
core/middleware.py — Cross-cutting middleware.

1. CorrelationIdMiddleware  — gán request_id từ header hoặc tự sinh UUID
2. AccessLogMiddleware      — log mỗi request với method/path/status/duration (RED model)
3. MetricsMiddleware        — đếm request_count, error_count, duration histogram
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from core.logging import set_request_id

logger = logging.getLogger("http")


# ── 1. Correlation ID ────────────────────────────────────────────────────────

class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """
    Gán correlation_id (còn gọi là request_id / trace_id) cho mỗi request.
    Đọc từ header `X-Request-ID` nếu client gửi, không thì sinh UUID mới.
    Ghi lại vào response header để client có thể reference khi báo lỗi.
    """

    HEADER = "x-request-id"

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get(self.HEADER) or str(uuid.uuid4())
        set_request_id(rid)
        request.state.request_id = rid

        response: Response = await call_next(request)
        response.headers[self.HEADER] = rid
        return response


# ── 2. Access log (RED: Rate, Errors, Duration) ──────────────────────────────

class AccessLogMiddleware(BaseHTTPMiddleware):
    """Log mỗi request theo chuẩn RED model."""

    async def dispatch(self, request: Request, call_next):
        t0 = time.perf_counter()
        try:
            response: Response = await call_next(request)
            status_code = response.status_code
        except Exception:
            # để exception handler xử lý, chỉ log
            dur_ms = round((time.perf_counter() - t0) * 1000, 2)
            logger.exception("request_failed", extra={
                "method":      request.method,
                "path":        request.url.path,
                "status":      500,
                "duration_ms": dur_ms,
            })
            raise

        dur_ms = round((time.perf_counter() - t0) * 1000, 2)
        level  = logging.ERROR if status_code >= 500 else (
                 logging.WARNING if status_code >= 400 else logging.INFO)
        logger.log(level, "request", extra={
            "method":      request.method,
            "path":        request.url.path,
            "status":      status_code,
            "duration_ms": dur_ms,
        })
        return response


# ── 3. In-memory metrics (đơn giản, không cần Prometheus) ────────────────────

class _Metrics:
    """Thu thập metrics dạng counter + histogram đơn giản."""
    def __init__(self):
        self.request_count: dict[tuple[str, int], int]     = defaultdict(int)
        self.duration_sum:  dict[str, float]               = defaultdict(float)
        self.duration_max:  dict[str, float]               = defaultdict(float)

    def record(self, path: str, status: int, duration_ms: float):
        self.request_count[(path, status)] += 1
        self.duration_sum[path]            += duration_ms
        if duration_ms > self.duration_max[path]:
            self.duration_max[path] = duration_ms

    def snapshot(self) -> dict:
        """Trả về snapshot metrics cho /metrics endpoint."""
        by_path: dict[str, dict] = {}
        for (path, status), count in self.request_count.items():
            by_path.setdefault(path, {"by_status": {}, "total": 0})
            by_path[path]["by_status"][status] = count
            by_path[path]["total"] += count

        for path, info in by_path.items():
            total = info["total"] or 1
            info["avg_duration_ms"] = round(self.duration_sum[path] / total, 2)
            info["max_duration_ms"] = round(self.duration_max[path], 2)
            info["error_count"]     = sum(
                n for st, n in info["by_status"].items() if st >= 500
            )

        return by_path


metrics = _Metrics()


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        t0 = time.perf_counter()
        response = await call_next(request)
        dur_ms = (time.perf_counter() - t0) * 1000
        metrics.record(request.url.path, response.status_code, dur_ms)
        return response
