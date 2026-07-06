# LoRa Coverage Mapping Platform
Xây dựng bản đồ và ước lượng vùng phủ mạng không dây LPWAN trên địa bàn thành phố Đà Nẵng

## Quick start

```bash
git clone <repo-url> lora-coverage
cd lora-coverage
./setup.sh        # macOS / Linux / Git Bash — Windows: setup.bat
```

Script tự kiểm tra và **cài công cụ thiếu** (Git, Docker, Node ≥ 22 — qua winget/Homebrew/apt tùy OS; Docker Desktop lần đầu cần bấm chấp nhận điều khoản, Linux cần sudo). Máy cần **~8 GB RAM**, port trống `5432`/`8000`/`8001`/`5173`.

### Sau khi setup xong

1. Mở `http://localhost:5173` → **Đăng ký** — tài khoản **đầu tiên** tự động là **admin** (kèm `email_verified=true`; các tài khoản sau là user thường, admin cấp quyền qua trang quản trị). Deploy public: đăng ký ngay sau khi dựng, trước khi mở cho người khác.
2. Menu **Nguồn dữ liệu** → liên kết nguồn (`lpwanmapper`) → **Tải dữ liệu mới nhất** — gateway vào hàng chờ duyệt, điểm đo vào quarantine.
3. Trang **Quản trị** → duyệt batch đóng góp (mode *Duyệt cả file*) → gateway kích hoạt + điểm đo lên bản đồ → `/predict` hoạt động.

Kiểm tra nhanh: `GET http://localhost:8000/healthz` → ok; tab "Bản đồ phủ sóng" mode `estimate` (heatmap tĩnh đã commit) xem được ngay cả khi chưa link nguồn; mode `points`/`heatmap` + predict có dữ liệu sau bước 2-3.

### Những gì KHÔNG có trong git (gitignore) — cần biết khi clone mới

- `lora-data/` — raster địa hình (~7 GB đầy đủ; setup.sh tự tải DEM ~100 MB + OSM PBF ~350 MB rồi build DSM cho rebuild heatmap); phần tùy chọn còn lại theo § Dữ liệu địa lý
- `*.joblib` — model Stage 2; setup.sh train lại từ CSV đã commit, thiếu thì hệ tự chạy Stage 1-only
- Dữ liệu database (gateway, điểm đo, tài khoản) — nằm trong Docker volume của từng máy, nạp qua liên kết nguồn dữ liệu

## Layout lora-data:

```
lora-coverage/
lora-data/
  dem/                     ⬇  Copernicus GLO-30 DTM (mặt đất)      — BẮT BUỘC (runtime /predict)
  landcover/esa-worldcover/⬇  ESA WorldCover 10m 2021 v200         — tùy chọn (P.1812 clutter thủ công)
  osm/vietnam-*.osm.pbf    ⬇  Geofabrik VN extract (building tags) — setup.sh tự tải (để build DSM)
  dem-surface/             ⚙  DSM = DTM + nhà OSM (native 30m)      — setup.sh tự build (rebuild heatmap dùng)
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

**Dữ liệu địa hình** — `setup.sh` tự lo toàn bộ mục 1, 3, 4 (bỏ qua 3+4 bằng `SETUP_SKIP_DSM=1`):

### 1. DEM Copernicus GLO-30m → `dem/`

setup.sh tải 4 tile thô từ AWS public bucket (`s3://copernicus-dem-30m/`) rồi merge trong container thành `copernicus_glo30_danang.tif` (bbox 107.9–108.5°E, 15.8–16.3°N — **đúng tên file pipeline retrain ML cần**). Tải tay: [OpenTopography](https://portal.opentopography.org/raster?opentopoID=OTSDEM.032021.4326.3).

### 2. ESA WorldCover → `landcover/esa-worldcover/` (tùy chọn)

KHÔNG cần cho rebuild heatmap/retrain — chỉ dùng cho thí nghiệm P.1812 clutter thủ công. Nguồn: AWS `s3://esa-worldcover/v200/2021/map/`, tile Đà Nẵng `ESA_WorldCover_10m_2021_v200_N15E108_Map.tif`.

### 3. OSM PBF Việt Nam → `osm/` (setup.sh tự tải)

Geofabrik VN extract (~350 MB, tag `building=*`) — input build DSM. Script: `scripts/fetch_osm_pbf.py` (verify MD5 + atomic rename), chạy trong container.

### 4. DSM → `dem-surface/` (setup.sh tự build)

DSM = DTM + chiều cao nhà OSM (`scripts/build_dsm.py`, chạy trong container) — rebuild heatmap + /predict surface mode dùng; thiếu thì fallback DTM + P.2108 (kém chính xác đô thị).

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
                       Latest: 0035_gateway_rssi_bias. Schema-only, KHÔNG seed dữ liệu —
                       gateway/điểm đo nạp qua liên kết nguồn (lpwanmapper/ChirpStack) + admin duyệt
ops/                Nginx reverse-proxy template
docs/               (gitignore, local-only) Báo cáo tiến độ + ADR
core-logic/         (gitignore, local-only) Design playbook + skill rules
vendor/             ✅ crc_covlib wheel (đã commit — không cần build lại)
scripts/            Stage 1 fit/validate, precompute RSSI heatmap, DSM build, ML train, seed
.github/workflows/  CI: api-service (lint+mypy+import-linter+pytest), docker-build smoke, web-app
```

## Coverage map modes (web-app)

Tab "Bản đồ phủ sóng" có 3 chế độ:

| Mode | Mô tả | Tin cậy | Máy mới |
|---|---|---|---|
| `points` | Survey điểm đo (raw walk-measure data) | Tuyệt đối — đo thực tế  |
| `heatmap` | Heat density survey points | Hiển thị mật độ | Trống (như trên) |
| `estimate` | **Composite RSSI** max qua 13 gateway | Beta — RMSE ±10 dB (~1 bin) | 

## Architecture

5-layer split, enforced by `import-linter` (`.importlinter`):

```
Client → edge            (FastAPI router/middleware/serialization)
       → application     (use cases, repository Protocols)
       → domain          (pure types, no I/O)
       ↑ infrastructure  (concrete repos: PostGIS, R2, Valkey)
```

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
  seed_gateways.py                # (legacy, máy gốc only — cần r-dt/; flow hiện tại
                                  #   nạp gateway qua liên kết nguồn + admin duyệt)
  backfill_gateway_noise_floor.py # Per-gw noise floor migration helper

services/ml-service/scripts/
  train_extra_trees.py            # Train Stage 2 ExtraTrees 
```

Scripts chạy ngoài container cần Python workspace: `uv sync` 1 lần ở repo root.

## Test

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

## NOTE
Dự án còn chưa hoàn thiện và vẫn đang tiếp tục phát triển, các thuật toán, model,... dự án sử dụng có thể được viết lại toàn bộ hoặc một phần trong tương lai, do đó nếu muốn phát triển riêng có thể clone về và tạo repo mới của riêng bạn.
Mọi thắc mắc xin liên hệ email: anngh2004@gmail.com
