"""
core/tenant.py — Multi-tenant context theo header X-Project-Id.

Lưu ý: middleware KHÔNG raise exception (FastAPI exception handler
không bắt được ở middleware layer). Phải return JSONResponse trực tiếp.
"""

from __future__ import annotations

import uuid

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from core.exceptions import ValidationError
from core.responses import fail


HEADER_NAME = "x-project-id"


class TenantMiddleware(BaseHTTPMiddleware):
    """Đọc X-Project-Id → request.state.project_id (UUID hoặc None)."""

    async def dispatch(self, request: Request, call_next):
        raw = request.headers.get(HEADER_NAME)
        if raw:
            try:
                request.state.project_id = uuid.UUID(raw)
            except ValueError:
                # Trả 422 trực tiếp — không raise vì exception handler
                # không chạy ở middleware layer
                return JSONResponse(
                    status_code=422,
                    content=fail(
                        "INVALID_PROJECT_ID",
                        f"Header {HEADER_NAME} không phải UUID hợp lệ.",
                    ),
                )
        else:
            request.state.project_id = None
        return await call_next(request)


def current_project_id(request: Request) -> uuid.UUID | None:
    return getattr(request.state, "project_id", None)


def required_project_id(request: Request) -> uuid.UUID:
    pid = getattr(request.state, "project_id", None)
    if pid is None:
        raise ValidationError(
            f"Endpoint này yêu cầu header {HEADER_NAME}.",
            code="PROJECT_ID_REQUIRED",
        )
    return pid