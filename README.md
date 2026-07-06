# LoRa Coverage Mapping Platform

LoRaWAN coverage prediction cho khu vực Đà Nẵng (AS923-2, Vietnam). Stack: ITU-R P.1812-7 (Stage 1 physics) + ExtraTrees end-to-end (Stage 2 ML) + React/MapLibre web UI.

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
- DEM/DSM dữ liệu địa hình tại `LORA_DATA_DIR` (mặc định `E:/DATN/lora-data`); xem [§ Dữ liệu địa lý](#dữ-liệu-địa-lý-lora-data)

## Dữ liệu địa lý (`lora-data`)

Stage 1 (ITU-R P.1812) cần raster địa hình + landcover đặt tại `LORA_DATA_DIR` (mặc định cùng cấp với lora-coverage, mount read-only vào `api-service` + `ml-service`). **Không commit vào git** (nặng ~7 GB) — tải/​sinh theo bảng dưới. Layout:

```
lora-coverage/
lora-data/
  dem/                     ⬇  Copernicus GLO-30 DTM (mặt đất)      — BẮT BUỘC
  landcover/esa-worldcover/⬇  ESA WorldCover 10m 2021 v200         — BẮT BUỘC
  osm/vietnam-*.osm.pbf    ⬇  Geofabrik VN extract (building tags) — BẮT BUỘC (để build DSM)
  dem-surface/             ⚙  DSM = DTM + nhà OSM (native 30m)      — sinh cục bộ
  dem-surface-10m/         ⚙  DSM upsample 10m                      — sinh cục bộ (tùy chọn)
  dem-surface-built-up-only/⚙ DSM chỉ giữ nhà ở pixel built-up      — sinh cục bộ (tùy chọn)
  geo/                     ⚙  mount ghi-được cho Celery refresh_geo_data
  osm/urbanization_vn.tif  ◦  raster built-up (LORA_URBANIZATION_PATH) — tùy chọn/legacy
  climatic-zones/vn-zones.tif ◦ radio-climatic zone raster          — tùy chọn
  buildings-msft/          ◦  Microsoft GlobalMLBuildingFootprints  — tùy chọn (R&D)
  buildings-google/        ◦  Google Open Buildings v3              — tùy chọn (R&D)
  canopy-height/           ◦  Meta Canopy Height Model 1m           — tùy chọn (R&D)
  itu-digital-maps/        ◦  (rỗng) — bản đồ số P.453/P.836/P.1510 đã kèm trong crc-covlib
```

⬇ tải từ nguồn ngoài · ⚙ sinh cục bộ bằng script · ◦ tùy chọn, không cần để chạy demo.

### 1. DEM Copernicus GLO-30 (BẮT BUỘC) → `dem/`

DTM 30 m, WGS84 GeoTIFF. Nguồn: [OpenTopography](https://portal.opentopography.org/raster?opentopoID=OTSDEM.032021.4326.3) (chọn *Copernicus GLO-30*, vẽ bbox) hoặc AWS Open Data `s3://copernicus-dem-30m/`. Ba tile dự án dùng, đặt vào `lora-data/dem/`:

- `copernicus_glo30_danang.tif` — Đà Nẵng (khu vực chính, bbox ~107.9–108.5°E, 15.8–16.3°N)
- `copernicus_glo30_north_vn.tif` — Bắc Bộ (Hải Phòng / Hải Dương / Hà Nội — Stage 1 validation)
- `copernicus_glo30_south_vn.tif` — Nam Bộ

crc-covlib tự dò tile theo bbox của link nên filename tự do, miễn nằm trong `LORA_DEM_DIRECTORY`. `LORA_DEM_PATH` / `LORA_DEM_PATH_NORTH_VN` trong `.env` trỏ file cụ thể cho link-budget + validation.

### 2. ESA WorldCover (BẮT BUỘC cho landcover clutter) → `landcover/esa-worldcover/`

Landcover 10 m 2021 v200, tile 3°×3°. Nguồn: [esa-worldcover.org](https://esa-worldcover.org/en/data-access) hoặc AWS `s3://esa-worldcover/v200/2021/map/`. Central VN cần các tile `ESA_WorldCover_10m_2021_v200_N15E108_Map.tif` (Đà Nẵng) + `N18E105`, `N21E105`… (xem `landcover/esa-worldcover/` hiện có). Mapping WorldCover→P.1812 ở `infrastructure/itu/landcover_mapping.py`.

```bash
# ví dụ 1 tile qua AWS CLI (no-sign-request, bucket public)
aws s3 cp --no-sign-request \
  s3://esa-worldcover/v200/2021/map/ESA_WorldCover_10m_2021_v200_N15E108_Map.tif \
  E:/DATN/lora-data/landcover/esa-worldcover/
```

### 3. OSM PBF Việt Nam (BẮT BUỘC để build DSM) → `osm/`

Extract từ Geofabrik (cập nhật hằng ngày, có tag `building=*` để suy chiều cao). Dùng script có sẵn (stream + verify MD5 + atomic rename):

```bash
uv run --project services/api-service python scripts/fetch_osm_pbf.py \
  --out E:/DATN/lora-data/osm/vietnam-latest.osm.pbf
```

### 4. Sinh DSM cục bộ → `dem-surface/` (⚙, không tải)

DSM = DTM + chiều cao nhà OSM (P.1812 nhiễu xạ qua mái). Sinh từ dữ liệu bước 1 + 3:

```bash
# native 30m (mặc định — trỏ LORA_SURFACE_DEM_DIRECTORY vào đây)
uv run --project services/api-service python scripts/build_dsm.py \
  --dem-dir E:/DATN/lora-data/dem \
  --pbf     E:/DATN/lora-data/osm/vietnam-latest.osm.pbf \
  --out-dir E:/DATN/lora-data/dem-surface

# biến thể 10m (tùy chọn): thêm --pixel-size-m 10 --out-dir …/dem-surface-10m
# biến thể built-up-only: scripts/build_dsm_built_up_only.py (cần 1 tile ESA WorldCover)
```

Bỏ qua `dem-surface/` (để `LORA_SURFACE_DEM_DIRECTORY` rỗng) → P.1812 chạy DTM-only + P.2108 clutter thống kê, vẫn hoạt động nhưng kém chính xác ở đô thị đặc.

### 5. Tùy chọn (R&D, không cần để chạy)

- **buildings-msft/** — [Microsoft GlobalMLBuildingFootprints](https://github.com/microsoft/GlobalMLBuildingFootprints) (quadkey `*.geojsonl.gz`); **buildings-google/** — [Google Open Buildings v3](https://sites.research.google/open-buildings/); **canopy-height/** — [Meta Canopy Height Model 1m](https://registry.opendata.aws/dataforgood-fb-forests/). Dùng cho thí nghiệm nguồn surface thay thế, không nằm trong đường chạy production.
- **osm/urbanization_vn.tif**, **climatic-zones/vn-zones.tif** — raster phụ; `itu-digital-maps/` để rỗng (bản đồ số ITU đã kèm trong crc-covlib).

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


## NOTE
Dự án còn chưa hoàn thiện và vẫn đang tiếp tục phát triển, các thuật toán, model,... dự án sử dụng có thể được viết lại toàn bộ hoặc một phần trong tương lai, do đó nếu muốn phát triển riêng có thể clone về và tạo repo mới của riêng bạn.
Mọi thắc mắc xin liên hệ email: anngh2004@gmail.com