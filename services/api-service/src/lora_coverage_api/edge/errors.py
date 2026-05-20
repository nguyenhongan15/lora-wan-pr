"""RFC 7807 Problem Details exception handlers."""

from __future__ import annotations

import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..application.errors import ApplicationError


def _trace_id_of(request: Request) -> str:
    return (
        getattr(request.state, "trace_id", None)
        or request.headers.get("x-trace-id")
        or str(uuid.uuid4())
    )


_RATE_LIMIT_UNIT_SECONDS: dict[str, int] = {
    "second": 1,
    "seconds": 1,
    "minute": 60,
    "minutes": 60,
    "hour": 3600,
    "hours": 3600,
    "day": 86400,
    "days": 86400,
}


def _rate_limit_period_seconds(detail: str) -> int:
    """Parse slowapi detail string ('10 per 1 minute' hoặc '10 per minute') → seconds.

    Fallback 60 nếu format không nhận dạng được.
    """
    parts = detail.lower().split()
    for i, p in enumerate(parts):
        if p in _RATE_LIMIT_UNIT_SECONDS:
            unit = _RATE_LIMIT_UNIT_SECONDS[p]
            # Tìm multiplier ngay trước unit (vd "per 1 minute") — default 1.
            prev = parts[i - 1] if i > 0 else ""
            mul = int(prev) if prev.isdigit() else 1
            return max(1, mul * unit)
    return 60


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApplicationError)
    async def on_application_error(request: Request, exc: ApplicationError) -> JSONResponse:
        # Plan-auth-v1 §8.1+§8.2: 1 handler duy nhất cho mọi subclass. Routes
        # không phải try/except; adapter raise đúng class — handler tự map
        # http_status + code → RFC 7807.
        body: dict[str, object] = {
            "type": "about:blank",
            "title": exc.__class__.__name__,
            "status": exc.http_status,
            "detail": str(exc) or None,
            "instance": str(request.url.path),
            "code": exc.code,
            "traceId": _trace_id_of(request),
        }
        headers: dict[str, str] = {}
        # Plan-auth-v2: AccountLockedError carries retry_after_seconds; expose
        # cả trong body (cho frontend đếm ngược) lẫn Retry-After header (chuẩn HTTP).
        retry_after = getattr(exc, "retry_after_seconds", None)
        if retry_after is not None:
            body["retry_after_seconds"] = retry_after
            headers["Retry-After"] = str(retry_after)
        return JSONResponse(
            status_code=exc.http_status,
            media_type="application/problem+json",
            content=body,
            headers=headers or None,
        )

    @app.exception_handler(RateLimitExceeded)
    async def on_rate_limit(request: Request, exc: RateLimitExceeded) -> JSONResponse:
        # Plan-auth-v2: slowapi raise RateLimitExceeded khi vượt limit của
        # decorator. exc.detail dạng "10 per 1 minute" — không có retry-after
        # chính xác (cần bucket state). Dùng period seconds làm conservative
        # upper-bound Retry-After.
        retry_after = _rate_limit_period_seconds(str(exc.detail))
        return JSONResponse(
            status_code=429,
            media_type="application/problem+json",
            content={
                "type": "about:blank",
                "title": "Rate Limit Exceeded",
                "status": 429,
                "detail": f"Quá nhiều request từ địa chỉ này. Thử lại sau {retry_after} giây.",
                "instance": str(request.url.path),
                "code": "rate_limit_exceeded",
                "traceId": _trace_id_of(request),
                "retry_after_seconds": retry_after,
            },
            headers={"Retry-After": str(retry_after)},
        )

    @app.exception_handler(RequestValidationError)
    async def on_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            media_type="application/problem+json",
            content={
                "type": "about:blank",
                "title": "Validation failed",
                "status": 422,
                "detail": "One or more fields failed validation.",
                "instance": str(request.url.path),
                "code": "VALIDATION_ERROR",
                "traceId": _trace_id_of(request),
                "errors": [
                    {
                        "field": ".".join(str(p) for p in err["loc"][1:]),
                        "message": err["msg"],
                        "type": err["type"],
                    }
                    for err in exc.errors()
                ],
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def on_http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            media_type="application/problem+json",
            content={
                "type": "about:blank",
                "title": exc.detail if isinstance(exc.detail, str) else "HTTP error",
                "status": exc.status_code,
                "instance": str(request.url.path),
                "traceId": _trace_id_of(request),
            },
        )

    @app.exception_handler(Exception)
    async def on_unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Không leak stack trace ra client. Log server-side ở middleware.
        return JSONResponse(
            status_code=500,
            media_type="application/problem+json",
            content={
                "type": "about:blank",
                "title": "Internal Server Error",
                "status": 500,
                "detail": "Đã xảy ra lỗi không mong đợi. Liên hệ support kèm traceId.",
                "instance": str(request.url.path),
                "code": "INTERNAL_ERROR",
                "traceId": _trace_id_of(request),
            },
        )
