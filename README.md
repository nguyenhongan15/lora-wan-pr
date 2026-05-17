# Nền tảng bản đồ vùng phủ sóng LoRa



## Khởi động nhanh (dev)

```bash
cp .env.template .env       # điền giá trị (chỉ lần đầu)

# Backend: db → migrate (một lần) → api — một lệnh duy nhất, khởi động theo thứ tự
docker compose up -d

# Frontend (terminal khác)
npm install
npm run dev:web
```

API chạy ở `http://localhost:8000` (docs ở `/docs`), web ở `http://localhost:5173`.
Xem log với `docker compose logs -f api-service`.

## Yêu cầu

- Docker Desktop (compose v2)
- Node ≥ 22, npm ≥ 10 — npm workspaces bao gồm `apps/*`, `packages/sdk-js`, `packages/api-types`
- Python 3.12 + [uv](https://docs.astral.sh/uv/) — uv workspace bao gồm `services/*` và `packages/sdk-python`

## Cấu trúc repository

Chú thích trạng thái: ✅ đã implement · 🟡 khung/scaffold · ⏳ placeholder

```
apps/
  web-app/          ✅ React 19 + Vite + JS ES2024 + JSDoc + Zod + Tailwind 4 + MapLibre GL + TanStack Query
  mobile-app/       ⏳ React Native + Expo (dự kiến)
  docs/             ⏳ Site tài liệu cho người dùng (dự kiến)

services/
  api-service/         ✅ FastAPI (Python 3.12) — kiến trúc 5 tầng, bộ dự đoán ITU-R P.1812 + P.2108 Stage 1
  ml-service-predict/  ✅ Predict-ML:  Physics → LightGBM → SVGP
  ml-service-hmap/     🟡 Map-ML (heatmap, cho /map) — placeholder 
  worker-service/      ⏳ Celery + Redis/Valkey (dự kiến)
  tile-server/         ⏳ Go PMTiles server (dự kiến)

packages/
  api-types/        ⏳ Định nghĩa type sinh từ OpenAPI (chưa generate)
  sdk-python/       ⏳ Python client SDK
  sdk-js/           ⏳ JavaScript client SDK
  sdk-go/           ⏳ Go client SDK

migrations/         ✅ Alembic — 9 version (PostGIS + TimescaleDB hypertable) + seed_gateways.sql (11 gateway DNIIT + 2 HP)
ops/                Template reverse-proxy Nginx; thư mục Docker / Grafana đã chừa chỗ
docs/               Tài liệu kiến trúc & ADR 
core-logic/         Playbook thiết kế (kiến trúc hệ thống, quy tắc skill, ghi chú triết lý)
scripts/            seed_gateways.py, backfill_rdt.py, validate_stage1_itu.py
.github/workflows/  CI: api-service (lint+mypy+import-linter+pytest), docker-build smoke, web-app
```

## Kiến trúc

Tách 5 tầng nghiêm ngặt, enforce bởi `import-linter` (xem `.importlinter`):

```
Client → edge            (FastAPI router/middleware/serialization)
       → application     (use case, repository Protocol)
       → domain          (type thuần, không I/O)
       ↑ infrastructure  (repo cụ thể: PostGIS, R2, Valkey)
```

`application/` **không bao giờ** được import `infrastructure/`. `domain/` không được import bất kỳ tầng nào khác. CI cũng grep tìm chuỗi gắn tầng storage (`postgres`, `redis`, `valkey`, `s3`, `stage_4`, `GiST`, `BRIN`) bên trong `application/` và `domain/` — vi phạm sẽ fail build.

## Stack dữ liệu

- PostgreSQL 17 + PostGIS 3.5 + TimescaleDB 2.17 trong một image duy nhất (`timescale/timescaledb-ha:pg17-ts2.17-all`)
- Dữ liệu khảo sát đi vào hypertable `quarantine`; chỉ row đã validated mới được promote lên hypertable `training`
- Object storage: Cloudflare R2 (S3-compatible) — `model_version` là một phần của key prefix
- Cache: Valkey đang bị comment trong `docker-compose.yml`; chỉ bật khi traffic đủ lớn

## API

OpenAPI 3.1 spec ở `openapi.yaml`. Các endpoint đang live:

- `GET /healthz`, `GET /readyz`
- `POST /api/v1/coverage/predict` — dự đoán lai ghép Stage 1 + Stage 2 (RSSI/SNR/coverage/confidence/model_version). `model_version` là `stage1-...+stage2-...` khi Stage 2 active, là `stage1-...` trơn khi Stage 2 lỗi (chế độ degraded)
- `GET /api/v1/gateways` — danh mục gateway
- Ingestion webhook ChirpStack

Lỗi tuân theo RFC 7807 (`application/problem+json`). Versioning theo URI-path (`/api/v1`).

## Test

`.env.test` được commit chủ ý: thông tin đăng nhập (`lora_test_user:test_only_no_secrets`) chỉ cho phép truy cập DB test trống hoàn toàn cách ly khỏi dev.

```bash
# Setup DB test một lần
# → xem services/api-service/README.md §Setup test DB

# Chạy test
uv run pytest                                  # toàn bộ
uv run pytest tests/domain tests/application   # nhanh, không I/O
uv run pytest tests/integration -v             # cần DB test
```

## Lint / type-check

```bash
uv run ruff check .              # lint Python
uv run ruff format --check .     # format Python
uv run mypy services/api-service/src   # type-check strict (chạy từ repo root)
uv run lint-imports --config .importlinter   # tách 5 tầng
npm run lint                     # ESLint cho web-app
npm run jsdoc-check              # kiểm tra JSDoc qua tsc --noEmit
```

## CI (.github/workflows/ci.yml)

Ba job chạy trên push và PR vào `main`:

1. **api-service** — ruff lint+format, mypy strict, import-linter, grep no-leaky-strings, alembic upgrade trên service container TimescaleDB, seed gateway, pytest
2. **docker-build** — build Dockerfile multi-stage + smoke-start container
3. **web-app** — npm install, ESLint, JSDoc check (`tsc --checkJs`), Vite build


