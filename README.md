# LoRa Coverage Mapping Platform

Vietnam-first, donation-funded, fully-free LoRa network coverage mapping & ML-based path-loss prediction platform.

## Quick start (dev)

```bash
cp .env.template .env       # rồi điền giá trị
docker compose up -d db
cd services/api-service
uv sync                      # hoặc pip install -e .
alembic -c ../../migrations/alembic.ini upgrade head
python -m lora_coverage_api  # chạy uvicorn local

# Frontend
cd ../../apps/web-app
npm install
npm run dev
```

## Repository layout

```
apps/
  web-app/          React 19 + Vite 8 + JavaScript ES2024 + JSDoc + Zod
  mobile-app/       React Native + Expo (placeholder)
  widget/           Embeddable iframe widget (placeholder)
  docs/             User-facing docs site (placeholder)

services/
  api-service/      FastAPI REST API (5-layer architecture)
  ml-service/       Path-loss models (Stage 1–4)
  worker-service/   Celery + Redis (async ingest, training)
  tile-server/      Vector/raster tile generator (placeholder)

packages/
  api-types/        OpenAPI-generated type defs (shared)
  sdk-python/       Python client SDK
  sdk-js/           JS client SDK
  sdk-go/           Go client SDK (placeholder)

migrations/         Alembic migrations + seed data
ops/                Docker, Nginx, Grafana dashboards
docs/               Architecture & ADR docs
core-logic/         Source-of-truth design docs (DO NOT MODIFY)
u-work/             Work notes from Claude
legacy/             Archived previous codebase (read-only reference)
```

## Architecture

5-layer strict separation enforced by `import-linter`:

```
Client → Edge (FastAPI router/middleware)
       → Application (business logic, repository interfaces)
       → Repository (CoverageQuery, SurveyIngest, GatewayDirectory, AddressResolution)
       → Storage (PostGIS, Cloudflare R2, optional Valkey)
```

`application/` **never** imports `infrastructure/`. Enforced in CI.

## Ràng buộc bất biến (hard invariants)

- Mọi `Prediction` đều có `Confidence`
- Mọi survey upload đi qua `quarantine` trước khi vào `training` (2 hypertable riêng)
- General donations không bao giờ chạm Google APIs
- `model_version` nằm trong S3 key prefix
- v1 deploy: Hetzner CPX31 ($16/mo), Docker Compose, target <$100/mo

## Tài liệu

Xem `core-logic/main-logic/system-architecture.md` để hiểu đầy đủ thiết kế.
