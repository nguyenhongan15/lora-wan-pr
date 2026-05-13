# LoRa Coverage Mapping Platform

Vietnam-first, donation-funded, AGPL-3.0 platform for LoRa network coverage querying, gateway directory and survey ingestion. Current release ships a Stage 1 + Stage 2 hybrid path-loss predictor: Stage 1 is a pure-math log-distance / Friis baseline (AS923-2 / 923 MHz, suburban exponent n=3.0, shadow fading σ=6.0 dB, reference distance d₀ = 100 m) and Stage 2 is a LightGBM residual model (Huber loss, Optuna 100-trial TPE, grid-based spatial GroupKFold CV) served by `ml-service-predict` over an internal bearer-authed HTTP. Calibration scope is Đà Nẵng-only (9.5k survey records); Stage 1 validity domain is outdoor 5–30 km (RMSE 4–5 dB in-distribution); Stage 2 corrects the <2 km bias and learns shadow-fading residuals (CV RMSE 4.58 dB). Stage 3 SVGP uncertainty quantification is deferred. Scope is intentionally Vietnam-only — multi-region (EU868 / US915 / CN470 / AS923-1/3/4) is deferred.

Version: **0.2.0**

## Quick start (dev)

```bash
cp .env.template .env       # fill in values (first time only)

# Backend: db → migrate (one-shot) → api — single command, ordered startup
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

Status legend: ✅ implemented · 🟡 skeleton/scaffold · ⏳ placeholder

```
apps/
  web-app/          ✅ React 19 + Vite + JS ES2024 + JSDoc + Zod + Tailwind 4 + MapLibre GL + TanStack Query
  mobile-app/       ⏳ React Native + Expo (planned)
  docs/             ⏳ User-facing docs site (planned)

services/
  api-service/         ✅ FastAPI (Python 3.12) — 5-layer architecture, Stage-1 log-distance predictor
  ml-service-predict/  ✅ Predict-ML (Option C: Physics → LightGBM → SVGP) — Stage 2 LightGBM residual live (Huber, Optuna, spatial GroupKFold), Phase 4+5 done; serves internal /residual called by api-service for /coverage/predict + /coverage/batch
  ml-service-hmap/     🟡 Map-ML (heatmap, for /map) — skeleton placeholder; owned by future contributor
  worker-service/      ⏳ Celery + Redis/Valkey (planned)
  tile-server/         ⏳ Go PMTiles server (planned)

packages/
  api-types/        ⏳ OpenAPI-generated type defs (not yet generated)
  sdk-python/       ⏳ Python client SDK
  sdk-js/           ⏳ JavaScript client SDK
  sdk-go/           ⏳ Go client SDK

migrations/         ✅ Alembic — 9 versions (PostGIS + TimescaleDB hypertables) + seed_gateways.sql (11 DNIIT + 2 HP gateways)
ops/                Nginx reverse-proxy template; Docker / Grafana dirs reserved
docs/               Architecture & ADR docs · ml-annguyen/ Stage 1 validation report
core-logic/         Design playbooks (system architecture, skill rules, philosophy notes)
scripts/            seed_gateways.py, backfill_rdt.py, fit_path_loss_exponent.sql, validate_stage1_danang.sql
.github/workflows/  CI: api-service (lint+mypy+import-linter+pytest), docker-build smoke, web-app
```

## Architecture

5-layer strict separation, enforced by `import-linter` (see `.importlinter`):

```
Client → edge            (FastAPI router/middleware/serialization)
       → application     (use cases, repository Protocols)
       → domain          (pure types, no I/O)
       ↑ infrastructure  (concrete repos: PostGIS, R2, Valkey)
```

`application/` **must never** import `infrastructure/`. `domain/` must not import any other layer. CI also greps for storage-tier strings (`postgres`, `redis`, `valkey`, `s3`, `stage_4`, `GiST`, `BRIN`) inside `application/` and `domain/` — violations fail the build.

## Data stack

- PostgreSQL 17 + PostGIS 3.5 + TimescaleDB 2.17 in a single image (`timescale/timescaledb-ha:pg17-ts2.17-all`)
- Survey data lands in `quarantine` hypertables; only validated rows are promoted to `training` hypertables
- Object storage: Cloudflare R2 (S3-compatible) — `model_version` is part of the key prefix
- Cache: Valkey is commented out in `docker-compose.yml`; enable only when traffic warrants it

## API

OpenAPI 3.1 spec at `openapi.yaml`. Live endpoints:

- `GET /healthz`, `GET /readyz`
- `POST /api/v1/coverage/predict` — Stage 1 + Stage 2 hybrid prediction (RSSI/SNR/coverage/confidence/model_version). `model_version` is `stage1-...+stage2-...` when Stage 2 active, plain `stage1-...` on Stage 2 failure (degraded mode)
- `GET /api/v1/gateways` — gateway directory
- ChirpStack webhook ingestion

Errors follow RFC 7807 (`application/problem+json`). Versioning is URI-path (`/api/v1`).

## Test

`.env.test` is committed on purpose: the credentials (`lora_test_user:test_only_no_secrets`) only grant access to an empty test database that is fully isolated from dev.

```bash
# One-time test DB setup
# → see services/api-service/README.md §Setup test DB

# Run tests
uv run pytest                                  # full suite
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
npm run jsdoc-check              # JSDoc verified via tsc --noEmit
```

## CI (.github/workflows/ci.yml)

Three jobs run on push and PR to `main`:

1. **api-service** — ruff lint+format, mypy strict, import-linter, no-leaky-strings grep, alembic upgrade against TimescaleDB service container, seed gateways, pytest
2. **docker-build** — multi-stage Dockerfile build + smoke-start the container
3. **web-app** — npm install, ESLint, JSDoc check (`tsc --checkJs`), Vite build

## Hard invariants

- Every `Prediction` carries a `Confidence` (enforced in `domain.coverage.Prediction.__post_init__`)
- Every survey upload passes through `quarantine` before entering `training` (two separate hypertables)
- Stage 1 calibration data is Đà Nẵng-only (bbox lat 15.8–16.3, lon 107.9–108.5); Hải Phòng & other regions are validation-only, never enter the fit
- Stage 1 validity domain: outdoor 5–30 km — predictions inside this domain are validated, predictions at < 2 km have a known +30 dB optimistic bias
- Stage 2 training scope mirrors Stage 1 (Đà Nẵng bbox, same time-split); residual target = `rssi_measured − rssi_stage1`; 11 features (geometry + DEM + OSM + pass-through device/gateway params); spatial CV uses grid-cell GroupKFold (0.025° cells) to prevent spatial autocorrelation leak
- Dataset split for ML hygiene: train+val random from Nov–Dec 2025 (88/12), test = Jan–Feb 2026 temporal hold-out — derived in-query, not persisted
- Stage 2 fail-safe: every Stage 2 failure path (timeout, 503, auth, network) falls back to Stage 1 prediction — Stage 2 never blocks `/coverage/predict`
- General donations never hit Google APIs
- `model_version` is part of the S3 key prefix
- v1 deployment target: Hetzner CPX31 (~$16/mo), Docker Compose, total infra under $100/mo

## Documentation

- `services/api-service/README.md` — API service details and test DB setup
- `services/ml-service-predict/README.md` — Predict-ML pipeline (Stage 2/3) build status and layout
- `u-work/ml-plan/plan-v1.md` — Predict-ML pipeline plan v1 (deep modules, phases, tradeoffs)
- `migrations/README.md` — migration conventions
- `docs/` — architecture notes and ADRs
- `docs/ml-annguyen/validation-tang1.md` — Stage 1 validation report, validity domain, per-split metrics
- `core-logic/main-logic/` — system architecture, business logic, design philosophy
- `core-logic/skills/` — REST/CRUD/DB/container/security/logging design rules

## License

AGPL-3.0

---