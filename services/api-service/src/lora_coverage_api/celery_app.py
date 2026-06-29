"""Celery app factory cho admin "Rebuild bản đồ ước lượng" job.

Broker + result backend = Valkey (Redis-compatible cache service docker-compose).
Worker chạy container riêng (`celery-worker`) — dùng cùng image api-service,
override entrypoint sang `celery worker`.

Producer (api-service FastAPI): import `celery_app` → gọi `.delay()` để enqueue.
Consumer (celery-worker): chạy `python -m celery -A lora_coverage_api.celery_app worker`.
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from .config import get_settings


def _build_app() -> Celery:
    s = get_settings()
    app = Celery(
        "lora_coverage",
        broker=s.celery_broker_url,
        backend=s.celery_result_backend,
        include=[
            "lora_coverage_api.tasks.rebuild_coverage",
            "lora_coverage_api.tasks.retrain_ml",
            "lora_coverage_api.tasks.refresh_geo_data",
        ],
    )
    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        # Result expires sau 7 ngày — đủ admin review log cũ, KHÔNG burn memory
        # Valkey 64mb shared với rate-limit.
        result_expires=7 * 24 * 3600,
        # Heavy task ~5-10 phút — không cần ack-late retry vì script idempotent
        # (overwrite output files). Worker concurrency=1 để script multiprocessing
        # bên trong không bị nhân lên.
        task_acks_late=False,
        worker_prefetch_multiplier=1,
        # ── Beat schedule (cần chạy worker với `-B`, xem docker-compose) ──
        # Làm tươi địa hình/nhà HÀNG THÁNG: tải OSM mới → build DSM → rebuild
        # heatmap. 03:00 UTC ngày 1 mỗi tháng (giờ thấp điểm). Footprint nhà đổi
        # chậm nên hàng tháng là đủ; real-time không cần (rebuild ~20-30 phút).
        beat_schedule={
            "refresh-geo-data-monthly": {
                "task": "refresh_geo_data",
                "schedule": crontab(minute=0, hour=3, day_of_month="1"),
            },
        },
    )
    return app


celery_app = _build_app()
