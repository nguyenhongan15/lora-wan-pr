"""Health & readiness endpoints (rule-design-observability.md §3.1.7)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from ... import __version__
from ..deps import _engine
from ..schemas import HealthStatus

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=HealthStatus)
async def healthz() -> HealthStatus:
    """Liveness — process còn chạy."""
    return HealthStatus(status="ok", version=__version__)


@router.get("/readyz")
async def readyz(request: Request) -> JSONResponse:
    """Readiness — DB ping được không."""
    try:
        with _engine().connect() as c:
            c.execute(text("SELECT 1"))
        return JSONResponse(
            status_code=200,
            content={"status": "ok", "version": __version__},
        )
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            media_type="application/problem+json",
            content={
                "type": "about:blank",
                "title": "Not ready",
                "status": 503,
                "detail": str(exc.__class__.__name__),
                "instance": str(request.url.path),
                "code": "DB_UNREACHABLE",
            },
        )
