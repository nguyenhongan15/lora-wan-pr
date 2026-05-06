"""FastAPI app factory."""

from __future__ import annotations

import logging

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse

from ..config import get_settings
from .errors import register_error_handlers
from .metrics import metrics_endpoint, metrics_middleware
from .middleware import trace_and_log
from .routers import coverage as coverage_router
from .routers import gateways as gateways_router
from .routers import health as health_router
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

    app = FastAPI(
        title="LoRa Coverage Platform API",
        version="0.2.0",
        default_response_class=ORJSONResponse,
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
    )

    # CORS — strict whitelist (rule-design-cors.md).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["content-type", "x-trace-id", "authorization", "if-match"],
        expose_headers=["etag", "x-trace-id"],
        max_age=600,
    )

    app.middleware("http")(trace_and_log)
    app.middleware("http")(metrics_middleware)

    register_error_handlers(app)

    app.include_router(health_router.router)
    app.include_router(coverage_router.router)
    app.include_router(gateways_router.router)
    app.include_router(survey_router.router)
    app.include_router(webhooks_router.router)

    # Prometheus scrape endpoint — không trong router để giữ nó tối giản
    # và không bị middleware metrics tự ghi lại (đã skip trong middleware).
    app.add_api_route(
        "/metrics", metrics_endpoint, methods=["GET"], include_in_schema=False
    )

    return app
