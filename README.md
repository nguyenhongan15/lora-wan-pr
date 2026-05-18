# LoRa Coverage Mapping Platform

## Quick start (dev)

```bash
cp .env.template .env       # fill in values (first time only)

# Backend: db → migrate (one-shot) → api — single command, starts in order
docker compose up -d

# Frontend (separate terminal)
npm install
npm run dev:web
```

API runs at `http://localhost:8000` (docs at `/docs`), web at `http://localhost:5173`.
Tail logs with `docker compose logs -f api-service`.

## Requirements

- Docker Desktop (compose v2)
- Node ≥ 22, npm ≥ 10 — npm workspaces cover `apps/*`, `packages/sdk-js`, `packages/api-types`
- Python 3.12 + [uv](https://docs.astral.sh/uv/) — uv workspace covers `services/api-service`, `services/worker-service`, `packages/sdk-python` (`services/ml-service` is empty pending the new ML developer; see **ml-service & Stage 2** below)

## Repository layout

Status legend: ✅ implemented · 🟡 scaffolded · ⏳ placeholder

```
apps/
  web-app/          ✅ React 19 + Vite + JS ES2024 + JSDoc + Zod + Tailwind 4 + MapLibre GL + TanStack Query
  mobile-app/       ⏳ React Native + Expo (planned)
  docs/             ⏳ End-user documentation site (planned)

services/
  api-service/         ✅ FastAPI (Python 3.12) — 5-layer architecture, ITU-R P.1812 + P.2108 Stage 1 predictor
  ml-service/          🟡 Empty — waiting for new ML dev to set up. Currently only README + `reference_wireless/`
  worker-service/      ⏳ Celery + Redis/Valkey (planned)
  tile-server/         ⏳ Go PMTiles server (planned)

packages/
  api-types/        ⏳ Types generated from OpenAPI (not generated yet)
  sdk-python/       ⏳ Python client SDK
  sdk-js/           ⏳ JavaScript client SDK
  sdk-go/           ⏳ Go client SDK

archive/
  stage2-lightgbm/  📦 Stage 2 LightGBM residual model the platform owner built before the handoff
                       (test RMSE 6.41 dB, frozen reference, not deployed). See its own README.

migrations/         ✅ Alembic — 9 versions (PostGIS + TimescaleDB hypertable) + seed_gateways.sql (11 DNIIT gateways + 2 HP)
ops/                Nginx reverse-proxy template; Docker / Grafana folders reserved
docs/               Architecture & ADR documentation
core-logic/         Design playbook (system architecture, skill rules, philosophy notes)
scripts/            seed_gateways.py, backfill_rdt.py, validate_stage1_itu.py, precompute_minsf.py, build_dsm.py
.github/workflows/  CI: api-service (lint+mypy+import-linter+pytest), docker-build smoke, web-app
```

## ml-service & Stage 2

Stage 2 (residual correction on top of Stage 1 ITU) is currently in a **handoff state to the new ML developer**. The platform owner built a LightGBM residual baseline before the handoff for personal experience — that baseline has been archived to `archive/stage2-lightgbm/` (committed to git along with its 3.3 MB artifact, test RMSE 6.41 dB) as a reference benchmark, **not deployed**.

- `services/ml-service/` currently contains only `README.md` + `reference_wireless/` (the XGBoost direct-RSSI project the new dev authored before joining this repo). The folder is empty and waiting — `pyproject.toml`, `Dockerfile`, and the HTTP contract are all the new dev's call.
- `api-service` runs Stage-1-only: `STAGE2_PREDICT_BASE_URL` is empty in `.env`, and responses carry `model_version = stage1-itu-p1812-v0.1.0`.
- When the new dev deploys their model, set `STAGE2_PREDICT_BASE_URL=http://ml-service:8001` (or whichever route/port they pick) and rebuild api-service.
- The min-SF coverage map is **pure physics** (Stage 1 ITU + ITU-R P.2108 clutter loss), owned by the platform owner — out of scope for ml-service.

Handoff details: `services/ml-service/README.md` (English). Archived model details: `archive/stage2-lightgbm/README.md`.

## Architecture

Strict 5-layer split, enforced by `import-linter` (see `.importlinter`):

```
Client → edge            (FastAPI router/middleware/serialization)
       → application     (use cases, repository Protocols)
       → domain          (pure types, no I/O)
       ↑ infrastructure  (concrete repos: PostGIS, R2, Valkey)
```

`application/` must **never** import `infrastructure/`. `domain/` must not import any other layer. CI also greps for storage-tier strings (`postgres`, `redis`, `valkey`, `s3`, `stage_4`, `GiST`, `BRIN`) inside `application/` and `domain/` — violations fail the build.

## Data stack

- PostgreSQL 17 + PostGIS 3.5 + TimescaleDB 2.17 in a single image (`timescale/timescaledb-ha:pg17-ts2.17-all`)
- Survey data lands in the `quarantine` hypertable; only validated rows are promoted to the `training` hypertable
- Object storage: Cloudflare R2 (S3-compatible) — `model_version` is part of the key prefix
- Cache: Valkey is commented out in `docker-compose.yml`; only enable it when traffic warrants

## API

OpenAPI 3.1 spec at `openapi.yaml`. Live endpoints:

- `GET /healthz`, `GET /readyz`
- `POST /api/v1/coverage/predict` — Stage 1 prediction (RSSI/SNR/coverage/confidence/model_version). `model_version` currently returns `stage1-itu-p1812-v0.1.0` because Stage 2 is shut down during the handoff (see **ml-service & Stage 2**). Once the new dev deploys a model, the response becomes `stage1-...+stage2-...`.
- `GET /api/v1/gateways` — gateway catalog
- ChirpStack ingestion webhook

Errors follow RFC 7807 (`application/problem+json`). Versioning is URI-path based (`/api/v1`).

## Test

`.env.test` is intentionally committed: the credentials (`lora_test_user:test_only_no_secrets`) only grant access to a fully empty test DB isolated from dev.

```bash
# One-time test DB setup
# → see services/api-service/README.md §Setup test DB

# Run tests
uv run pytest                                  # everything
uv run pytest tests/domain tests/application   # fast, no I/O
uv run pytest tests/integration -v             # needs test DB
```

## Lint / type-check

```bash
uv run ruff check .              # Python lint
uv run ruff format --check .     # Python format
uv run mypy services/api-service/src   # strict type-check (run from repo root)
uv run lint-imports --config .importlinter   # 5-layer separation
npm run lint                     # ESLint for web-app
npm run jsdoc-check              # JSDoc check via tsc --noEmit
```

## CI (.github/workflows/ci.yml)

Three jobs run on push and PRs against `main`:

1. **api-service** — ruff lint+format, mypy strict, import-linter, no-leaky-strings grep, alembic upgrade on a TimescaleDB service container, gateway seed, pytest
2. **docker-build** — multi-stage Dockerfile build + container smoke-start
3. **web-app** — npm install, ESLint, JSDoc check (`tsc --checkJs`), Vite build
