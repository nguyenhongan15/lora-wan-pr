# LoRa Coverage Mapping Platform

Vietnam-first, donation-funded, fully-free LoRa network coverage mapping and ML-based path-loss prediction platform.

## Quick start (dev)

```bash
cp .env.template .env       # fill in values (first time only)

# Backend: db + migrations + api — single command, ordered startup
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
- Python 3.12 + [uv](https://docs.astral.sh/uv/) — uv workspace covers `services/*` and `packages/sdk-python`

## Repository layout

```
apps/
  web-app/          React 19 + Vite 7 + JavaScript ES2024 + JSDoc + Zod + Tailwind 4
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
  sdk-js/           JavaScript client SDK
  sdk-go/           Go client SDK (placeholder)

migrations/         Alembic migrations + seed data
ops/                Docker, Nginx, Grafana dashboards
docs/               Architecture & ADR docs
```

## Architecture

5-layer strict separation, enforced by `import-linter` (see `.importlinter`):

```
Client → edge            (FastAPI router/middleware/serialization)
       → application     (use cases, repository Protocols)
       → domain          (pure types, no I/O)
       ↑ infrastructure  (concrete repos: PostGIS, R2, Valkey)
```

`application/` **must never** import `infrastructure/`. `domain/` must not import any other layer. Violations fail CI — no exceptions.

## Test

`.env.test` is committed to the repo on purpose: the credentials (`lora_test_user:test_only_no_secrets`) only grant access to an empty test database that is fully isolated from dev.

```bash
# One-time test DB setup
# → see services/api-service/README.md §Setup test DB

# Run tests
uv run pytest                                  # full suite
uv run pytest tests/domain tests/application   # fast, no I/O
```

## Lint / type-check

```bash
uv run ruff check .              # Python lint
uv run mypy services/            # Python strict type-check
uv run lint-imports              # 5-layer separation
npm run lint                     # ESLint for web-app
npm run jsdoc-check              # JSDoc verified via tsc --noEmit
```

## Hard invariants

- Every `Prediction` carries a `Confidence`
- Every survey upload passes through `quarantine` before entering `training` (two separate hypertables)
- General donations never hit Google APIs
- `model_version` is part of the S3 key prefix
- v1 deployment target: Hetzner CPX31 ($16/mo), Docker Compose, total infra under $100/mo

## Documentation

- `services/api-service/README.md` — API service details and test setup
- `docs/` — architecture notes and ADRs
