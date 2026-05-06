# LoRa Coverage Mapping Platform

Vietnam-first, donation-funded, AGPL-3.0 platform for LoRa network coverage querying, gateway directory and survey ingestion. Current release ships a pure-math log-distance path-loss predictor; ML stages (residual, ensemble, Bayesian) are planned but not yet implemented.

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
  api-service/      ✅ FastAPI (Python 3.12) — 5-layer architecture, Stage-1 log-distance predictor
  ml-service/       🟡 ONNX/LightGBM/PyTorch scaffold — no models trained yet
  worker-service/   ⏳ Celery + Redis/Valkey (planned)
  tile-server/      ⏳ Go PMTiles server (planned)

packages/
  api-types/        ⏳ OpenAPI-generated type defs (not yet generated)
  sdk-python/       ⏳ Python client SDK
  sdk-js/           ⏳ JavaScript client SDK
  sdk-go/           ⏳ Go client SDK

migrations/         ✅ Alembic — 5 versions (PostGIS + TimescaleDB hypertables) + seed_gateways.sql
ops/                Nginx reverse-proxy template; Docker / Grafana dirs reserved
docs/               Architecture & ADR docs
core-logic/         Design playbooks (system architecture, skill rules, philosophy notes)
scripts/            seed_gateways.py, backfill_rdt.py
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
- `POST /api/v1/coverage/predict` — Stage-1 log-distance prediction (RSSI/SNR/coverage/confidence/model_version)
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
- General donations never hit Google APIs
- `model_version` is part of the S3 key prefix
- v1 deployment target: Hetzner CPX31 (~$16/mo), Docker Compose, total infra under $100/mo

## Documentation

- `services/api-service/README.md` — API service details and test DB setup
- `migrations/README.md` — migration conventions
- `docs/` — architecture notes and ADRs
- `core-logic/main-logic/` — system architecture, business logic, design philosophy
- `core-logic/skills/` — REST/CRUD/DB/container/security/logging design rules

## License

AGPL-3.0

---

# Onboarding guide for Machine Learning developers

This section is for developers invited to the repo (as Collaborators) to work on the ML module. Read it carefully before your first commit.

## 1. Context before you start

- The project **does not yet have a real ML model in production**. The endpoint `POST /api/v1/coverage/predict` currently uses a pure-math log-distance formula in `services/api-service/src/lora_coverage_api/application/path_loss.py` (Stage 1). Treat this as the baseline.
- ML roadmap: train Stage 2 (LightGBM residual) → Stage 3 (ResNet-18 CNN on rasters) → Stage 4 (Bayesian / MC-dropout ensemble), export to ONNX, ship into `services/ml-service/`.
- **Trigger to start Stage 2**: at least 5,000 real survey points for at least one region promoted into the `ts.survey_training` hypertable. If data is not yet sufficient, focus on pipeline code + offline notebooks first — do not rush into training a model.
- Everything must be free / low-cost (target: under $100/month for the whole infra). Do not pull in heavy dependencies unless absolutely necessary.

## 2. Set up the dev environment (first time)

```bash
# Accept the GitHub invite in your email → clone
git clone https://github.com/<owner>/lora-coverage.git
cd lora-coverage
git config user.name  "<Your name>"
git config user.email "<email>"
```

Install prerequisites:

| Tool | Version | Notes |
|------|---------|-------|
| Docker Desktop | compose v2 | runs db + api |
| Python | 3.12 | exact version required |
| uv | latest | `pip install uv` or `winget install astral-sh.uv` |
| Node | ≥ 22 | only needed if you want to run the web UI to view predictions |
| git, gh | any | `gh auth login` recommended |

Verify:

```bash
docker --version && docker compose version
python --version    # must be 3.12.x
uv --version
```

## 3. Bring up the backend + install deps

```bash
cp .env.template .env             # fill in POSTGRES_*, CORS_ALLOWED_ORIGINS

docker compose up -d              # db → migrate (alembic) → api-service
docker compose logs -f api-service   # wait for "Uvicorn running on 0.0.0.0:8000"

uv sync --all-extras --all-groups # install Python deps for the whole workspace, including ml-service
```

Sanity check:

```bash
curl http://localhost:8000/healthz                 # {"status":"ok"}
curl http://localhost:8000/api/v1/gateways | head  # gateway directory has been seeded
```

## 4. Set up the test DB (one-time, required to run pytest)

Per `services/api-service/README.md`:

```bash
docker exec lora-wan-db psql -U lora_user -d postgres -c \
  "CREATE ROLE lora_test_user LOGIN SUPERUSER PASSWORD 'test_only_no_secrets';"
docker exec lora-wan-db psql -U lora_user -d postgres -c \
  "CREATE DATABASE lora_coverage_test OWNER lora_test_user;"

DATABASE_URL=postgresql+psycopg://lora_test_user:test_only_no_secrets@localhost:5432/lora_coverage_test \
  uv run alembic -c migrations/alembic.ini upgrade head

docker exec -i lora-wan-db psql -U lora_test_user -d lora_coverage_test \
  < migrations/seeds/seed_gateways.sql
```

## 5. Where the ML developer works

**All ML code lives inside `services/ml-service/`. Do not touch anywhere else.**

```
services/ml-service/
├── src/lora_coverage_ml/
│   ├── api.py                    # FastAPI /predict — internal entrypoint
│   ├── router.py                 # stage selection + auto-fallback
│   ├── stages/
│   │   ├── stage1_empirical.py   # log-distance (ported from api-service when needed)
│   │   ├── stage2_lightgbm.py    # ← TOP PRIORITY
│   │   ├── stage3_cnn.py         # ResNet-18 ONNX
│   │   └── stage4_bayesian.py    # ensemble / MC-dropout
│   ├── pipeline/
│   │   ├── tabular_features.py   # feature engineering for Stage 2
│   │   └── raster_features.py    # feature engineering for Stage 3/4 (DEM, clutter)
│   └── calibration/
│       └── ece_monitor.py        # ECE > 0.08 → alert
├── data/dem/                     # SRTM tiles (n15-16/e107-108.hgt already present)
├── models/                       # ONNX artifacts (gitignored, R2-backed)
├── tests/                        # currently empty — write tests as you add code
├── Dockerfile, pyproject.toml
└── README.md
```

Code-location rules:

- ❌ **Do not** put ML logic inside `services/api-service/`. CI greps for strings like `stage_4`, `s3`, ... in `application/` and `domain/` and will fail the build.
- ❌ **Do not** put training scripts in `scripts/` at the repo root (that folder is for ops scripts like `seed_gateways.py`). Create `services/ml-service/src/lora_coverage_ml/training/` or a similar subfolder.
- ❌ **Do not** commit datasets / weights / `.hgt` / ONNX files into git. `.gitignore` must cover `services/ml-service/data/` and `services/ml-service/models/`.
- ❌ **Do not** modify `.env.test`. If you need ML-specific env vars, use the `ML_` prefix in your local `.env`.
- ✅ Exploratory notebooks go in `services/ml-service/notebooks/` (create it). Gitignore outputs; only commit `.ipynb` files with cleared cell output.

## 6. Documents to read before writing code

In priority order:

1. `services/ml-service/README.md` — detailed spec for this module.
2. `core-logic/main-logic/system-architecture.md` §3.5 — the role of ml-service in the overall system.
3. `core-logic/main-logic/core-feature.md` — module decomposition (MeasurementStore → CoverageSurface → MapRenderer).
4. `services/api-service/src/lora_coverage_api/domain/coverage.py` — types `Prediction`, `Confidence`, `CoverageStatus`. The ml-service output must conform to this schema.
5. `services/api-service/src/lora_coverage_api/application/path_loss.py` — current Stage 1; Stage 2 will learn the residual on top of it.
6. `migrations/versions/0003_ts_survey_hypertables.py` — schema for `ts.survey_quarantine` and `ts.survey_training` (the training data source).
7. `core-logic/main-logic/a-philosophy-of-software-design.md` — design philosophy (deep modules, information hiding) that applies to ml-service too.

## 7. Hard invariants ML must respect

- **Every `Prediction` must carry a complete `Confidence`** (lower/upper/level). If a model cannot produce uncertainty, fall back to a lower stage — never return `null`.
- **Auto-fallback**: if Stage N fails to load (missing ONNX file, OOM, exception), `router.py` must fall back to Stage N-1 transparently for the caller.
- **`model_version`** must appear in the response and be part of the S3/R2 key prefix when storing artifacts: `lora-models-prod/stage=2/region=danang/calib=v1/model.onnx`.
- **Train only on `ts.survey_training`**, never read from `ts.survey_quarantine`. Validation must be split off from training (group split by gateway or by time).
- **Calibration**: track ECE (Expected Calibration Error) via `calibration/ece_monitor.py`. ECE > 0.08 → log a warning and consider retraining.
- **No Google Maps / paid APIs** in the training pipeline (donation-funded rule).
- **Do not expose ml-service to the public Internet**. `api-service` calls it over the internal Docker network only.

## 8. Local run & test workflow for ML

```bash
# Pull workspace deps for ml-service
uv sync --all-extras --all-groups

# Run ml-service standalone (once real code exists)
uv run --project services/ml-service uvicorn lora_coverage_ml.api:app --port 8001 --reload

# Tests
uv run pytest services/ml-service/tests -v

# Lint + type check (CI will run these)
uv run ruff check services/ml-service
uv run ruff format --check services/ml-service
uv run mypy services/ml-service/src
```

When you are ready to integrate with api-service: add the env var `ML_SERVICE_URL=http://ml-service:8001` and modify `coverage_service.py` to call over HTTP instead of invoking `Stage1LogDistanceModel` directly. **Ship this as a separate PR**, not bundled with the model-training PR.

## 9. How to add a new stage (Stage 2 example)

1. **EDA + feature engineering**: notebook in `services/ml-service/notebooks/`. Output: list of selected features + reasoning.
2. **Implement** `pipeline/tabular_features.py` — a pure function `(survey_row) → features dict`. Cover with unit tests.
3. **Train offline** on `ts.survey_training` (use a read-only DB connection). Script lives in `src/lora_coverage_ml/training/train_stage2.py`. Save metrics (MAE, RMSE, ECE) as a JSON file alongside the model.
4. **Export to ONNX** via `onnxmltools` or `skl2onnx`. Verify inference parity by comparing Python vs ONNX outputs (tolerance < 1e-4).
5. **Drop the artifact**: `services/ml-service/models/stage2/region=<x>/calib=v1/model.onnx` for local; in production, sync up to R2.
6. **Wire the endpoint** `/predict` in `api.py` + `router.py` (fall back to Stage 1 if Stage 2 fails).
7. **Calibration check**: run `ece_monitor.py` on a hold-out set; attach the metrics to the PR description.
8. **PRs**: one PR for pipeline + training, one for serving, one for the api-service integration. Do not bundle them.

## 10. CI checklist before pushing

CI today only covers api-service, docker-build, and web-app. Once ml-service has real code, the ML developer must ensure the following pass locally (a dedicated CI job will be added later):

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy services/ml-service/src
uv run pytest services/ml-service/tests
```

Open a PR only after everything passes. `main` is branch-protected — every change must go through a PR with green CI and at least one review.

## 11. Troubleshooting

- **Port 5432 already in use**: stop your local Postgres, or change the port mapping in `docker-compose.yml`.
- **`CREATE EXTENSION` permission denied**: the test role needs `SUPERUSER` (see step 4).
- **OOM during local training**: lower LightGBM `n_estimators` or subsample the data; production training should run on a separate VPS, not on the API server.
- **ONNX inference differs from Python**: check input tensor dtype (float32 vs float64) and shape.
- **Don't know where the data is**: run `psql $DATABASE_URL`, then `\dt ts.*` to inspect hypertables. If real data is not yet available, generate synthetic surveys (log-distance + Gaussian noise) to exercise the pipeline first.

For anything else, open an issue or message the repo owner directly.

