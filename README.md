# LoRa Coverage Mapping Platform

LoRaWAN coverage prediction cho khu vực Đà Nẵng (AS923-2, Vietnam). Stack: ITU-R P.1812-7 + P.2108 (Stage 1 physics) + ExtraTrees end-to-end (Stage 2 ML) + React/MapLibre web UI.

## Quick start (dev)

```bash
cp .env.template .env       # fill in values (first time only)

# Backend: db → migrate (one-shot) → api + ml-service — single command, starts in order
docker compose up -d

# Frontend (separate terminal)
npm install
npm run dev:web
```

API: `http://localhost:8000` (docs `/docs`).  Web: `http://localhost:5173`.  ml-service: `http://localhost:8001`.
Tail logs: `docker compose logs -f api-service ml-service`.

## Requirements

- Docker Desktop (compose v2)
- Node ≥ 22, npm ≥ 10 — npm workspaces cho `apps/*`, `packages/sdk-js`, `packages/api-types`
- Python 3.12 + [uv](https://docs.astral.sh/uv/) — uv workspace cho `services/api-service`, `services/ml-service`, `services/worker-service`, `packages/sdk-python`
- DEM/DSM dữ liệu địa hình tại `LORA_DATA_DIR` (mặc định `E:/DATN/lora-data`); xem `scripts/build_dsm.py`

## Repository layout

Status: ✅ active · 🟡 scaffolded · ⏳ placeholder

```
apps/
  web-app/          ✅ React 19 + Vite + JS ES2024 + JSDoc + Zod + Tailwind 4 + MapLibre GL + TanStack Query
  mobile-app/       ⏳ React Native + Expo (planned, post-v1)
  docs/             ⏳ End-user documentation site (planned)

services/
  api-service/      ✅ FastAPI (Python 3.12), 5-layer architecture, Stage 1 ITU-R P.1812 + P.2108
  ml-service/       ✅ FastAPI Stage 2 ExtraTrees end-to-end (v0.7.0). Active when STAGE2_PREDICT_BASE_URL set
  worker-service/   ⏳ Celery + Redis/Valkey (planned)
  tile-server/      ⏳ Go PMTiles server (planned)

packages/
  api-types/        ⏳ Types từ OpenAPI (chưa generate)
  sdk-python/       ⏳ Python client SDK (planned)
  sdk-js/           ⏳ JS client SDK (planned)
  sdk-go/           ⏳ Go client SDK (planned)

archive/            (gitignore, local-only — frozen references, không deploy)
  stage2-lightgbm/  📦 Stage 2 LightGBM cũ (RMSE 6.41 dB hold-out)
  (XGBoost residual cũ: train_residual_model.py, retrain_stage2.sh, stage2_xgb.joblib + thí nghiệm R&D)

migrations/         ✅ Alembic — 20 revisions (PostGIS + TimescaleDB hypertable + auth + ML registry)
                       Latest: 0020_gateway_noise_floor. Seed: 11 gw DNIIT Đà Nẵng + 2 Hải Phòng pilot
ops/                Nginx reverse-proxy template
docs/               Báo cáo tiến độ + ADR (mới có 1 file)
core-logic/         Design playbook + skill rules
scripts/            Stage 1 fit/validate, precompute RSSI heatmap, DSM build, ML train, seed
.github/workflows/  CI: api-service (lint+mypy+import-linter+pytest), docker-build smoke, web-app
```

## Stage 2 ML (ExtraTrees end-to-end)

- **Active model**: `stage2-et-v0.7.0` (ExtraTreesRegressor, joblib in `services/ml-service/data/extra_trees_model.joblib`)
- **Features (21)**: geometry (log_distance, delta_lat/lon, angle, elevation_angle) + terrain DEM (slope, roughness, terrain_*) + Fresnel clearance + residential_ratio + frequency + spreading_factor + gateway (one-hot)
- **Spatial hold-out** (H3 res-8 + session split, không rò rỉ): **test RMSE 6.32 dB**, MAE 4.75, R² ≈ −0.08 — khái quát hoá không gian còn YẾU (dữ liệu hẹp 13 gw); chạy như lớp tinh chỉnh trên Stage 1, fail thì fallback Stage 1. Chi tiết: `services/ml-service/README.md` §2.
- **Wiring**: set `STAGE2_PREDICT_BASE_URL=http://ml-service:8001` trong `.env` → api-service tự động gọi `/residual` và trả `model_version = "stage1-itu-p1812-v0.1.0+stage2-et-v0.7.0"`. Để trống → Stage 1 only fallback.
- **Auth**: shared bearer token qua `LORA_STAGE2_AUTH_TOKEN`.
- Chi tiết train + reproduce: `services/ml-service/README.md`, `scripts/build_training_csv.py` + `services/ml-service/scripts/train_extra_trees.py`.
- **Legacy XGBoost residual** (`stage2-xgb-v0.6.0`, hold-out 10.59 dB) đã retire vào `archive/` (rollback, không deploy).

## Coverage map modes (web-app)

Tab "Bản đồ phủ sóng" có 3 chế độ:

| Mode | Mô tả | Tin cậy |
|---|---|---|
| `points` | Survey điểm đo (raw walk-measure data) | Tuyệt đối — đo thực tế |
| `heatmap` | Heat density survey points | Hiển thị mật độ |
| `estimate` | **Composite RSSI** max qua 13 gateway (Stage 1 + Stage 2) | Beta — RMSE ±10 dB (~1 bin) |

GeoJSON tĩnh được pre-generate trong `apps/web-app/public/coverage/rssi/`.

## Architecture

5-layer split, enforced by `import-linter` (`.importlinter`):

```
Client → edge            (FastAPI router/middleware/serialization)
       → application     (use cases, repository Protocols)
       → domain          (pure types, no I/O)
       ↑ infrastructure  (concrete repos: PostGIS, R2, Valkey)
```

`application/` **không bao giờ** import `infrastructure/`. `domain/` không import bất kỳ tầng nào khác. CI cũng grep storage-tier strings (`postgres`, `redis`, `valkey`, `s3`, `stage_4`, `GiST`, `BRIN`) bên trong `application/` và `domain/` — vi phạm fail build.

## Data stack

- PostgreSQL 17 + PostGIS 3.5 + TimescaleDB 2.17 trong 1 image (`timescale/timescaledb-ha:pg17-ts2.17-all`)
- Survey data → hypertable `ts.survey_quarantine`; row được promote → `ts.survey_training`
- Object storage: Cloudflare R2 (S3-compatible); `model_version` là phần key prefix
- Cache: Valkey 8 (active — rate-limit + session)

## API

OpenAPI 3.1 spec: `openapi.yaml`. Endpoint chính:

- `GET /healthz`, `GET /readyz`
- `POST /api/v1/coverage/predict` — Stage 1+2 prediction (RSSI/SNR/coverage/confidence/model_version)
- `GET /api/v1/gateways` — gateway catalog (11 DNIIT + 2 HP)
- `POST /api/v1/auth/{register,login,refresh,logout}` — JWT auth (HttpOnly cookie refresh)
- `POST /api/v1/admin/*` — admin queue (review pending contributions)
- ChirpStack webhook ingestion

Lỗi theo RFC 7807 (`application/problem+json`). Versioning URI-path (`/api/v1`).

## Scripts (chính)

```
scripts/                          # chỉ mục đầy đủ theo nhóm: scripts/README.md
  precompute_rssi_heatmap.py      # Composite RSSI heatmap (Stage 1 + Stage 2)
  build_training_csv.py           # Build CSV train từ ts.survey_training (+ data_split H3)
  eval_extra_trees_holdout.py     # Eval H3 spatial hold-out (Celery retrain)
  build_dsm.py                    # Build DSM raster (Copernicus + Google buildings + landcover)
  validate_stage1_itu.py          # Stage 1 hold-out validation
  seed_gateways.py                # Seed gw từ CSV vào geo.gateways
  backfill_gateway_noise_floor.py # Per-gw noise floor migration helper

services/ml-service/scripts/
  train_extra_trees.py            # Train Stage 2 ExtraTrees (đã chuyển vào ml-service)
```

## Test

`.env.test` được commit có chủ ý: credential (`lora_test_user:test_only_no_secrets`) chỉ access DB test rỗng, tách khỏi dev.

```bash
# Setup DB test (1 lần)
# → xem services/api-service/README.md §Setup DB test

uv run pytest                                  # everything
uv run pytest tests/domain tests/application   # nhanh, không I/O
uv run pytest tests/integration -v             # cần DB test
```

## Lint / type-check

```bash
uv run ruff check .              # Python lint
uv run ruff format --check .     # Python format
uv run mypy services/api-service/src   # strict type-check (chạy từ repo root)
uv run lint-imports --config .importlinter   # 5-layer separation
npm run lint                     # ESLint web-app
npm run jsdoc-check              # JSDoc check qua tsc --noEmit
```

## CI (.github/workflows/ci.yml)

Ba job chạy trên push & PR vào `main`:

1. **api-service** — ruff lint+format, mypy strict, import-linter, no-leaky-strings grep, alembic upgrade trên TimescaleDB service container, gateway seed, pytest
2. **docker-build** — multi-stage Dockerfile build + container smoke-start
3. **web-app** — npm install, ESLint, JSDoc check (`tsc --checkJs`), Vite build


