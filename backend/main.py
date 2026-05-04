"""
main.py — Entrypoint của FastAPI application.

Phase 6: spawn webhook retry worker trong lifespan.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import get_settings
from core.exceptions import register_exception_handlers
from core.logging import setup_logging
from core.middleware import (
    AccessLogMiddleware,
    CorrelationIdMiddleware,
    MetricsMiddleware,
    metrics,
)
from core.responses import ok
from core.tenant import TenantMiddleware
from database import engine
from routers import (
    calibration,
    campaigns,
    coverage,
    dem_router,
    exports,
    gateways,
    health,
    lpwan_sync,
    measurements,
    predict,
    reports,
    sandbox,
    scenarios,
    simulator,
    snapshots,
    webhook,
    webhook_subscriptions,
)
from database import AsyncSessionLocal
from services.calibration_cache import prefetch_all as prefetch_calibrations
from services.mqtt_listener import start_mqtt_listener
from services.webhook_retry import start_retry_worker

from routers.aoi          import router as aoi_router
from routers.optimization import router as optimization_router

settings = get_settings()

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("app_starting", extra={
        "env":    settings.app_env,
        "prefix": settings.api_prefix,
    })

    # Phase v3.2: warm calibration cache để request đầu tiên không phải đợi DB.
    # Best-effort: lỗi DB (vd init đầu tiên chưa có table) → log warning, app
    # vẫn boot. rf_predictor sẽ lazy-fetch khi request gọi resolve_calibration.
    try:
        async with AsyncSessionLocal() as session:
            n = await prefetch_calibrations(session)
        logger.info("calibration_cache_prefetched", extra={"count": n})
    except Exception as exc:
        logger.warning(
            "calibration_cache_prefetch_failed",
            extra={"error": str(exc)},
        )

    # Spawn webhook retry worker
    retry_task = start_retry_worker()
    logger.info("webhook_retry_worker_started")

    # Spawn MQTT listener (chỉ khi enabled)
    mqtt_task = None
    if settings.mqtt_enabled:
        mqtt_task = start_mqtt_listener()
        logger.info("mqtt_listener_started", extra={
            "host":  settings.mqtt_broker_host,
            "topic": settings.mqtt_topic,
        })

    try:
        yield
    finally:
        # Cancel workers trước khi đóng DB
        retry_task.cancel()
        try:
            await retry_task
        except Exception:
            pass

        if mqtt_task is not None:
            mqtt_task.cancel()
            try:
                await mqtt_task
            except Exception:
                pass

        await engine.dispose()
        logger.info("app_stopped")


app = FastAPI(
    title=settings.app_name,
    description="Backend cho hệ thống phân tích phủ sóng LoRaWAN",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=f"{settings.api_prefix}/docs",
    openapi_url=f"{settings.api_prefix}/openapi.json",
    redoc_url=None,
)


app.add_middleware(MetricsMiddleware)
app.add_middleware(AccessLogMiddleware)
app.add_middleware(TenantMiddleware)
app.add_middleware(CorrelationIdMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Request-ID", "X-Project-Id"],
    max_age=settings.cors_max_age,
)

register_exception_handlers(app)

static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/health", tags=["system"])
async def health_check():
    return ok({"status": "ok", "service": settings.app_name, "version": "1.0.0"})


@app.get("/metrics", tags=["system"])
async def get_metrics():
    return ok(metrics.snapshot())


api = settings.api_prefix

app.include_router(gateways.router,              prefix=api)
app.include_router(campaigns.router,             prefix=api)
app.include_router(measurements.router,          prefix=api)
app.include_router(coverage.router,              prefix=api)
app.include_router(predict.router,               prefix=api)
app.include_router(simulator.router,             prefix=api)
app.include_router(sandbox.router,               prefix=api)
app.include_router(exports.router,               prefix=api)
app.include_router(calibration.router,           prefix=api)
app.include_router(health.router,                prefix=api)
app.include_router(scenarios.router,             prefix=api)
app.include_router(reports.router,               prefix=api)
app.include_router(snapshots.router,             prefix=api)
app.include_router(webhook_subscriptions.router, prefix=api)
app.include_router(dem_router.router,            prefix=api)
app.include_router(lpwan_sync.router,            prefix=api)
app.include_router(webhook.router,               prefix=api)
app.include_router(aoi_router,                   prefix=api)
app.include_router(optimization_router,          prefix=api)