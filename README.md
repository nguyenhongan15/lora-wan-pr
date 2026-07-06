# LoRa Coverage Mapping Platform

LoRaWAN coverage prediction cho khu vực Đà Nẵng (AS923-2, Vietnam). Stack: ITU-R P.1812-7 (Stage 1 physics) + ExtraTrees end-to-end (Stage 2 ML) + React/MapLibre web UI.

## Quick start — máy mới (fresh clone)

### 0. Yêu cầu cài đặt

- Git
- Docker Desktop (compose v2) — Linux: Docker Engine + compose plugin
- Node ≥ 22, npm ≥ 10 — npm workspaces cho `apps/*`, `packages/sdk-js`, `packages/api-types`
- Python 3.12 + [uv](https://docs.astral.sh/uv/) — chỉ cần khi chạy scripts/test **ngoài** container (uv workspace cho `services/api-service`, `services/ml-service`, `services/worker-service`, `packages/sdk-python`)
- Port trống trên loopback: `5432` (db), `8000` (api), `8001` (ml), `5173` (web dev)

### 1. Clone + chuẩn bị dữ liệu địa hình

```bash
git clone <repo-url> lora-coverage
cd lora-coverage
```

Tạo thư mục `lora-data` (khuyến nghị cùng cấp với repo — **không có trong git**, ~7 GB đầy đủ) và tải **tối thiểu** 1 tile DEM Đà Nẵng để `/predict` chạy được:

```
lora-data/
  dem/copernicus_glo30_danang.tif    ← BẮT BUỘC (xem § Dữ liệu địa lý, mục 1)
```

Landcover / OSM PBF / DSM chỉ cần khi rebuild heatmap hoặc build DSM — tải sau theo [§ Dữ liệu địa lý](#dữ-liệu-địa-lý-lora-data).

### 2. Cấu hình `.env`

```bash
cp .env.template .env
```

Sửa trong `.env` (bắt buộc trước lần `docker compose up` đầu tiên):

| Biến | Giá trị |
|---|---|
| `LORA_DATA_DIR` | Đường dẫn tuyệt đối tới `lora-data` trên máy bạn (vd Windows `D:/work/lora-data`, Linux `/home/you/lora-data`) |
| `JWT_SECRET` | Sinh mới: `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `LINKING_FERNET_KEYS` | Sinh mới: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |

Các biến đường dẫn còn lại đang trỏ `E:/DATN/...` (`LORA_DEM_DIRECTORY`, `LORA_DEM_PATH`, `LORA_URBANIZATION_PATH`…) chỉ dùng khi chạy scripts **ngoài** container — đổi theo máy bạn khi cần. Container không đọc chúng: mọi service trong compose đọc `/data/...` qua volume mount `LORA_DATA_DIR`.

### 3. Backend (Docker)

```bash
docker compose up -d --build
# tự chạy theo thứ tự: db → migrate (alembic one-shot) → api-service + ml-service + celery-worker + cache
docker compose logs -f api-service ml-service   # chờ healthy
```

### 4. Frontend

```bash
npm install
npm run dev:web
```

FE mặc định gọi `http://localhost:8000` — không cần cấu hình gì thêm. Muốn đổi API URL: `cp apps/web-app/.env.example apps/web-app/.env.local` rồi sửa `VITE_API_BASE_URL`.

### 5. Kiểm tra

- **Tài khoản admin**: tài khoản **đầu tiên** đăng ký trên instance mới tự động là admin (kèm `email_verified=true` — instance mới chưa có SMTP). Các tài khoản sau là user thường, được admin cấp quyền qua trang quản trị. Lưu ý khi deploy public: đăng ký tài khoản của bạn ngay sau khi dựng xong, trước khi mở cho người khác.
- API: `http://localhost:8000/docs` — thử `GET /healthz`, `GET /api/v1/gateways` (phải trả 13 gateway)
- Web: `http://localhost:5173` — tab "Bản đồ phủ sóng":
  - mode `estimate` chạy ngay (GeoJSON tĩnh đã commit trong `apps/web-app/public/coverage/rssi/`)
  - mode `points` / `heatmap` sẽ **trống** trên máy mới — DB survey rỗng vì dump gốc (`r-dt/`) không commit
- ml-service: `http://localhost:8001` — mặc định trả 503 (model joblib không có trong git) → api-service tự fallback Stage 1, hệ vẫn hoạt động. Bật Stage 2: xem [§ Stage 2 ML](#stage-2-ml-extratrees-end-to-end).

### Những gì KHÔNG có trong git (gitignore) — cần biết khi clone mới

- `lora-data/` — raster địa hình ~7 GB; tải/sinh theo § Dữ liệu địa lý
- `*.joblib` — model Stage 2; train lại từ CSV đã commit (§ Stage 2 ML), thiếu thì hệ tự chạy Stage 1-only

## Dữ liệu địa lý (`lora-data`)

Stage 1 (ITU-R P.1812) cần raster địa hình đặt tại `LORA_DATA_DIR` (set trong `.env`, mount read-only vào `api-service` + `ml-service` + `celery-worker`). **Không commit vào git** (nặng ~7 GB) — tải/​sinh theo bảng dưới. Layout:

```
lora-coverage/
lora-data/
  dem/                     ⬇  Copernicus GLO-30 DTM (mặt đất)      — BẮT BUỘC (runtime /predict)
  landcover/esa-worldcover/⬇  ESA WorldCover 10m 2021 v200         — cần khi rebuild heatmap
  osm/vietnam-*.osm.pbf    ⬇  Geofabrik VN extract (building tags) — cần để build DSM
  dem-surface/             ⚙  DSM = DTM + nhà OSM (native 30m)      — sinh cục bộ (khuyến nghị)
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

**Tối thiểu để chạy demo**: chỉ cần `dem/` (tile Đà Nẵng). Landcover dùng bởi `precompute_rssi_heatmap.py` (rebuild heatmap qua admin/Celery); OSM PBF + DSM nâng độ chính xác đô thị nhưng không bắt buộc.

### 1. DEM Copernicus GLO-30 (BẮT BUỘC) → `dem/`

DTM 30 m, WGS84 GeoTIFF. Nguồn: [OpenTopography](https://portal.opentopography.org/raster?opentopoID=OTSDEM.032021.4326.3) (chọn *Copernicus GLO-30*, vẽ bbox) hoặc AWS Open Data `s3://copernicus-dem-30m/`. Tile dự án dùng, đặt vào `lora-data/dem/`:

- `copernicus_glo30_danang.tif` — Đà Nẵng (khu vực chính, bbox ~107.9–108.5°E, 15.8–16.3°N) — **đủ để chạy demo**
- `copernicus_glo30_north_vn.tif` — Bắc Bộ (Hải Phòng / Hải Dương / Hà Nội) — chỉ cần cho Stage 1 validation
- `copernicus_glo30_south_vn.tif` — Nam Bộ — tùy chọn

crc-covlib tự dò tile theo bbox của link nên filename tự do, miễn nằm trong `LORA_DEM_DIRECTORY`. `LORA_DEM_PATH` / `LORA_DEM_PATH_NORTH_VN` trong `.env` trỏ file cụ thể cho link-budget + validation (chỉ dùng bởi scripts ngoài container).

### 2. ESA WorldCover (cần khi rebuild heatmap) → `landcover/esa-worldcover/`

Landcover 10 m 2021 v200, tile 3°×3°. Nguồn: [esa-worldcover.org](https://esa-worldcover.org/en/data-access) hoặc AWS `s3://esa-worldcover/v200/2021/map/`. Đà Nẵng cần tile `ESA_WorldCover_10m_2021_v200_N15E108_Map.tif`; Bắc Bộ thêm `N18E105`, `N21E105`… Mapping WorldCover→P.1812 ở `infrastructure/itu/landcover_mapping.py`.

```bash
# ví dụ 1 tile qua AWS CLI (no-sign-request, bucket public); thay <LORA_DATA_DIR> bằng đường dẫn thật
aws s3 cp --no-sign-request \
  s3://esa-worldcover/v200/2021/map/ESA_WorldCover_10m_2021_v200_N15E108_Map.tif \
  <LORA_DATA_DIR>/landcover/esa-worldcover/
```

### 3. OSM PBF Việt Nam (cần để build DSM) → `osm/`

Extract từ Geofabrik (cập nhật hằng ngày, có tag `building=*` để suy chiều cao). Dùng script có sẵn (stream + verify MD5 + atomic rename):

```bash
uv run --project services/api-service python scripts/fetch_osm_pbf.py \
  --out <LORA_DATA_DIR>/osm/vietnam-latest.osm.pbf
```

### 4. Sinh DSM cục bộ → `dem-surface/` (⚙, không tải)

DSM = DTM + chiều cao nhà OSM (P.1812 nhiễu xạ qua mái). Sinh từ dữ liệu bước 1 + 3:

```bash
# native 30m (mặc định — trỏ LORA_SURFACE_DEM_DIRECTORY vào đây)
uv run --project services/api-service python scripts/build_dsm.py \
  --dem-dir <LORA_DATA_DIR>/dem \
  --pbf     <LORA_DATA_DIR>/osm/vietnam-latest.osm.pbf \
  --out-dir <LORA_DATA_DIR>/dem-surface

# biến thể 10m (tùy chọn): thêm --pixel-size-m 10 --out-dir …/dem-surface-10m
# biến thể built-up-only: scripts/build_dsm_built_up_only.py (cần 1 tile ESA WorldCover)
```

Bỏ qua `dem-surface/` (chưa build) → P.1812 chạy DTM-only + P.2108 clutter thống kê, vẫn hoạt động nhưng kém chính xác ở đô thị đặc.

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

migrations/         ✅ Alembic — 35 revisions (PostGIS + TimescaleDB hypertable + auth + ML registry
                       + gateway quarantine/state override)
                       Latest: 0035_gateway_rssi_bias.
                       Seed gateway: THỦ CÔNG qua migrations/seeds/seed_gateways.sql (11 gw DNIIT + 2 HP)
ops/                Nginx reverse-proxy template
docs/               (gitignore, local-only) Báo cáo tiến độ + ADR
core-logic/         (gitignore, local-only) Design playbook + skill rules
vendor/             ✅ crc_covlib wheel (đã commit — không cần build lại)
scripts/            Stage 1 fit/validate, precompute RSSI heatmap, DSM build, ML train, seed
.github/workflows/  CI: api-service (lint+mypy+import-linter+pytest), docker-build smoke, web-app
```

## Stage 2 ML (ExtraTrees end-to-end)

- **Active model**: `stage2-et-v0.7.0` (ExtraTreesRegressor, joblib tại `services/ml-service/data/extra_trees_model.joblib`)
- **Model artifact KHÔNG có trong git** (`*.joblib` gitignored). Máy mới mặc định: ml-service load dummy stub → `/residual` trả 503 → api-service fallback Stage 1-only. Hệ vẫn chạy đầy đủ, chỉ thiếu lớp tinh chỉnh ML.
- **Bật Stage 2 trên máy mới** — train lại từ CSV đã commit (`services/ml-service/data/training/processed/devices_history_full.csv`, đã có sẵn features + `data_split`):

  ```bash
  uv sync    # 1 lần — cài Python workspace
  uv run --project services/ml-service python services/ml-service/scripts/train_extra_trees.py
  # → ghi services/ml-service/data/extra_trees_model.joblib (+ metadata)
  ```

  Rồi set trong `.env`:

  ```
  STAGE2_PREDICT_BASE_URL=http://ml-service:8001
  LORA_ML_MODEL_PATH=/app/data/extra_trees_model.joblib
  ```

  và recreate: `docker compose up -d ml-service api-service`. Khi active, api-service trả `model_version = "stage1-itu-p1812-v0.1.0+stage2-et-v0.7.0"`.
- **Features (21)**: geometry (log_distance, delta_lat/lon, angle, elevation_angle) + terrain DEM (slope, roughness, terrain_*) + Fresnel clearance + residential_ratio + frequency + spreading_factor + gateway (one-hot)
- **Spatial hold-out** (H3 res-8 + session split, không rò rỉ): **test RMSE 6.32 dB**, MAE 4.75, R² ≈ −0.08 — khái quát hoá không gian còn YẾU (dữ liệu hẹp 13 gw); chạy như lớp tinh chỉnh trên Stage 1, fail thì fallback Stage 1. Chi tiết: `services/ml-service/README.md` §2.
- **Auth**: shared bearer token qua `LORA_STAGE2_AUTH_TOKEN` (`.env.template` có giá trị dev sẵn).
- Chi tiết train + reproduce: `services/ml-service/README.md`, `scripts/build_training_csv.py` + `services/ml-service/scripts/train_extra_trees.py`.
- **Legacy XGBoost residual** (`stage2-xgb-v0.6.0`, hold-out 10.59 dB) đã retire vào `archive/` (rollback, không deploy).

## Coverage map modes (web-app)

Tab "Bản đồ phủ sóng" có 3 chế độ:

| Mode | Mô tả | Tin cậy | Máy mới |
|---|---|---|---|
| `points` | Survey điểm đo (raw walk-measure data) | Tuyệt đối — đo thực tế | Trống (DB survey rỗng, dump `r-dt/` không commit) |
| `heatmap` | Heat density survey points | Hiển thị mật độ | Trống (như trên) |
| `estimate` | **Composite RSSI** max qua 13 gateway (Stage 1 + Stage 2) | Beta — RMSE ±10 dB (~1 bin) | ✅ chạy ngay (GeoJSON tĩnh đã commit) |

GeoJSON tĩnh được pre-generate trong `apps/web-app/public/coverage/rssi/`. Rebuild qua admin (Celery `rebuild_coverage_map`) — cần DEM + landcover trong `lora-data`.

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
  build_dsm.py                    # Build DSM raster (Copernicus + OSM buildings)
  validate_stage1_itu.py          # Stage 1 hold-out validation
  seed_gateways.py                # Seed gw từ ChirpStack JSON (cần r-dt/ — máy gốc only;
                                  #   máy mới dùng migrations/seeds/seed_gateways.sql)
  backfill_gateway_noise_floor.py # Per-gw noise floor migration helper

services/ml-service/scripts/
  train_extra_trees.py            # Train Stage 2 ExtraTrees (đã chuyển vào ml-service)
```

Scripts chạy ngoài container cần Python workspace: `uv sync` 1 lần ở repo root.

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

1. **api-service** — ruff lint+format, mypy strict, import-linter, no-leaky-strings grep, alembic upgrade trên TimescaleDB service container, pytest
2. **docker-build** — multi-stage Dockerfile build + container smoke-start
3. **web-app** — npm install, ESLint, JSDoc check (`tsc --checkJs`), Vite build


## NOTE
Dự án còn chưa hoàn thiện và vẫn đang tiếp tục phát triển, các thuật toán, model,... dự án sử dụng có thể được viết lại toàn bộ hoặc một phần trong tương lai, do đó nếu muốn phát triển riêng có thể clone về và tạo repo mới của riêng bạn.
Mọi thắc mắc xin liên hệ email: anngh2004@gmail.com
