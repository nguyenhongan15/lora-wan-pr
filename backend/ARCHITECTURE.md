# Backend Architecture — LoRa Coverage API

Backend tuân thủ: 12-Factor App, RESTful API, SOLID, CORS, Observability, Caching/Performance, BASE, API Contract FE-BE, LoRaWAN TS001/TS002/TS009.

Đây là backend nội bộ — không có tài khoản người dùng, không có auth flow.

## Cấu trúc thư mục

```
backend/
├── main.py                        # App entrypoint: lifespan, middleware, routers
├── config.py                      # 12-Factor F3: env vars qua pydantic-settings
├── database.py                    # Async SQLAlchemy engine + session factory
├── schemas.py                     # Pydantic request/response (CamelModel)
│
├── core/                          # ── Cross-cutting concerns ──
│   ├── responses.py               # ok() / fail() wrapper {success, data, meta}
│   ├── exceptions.py              # AppError + global handlers (API Contract)
│   ├── logging.py                 # Structured JSON logging → stdout (F11)
│   ├── middleware.py              # CorrelationId + AccessLog + Metrics (RED)
│   ├── rate_limit.py              # Sliding window per-IP limiter
│   ├── tenant.py                  # X-Project-Id header → request.state.project_id
│   └── webhook_security.py        # HMAC verify nguồn gốc webhook (không auth user)
│
├── routers/                       # ── HTTP layer (thin — delegate to services) ──
│   ├── gateways.py                # GET /gateways/
│   ├── campaigns.py               # GET /campaigns/, POST /campaigns/import-config
│   ├── measurements.py            # GET /measurements/, /stats, /coverage-grid
│   ├── coverage.py                # GET /coverage/check, /suggest-move
│   ├── predict.py                 # POST /predict/train, /predict/run; GET /predict/grid
│   ├── dem_router.py              # GET /dem/elevation, /hillshade-bounds, /elevation-grid
│   ├── calibration.py             # Persona 2 (Telco) ground-truth calibration
│   ├── health.py                  # Persona 2 operations dashboard
│   ├── exports.py                 # GET /exports/{cid}/measurements.geojson, .xlsx
│   ├── optimizer.py               # POST /optimizer/greedy
│   ├── reports.py                 # Persona 3 (manager) PDF reports
│   ├── scenarios.py               # Persona 4 (RnD) A/B scenario comparison
│   ├── simulator.py               # What-if simulation cho hypothetical gateways
│   ├── sandbox.py                 # Persona 6 custom environment experiments
│   ├── snapshots.py               # Prediction grid version history
│   ├── webhook.py                 # POST /webhook/{slug}: inbound ChirpStack uplink
│   ├── webhook_subscriptions.py   # Outbound webhook management (P2/P4)
│   └── lpwan_sync.py              # GET /sync/*: pull lpwanmapper.com
│
├── services/                      # ── Business logic (SOLID SRP) ──
│   ├── measurement_repo.py        # DB queries: fetch_training_rows(), fetch_measurement_points()
│   ├── ml_training.py             # Train orchestration: DEM → features → train → save
│   ├── ml_inference.py            # Inference orchestration: infer_on_grid()
│   ├── interpolation.py           # IDW + Ordinary Kriging
│   ├── grid.py                    # bbox_with_padding(), make_grid()
│   ├── prediction_store.py        # persist_trained_model(), save_prediction_grid()
│   ├── path_loss.py               # Okumura-Hata, log-distance path loss models
│   ├── calibration.py             # Calibration algorithms (Persona 2)
│   ├── optimizer.py               # Greedy gateway placement optimization
│   ├── scenarios.py               # Scenario comparison logic (Persona 4)
│   ├── sandbox.py                 # Custom experiment logic (Persona 6)
│   ├── exporters.py               # GeoJSON, Excel export utilities
│   ├── report_pdf.py              # ReportLab PDF generation (Persona 3)
│   ├── webhook_dispatcher.py      # Dispatch outbound webhooks tới subscribers
│   └── webhook_retry.py           # Async background worker: retry failed deliveries
│
├── ml/                            # ── Pure ML code (không biết HTTP/DB) ──
│   ├── features.py                # engineer_dataframe(): ~16 features
│   ├── trainer.py                 # XGBoost / RandomForest / GaussianProcess factory
│   ├── predictor.py               # predict_grid(): apply model lên grid
│   ├── model_store.py             # save/load ModelBundle .joblib (path-traversal safe)
│   ├── dem.py                     # DEMReader: đọc SRTM HGT files
│   ├── dem_predict_patch.py       # enrich_with_dem(): thêm elevation features
│   └── generate_hillshade.py      # Script tạo hillshade.png từ DEM
│
├── models/                        # SQLAlchemy ORM models
│   └── orm.py                     # 11 tables (xem mục Database bên dưới)
│
├── scripts/                       # Admin/bootstrap scripts (Factor 12)
│   ├── lpwan_bootstrap.py         # Tạo project/gateways/devices/campaigns từ lpwanmapper
│   ├── lpwan_import.py            # Import 10k+ measurements từ response_data.json
│   └── cleanup_seed.sql           # Xoá seed data
│
├── tests/
│   ├── test_smoke.py
│   └── unit/                      # Unit tests cho services, calibration, path_loss
│
├── data/lpwan/                    # LPWAN import data (JSON từ lpwanmapper.com)
├── static/                        # hillshade.png, hillshade_bounds.json
├── ml_models/                     # *.joblib bundles
├── requirements.txt
├── Dockerfile                     # Multi-stage build (builder + runtime)
└── .env.example
```

## Luồng dependency (một chiều, không vòng)

```
main.py
  ├── core/*                    (middleware, exceptions, webhook_security, tenant)
  ├── routers/*                 (HTTP layer)
  │     └── services/*          (business logic)
  │           ├── ml/*          (pure algorithms)
  │           └── models/orm    (DB schema)
  ├── config.py                 (env — F3)
  ├── database.py               (async engine)
  └── schemas.py                (Pydantic — CamelModel)
```

## Luồng request

```
HTTP Request
  ↓
Middleware stack (CorrelationId → AccessLog → Metrics → Tenant → CORS)
  ↓
Router (validate params, parse body)
  ↓
Service (business logic, DB queries, ML)
  ↓
Response wrapper: {success, data, meta} hoặc {success, error}
  ↓
HTTP Response
```

## Database

**PostgreSQL 16 + PostGIS 3.4**, kết nối async qua `asyncpg`.

Init scripts chạy theo thứ tự khi Docker Compose khởi động:
- `db/init/01_schema.sql` — tables + constraints
- `db/init/02_indexes.sql` — performance indexes
- `db/init/03_seed.sql` — sample data
- `db/init/04_triggers.sql` — audit triggers
- `db/init/05_phase5.sql` — webhook tables
- `db/init/06_phase6.sql` — webhook retry tables

### Các bảng (models/orm.py)

| Bảng | Mô tả | Ghi chú |
|------|--------|---------|
| `projects` | Multi-tenant root entity | Soft-delete |
| `gateways` | LoRaWAN gateway với tọa độ | gateway_eui: 16 hex, GIST index |
| `devices` | LoRaWAN end device | dev_eui: 16 hex (TS002) |
| `campaigns` | Đợt đo coverage | FK→project, date range constraint |
| `environment_zones` | Vùng địa lý (POLYGON) | building_density, NDVI, land_use |
| `campaign_zones` | Liên kết campaign ↔ zone | Unique (campaign_id, zone_id) |
| `measurements` | Điểm đo RSSI/SNR/SF | Core table, 5 indexes, GIST geospatial |
| `ml_models` | Metadata model đã train | algorithm enum, RMSE/MAE/R² |
| `ml_predictions` | Dự đoán trên điểm đo thực | FK→measurement + model |
| `prediction_grids` | Dự đoán trên lưới không gian | GIST index, resolution_m |
| `heatmap_caches` | Cache tile heatmap | TTL, unique (campaign, model, zoom) |

## API Contract

### Versioning
Mọi endpoint dưới `/api/v1/*`. Docs tại `/api/v1/docs`.

### Response format

Thành công:
```json
{
  "success": true,
  "data": { "..." },
  "meta": { "page": 1, "limit": 20, "total": 100 }
}
```

Lỗi:
```json
{
  "success": false,
  "error": {
    "code": "NOT_FOUND",
    "message": "Không tìm thấy gateway.",
    "details": []
  }
}
```

**Ngoại lệ:** GeoJSON FeatureCollection giữ đúng spec (không bọc wrapper) để Mapbox đọc trực tiếp.

### JSON keys
- URL: `kebab-case` → `/predict/hillshade-bounds`
- JSON body/response: `camelCase` → `gatewayEui`, `rssiDbm`, `antennaHeightM`
- Tự động convert qua `CamelModel` (alias_generator) trong `core/responses.py`

### HTTP status
| Code | Ý nghĩa |
|------|---------|
| `200 OK` | GET / update thành công |
| `201 Created` | POST tạo resource mới (train, run, import-config) |
| `400 Bad Request` | Validation logic error |
| `401 Unauthorized` | HMAC webhook sai (không phải auth user) |
| `404 Not Found` | Resource không tồn tại |
| `422 Unprocessable` | Pydantic body validation fail |
| `429 Too Many Requests` | Rate limited |
| `500 Internal Server Error` | Unhandled exception |

## ML Pipeline

```
Measurements (DB)
  ↓ fetch_training_rows()        [measurement_repo.py]
DEM enrichment                   [ml/dem_predict_patch.py]
  ↓ enrich_with_dem()
Feature engineering (~16 features) [ml/features.py]
  ↓ engineer_dataframe()
Model training                   [ml/trainer.py]
  ↓ XGBoost / RandomForest / GaussianProcess
Save ModelBundle → .joblib       [ml/model_store.py]
  ↓ persist_trained_model()      [services/prediction_store.py]
Inference trên grid              [ml/predictor.py]
  ↓ predict_grid()
GeoJSON FeatureCollection → Mapbox
```

**Phương pháp interpolation thay thế:** IDW (Inverse Distance Weighted) và Ordinary Kriging qua `pykrige` — dùng khi không đủ dữ liệu train ML.

## Webhook System (Phase 5–6)

```
ChirpStack uplink
  ↓ POST /webhook/{slug}
HMAC-SHA256 verify               [core/webhook_security.py]
  ↓
Dedup check (devEui + fCnt + gatewayEui + time)
  ↓
Insert measurement → DB
  ↓
webhook_dispatcher.py            dispatch tới registered subscribers
  ↓ (nếu fail)
webhook_retry.py                 async background worker, retry với exponential backoff
```

## Security

Hệ thống là backend nội bộ — không có auth user. Security layer gồm:

- **CORS whitelist**: chỉ origin trong `CORS_ORIGINS` env được phép. KHÔNG dùng `*` ở production. `max_age=86400` giảm preflight OPTIONS.
- **Webhook HMAC** (`core/webhook_security.py`): verify `X-Signature: sha256=<hex>` cho payload từ ChirpStack, chống spam endpoint public. Dùng constant-time comparison chống timing attack.
- **Rate limiting** (`core/rate_limit.py`): sliding window per-IP:
  - `/predict/train/*` — 5 req/min (CPU-nặng)
  - `/sync/*` — 30 req/min (lpwanmapper.com có rate limit thật)
  - Mặc định — 120 req/min
- **Path traversal protection** (`ml/model_store.py`): `model_id` phải là UUID, path resolve kiểm tra không thoát khỏi `ML_MODEL_DIR`.

## Observability

### Logs
Structured JSON → stdout (F11):
```json
{"ts":"2026-04-19T10:00:00Z","lvl":"info","logger":"predict",
 "msg":"model_trained","request_id":"abc-123","rmse_db":4.2}
```

### Correlation ID
`X-Request-ID` header — tự sinh UUID nếu client không gửi, đính kèm response. Mọi log trong cùng request đều có `request_id` giống nhau.

### Metrics
`GET /metrics` → JSON snapshot (RED model):
- Request count theo path + status code
- Avg / max duration (ms)
- Error count (status ≥ 500)

## LoRaWAN Compliance

- **DevEUI / GatewayEUI**: phải là 16 hex chars (TS002 §7). `campaigns.py` validate format.
- **Dedup window 5 phút** (TS002 DedupWindowSize): webhook bỏ qua bản tin trùng (devEui, fCnt, gatewayEui).
- **Spreading Factor**: validate `7 ≤ SF ≤ 12`.
- **Frequency**: validate `400 ≤ freq ≤ 1000 MHz`.

## Performance

- **N+1 fix**: `dem/elevation-grid` dùng `get_elevations_batch` thay vì loop.
- **Index**: `measurements` có 5 indexes (campaign+time, gateway+time, device+time, dedup composite, GIST geospatial).
- **Pagination**: `page/limit` với `COUNT(*)` riêng cho `meta.total`.
- **Connection pool**: `pool_size=10, max_overflow=20, pool_pre_ping=True`.
- **CPU-bound → thread pool**: training/interpolation chạy qua `loop.run_in_executor`.
- **Heatmap cache**: `heatmap_caches` table với TTL, unique per (campaign, model, zoom).

## Graceful Shutdown (Factor 9)

Lifespan handler trong `main.py`:
- **Startup**: spawn webhook retry worker background task.
- **Shutdown**: cancel retry worker, gọi `engine.dispose()` khi nhận SIGTERM.

## Khởi chạy

```bash
# 1. Config
cp .env.example .env
openssl rand -hex 32  # → WEBHOOK_SECRET

# 2. Run
docker compose up --build

# 3. Kiểm tra
curl http://localhost:8000/health
curl http://localhost:8000/api/v1/gateways/

# 4. Docs
open http://localhost:8000/api/v1/docs
```

**Docker Compose services:**
- `postgres` — postgis:16-3.4, auto-run `db/init/*.sql`
- `pgadmin` — database admin UI (localhost:5050)
- `api` — FastAPI app (localhost:8000), non-root user `appuser`

## Admin Tasks (Factor 12)

Chạy trong container với cùng codebase + config:

```bash
# Tạo hillshade từ DEM
docker exec lora_api python ml/generate_hillshade.py

# Bootstrap dữ liệu từ lpwanmapper.com
docker exec lora_api python scripts/lpwan_bootstrap.py
docker exec lora_api python scripts/lpwan_import.py

# DB migration
docker exec lora_api alembic upgrade head
```
