"""FastAPI app factory."""

from __future__ import annotations

import logging

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.middleware import SlowAPIMiddleware

from ..config import get_settings
from .errors import register_error_handlers
from .metrics import metrics_endpoint, metrics_middleware
from .middleware import trace_and_log
from .rate_limit import limiter
from .routers import admin as admin_router
from .routers import auth as auth_router
from .routers import coverage as coverage_router
from .routers import gateways as gateways_router
from .routers import health as health_router
from .routers import me_sources as me_sources_router
from .routers import survey as survey_router
from .routers import webhooks as webhooks_router


def _configure_logging(level: str) -> None:
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO))
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ]
    )


def create_app() -> FastAPI:
    settings = get_settings()
    _configure_logging(settings.log_level)

    # Pre-deploy checklist §6 (custom error screens): production KHÔNG expose
    # /docs + /openapi.json — leak schema nội bộ + giúp attacker fingerprint
    # stack. Staging/development giữ enable để dev/QA xem. Override qua env
    # nếu cần expose tạm (vd 1 sprint demo) — không khuyến khích.
    _docs_enabled = settings.app_env != "production"
    app = FastAPI(
        title="LoRa Coverage Platform API",
        version="0.2.0",
        docs_url="/docs" if _docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if _docs_enabled else None,
    )

    # CORS — STRICTLY WHITELISTED ORIGINS (plan-auth-v2 nguyên tắc bảo mật).
    # Chỉ frontend domain trong CORS_ALLOWED_ORIGINS được phép gọi API.
    # Wildcard "*" bị config.field_validator reject từ startup — không thể
    # vô tình mở. allow_credentials=True bắt buộc cho refresh cookie flow;
    # CORS spec cấm pair "*" + credentials nên whitelist tường minh là điều
    # kiện cứng.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["content-type", "x-trace-id", "authorization", "if-match"],
        expose_headers=["etag", "x-trace-id"],
        max_age=600,
    )

    app.middleware("http")(trace_and_log)
    app.middleware("http")(metrics_middleware)

    # Slowapi: gắn limiter vào app.state để decorator @limiter.limit() phía
    # router truy cập được; middleware xử lý header X-RateLimit-* trên response.
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)

    register_error_handlers(app)

    app.include_router(health_router.router)
    app.include_router(auth_router.router)
    app.include_router(me_sources_router.router)
    app.include_router(admin_router.router)
    app.include_router(coverage_router.router)
    app.include_router(gateways_router.router)
    app.include_router(survey_router.router)
    app.include_router(webhooks_router.router)

    # Prometheus scrape endpoint — không trong router để giữ nó tối giản
    # và không bị middleware metrics tự ghi lại (đã skip trong middleware).
    app.add_api_route("/metrics", metrics_endpoint, methods=["GET"], include_in_schema=False)

    return app
