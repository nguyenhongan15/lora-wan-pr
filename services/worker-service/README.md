# worker-service (placeholder)

Celery 5 + Redis broker. Async tasks:
- Survey ingestion validation (quarantine → training)
- ML model training (Stage 2+)
- Tile generation (raster + vector)
- Email notifications (donation receipts)

Chưa implement ở v0. Khi cần, cùng thư mục `src/lora_coverage_worker/` sẽ chứa task definitions.
