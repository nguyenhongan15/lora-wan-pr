"""
core/exceptions.py — Custom exceptions + global handlers.

Mọi lỗi đều trả về format chuẩn: {success: false, error: {code, message, details}}
CORS headers vẫn được gửi kèm dù là lỗi (xem cors.pdf rule #4.2).
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from core.responses import fail

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base class cho mọi lỗi business logic trong app."""
    code:        str         = "INTERNAL_ERROR"
    message:     str         = "Đã xảy ra lỗi không xác định"
    http_status: int         = status.HTTP_500_INTERNAL_SERVER_ERROR
    details:     list | None = None

    def __init__(
        self,
        message: str | None = None,
        code: str | None = None,
        http_status: int | None = None,
        details: list | None = None,
    ):
        if message:     self.message     = message
        if code:        self.code        = code
        if http_status: self.http_status = http_status
        if details is not None: self.details = details
        super().__init__(self.message)


class NotFoundError(AppError):
    code = "NOT_FOUND"
    http_status = status.HTTP_404_NOT_FOUND


class ValidationError(AppError):
    code = "VALIDATION_ERROR"
    http_status = status.HTTP_422_UNPROCESSABLE_ENTITY


class UnauthorizedError(AppError):
    code = "UNAUTHORIZED"
    http_status = status.HTTP_401_UNAUTHORIZED


class ForbiddenError(AppError):
    code = "FORBIDDEN"
    http_status = status.HTTP_403_FORBIDDEN


class RateLimitedError(AppError):
    code = "RATE_LIMITED"
    http_status = status.HTTP_429_TOO_MANY_REQUESTS


# ── Missing-data errors ─────────────────────────────────────────────────────
# Phase v3.2 step 1: thay vì để service crash với 500/AttributeError khi DB row
# có cột NULL không mong đợi, raise các error này → frontend hiển thị thông
# điệp tiếng Việt + actionable hint (vd "Hãy chọn model gateway từ thư viện").
# Pattern: dùng require_field() trong core/validation.py thay vì raise trực tiếp.

class MissingFieldError(AppError):
    """Required column trên 1 DB row đang NULL/missing."""
    code = "MISSING_FIELD"
    http_status = status.HTTP_422_UNPROCESSABLE_ENTITY


class MissingCalibrationError(AppError):
    """Không có active path_loss_calibrations cho environment_type yêu cầu."""
    code = "MISSING_CALIBRATION"
    http_status = status.HTTP_422_UNPROCESSABLE_ENTITY


class UnknownModelError(AppError):
    """Tham chiếu gateway_spec_id / device_spec_id không tồn tại trong library."""
    code = "UNKNOWN_MODEL"
    http_status = status.HTTP_404_NOT_FOUND


class InsufficientDataError(AppError):
    """Không đủ measurements để thực hiện thao tác (vd calibration fit ≥30)."""
    code = "INSUFFICIENT_DATA"
    http_status = status.HTTP_422_UNPROCESSABLE_ENTITY


class NoDemCoverageError(AppError):
    """ITM p2p mode cần DEM tile mà tile chưa tồn tại local (Phase 3)."""
    code = "NO_DEM_COVERAGE"
    http_status = status.HTTP_422_UNPROCESSABLE_ENTITY


# ── Handlers ─────────────────────────────────────────────────────────────────

async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    logger.warning("app_error", extra={
        "code":   exc.code,
        "path":   request.url.path,
        "method": request.method,
    })
    return JSONResponse(
        status_code=exc.http_status,
        content=fail(exc.code, exc.message, exc.details),
    )


async def _http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    # Map HTTP status → mã string chuẩn
    code_map = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        409: "CONFLICT",
        422: "VALIDATION_ERROR",
        429: "RATE_LIMITED",
    }
    code = code_map.get(exc.status_code, "HTTP_ERROR")
    return JSONResponse(
        status_code=exc.status_code,
        content=fail(code, str(exc.detail)),
    )


async def _validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=fail(
            "VALIDATION_ERROR",
            "Dữ liệu request không hợp lệ.",
            details=exc.errors(),
        ),
    )


async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled_exception", extra={
        "path":   request.url.path,
        "method": request.method,
    })
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=fail("INTERNAL_ERROR", "Lỗi nội bộ hệ thống."),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Đăng ký tất cả exception handler với FastAPI app."""
    app.add_exception_handler(AppError,                 _app_error_handler)
    app.add_exception_handler(StarletteHTTPException,   _http_exception_handler)
    app.add_exception_handler(RequestValidationError,   _validation_exception_handler)
    app.add_exception_handler(Exception,                _unhandled_exception_handler)
