"""RFC 7807 Problem Details exception handlers."""

from __future__ import annotations

import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..application.errors import ApplicationError


def _trace_id_of(request: Request) -> str:
    return (
        getattr(request.state, "trace_id", None)
        or request.headers.get("x-trace-id")
        or str(uuid.uuid4())
    )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApplicationError)
    async def on_application_error(request: Request, exc: ApplicationError) -> JSONResponse:
        # Plan-auth-v1 §8.1+§8.2: 1 handler duy nhất cho mọi subclass. Routes
        # không phải try/except; adapter raise đúng class — handler tự map
        # http_status + code → RFC 7807.
        return JSONResponse(
            status_code=exc.http_status,
            media_type="application/problem+json",
            content={
                "type": "about:blank",
                "title": exc.__class__.__name__,
                "status": exc.http_status,
                "detail": str(exc) or None,
                "instance": str(request.url.path),
                "code": exc.code,
                "traceId": _trace_id_of(request),
            },
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
