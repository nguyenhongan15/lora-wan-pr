# Thiết kế hệ thống — LoRa Coverage Mapping Platform

Tài liệu mô tả thiết kế chi tiết. Tổng quan và mục tiêu xem `docs/MO_TA_DU_AN.md`.

## 1. Sơ đồ thành phần

```
┌────────────────────────────────────────────────────────────┐
│  React Web App  (Vite + MapLibre + TanStack Query)         │
└──────────────────────┬─────────────────────────────────────┘
                       │ HTTPS / SSE
┌──────────────────────▼─────────────────────────────────────┐
│  Nginx reverse-proxy                                       │
└──┬───────────────────────────────────────────────────┬─────┘
   │                                                   │
┌──▼──────────────────┐                ┌──────────────▼────┐
│  api-service        │   gRPC/HTTP    │  ml-service       │
│  (FastAPI Python)   │◄──────────────►│  Extra Trees      │
│  5-layer clean arch │                │  (FastAPI, sklearn)│
└──┬───┬──────────────┘                └────────────┬──────┘
   │   │                                            │
   │   │ ChirpStack webhook (gói tin)               │ joblib hot-reload
   │   ▼                                            │
   │  ┌─────────────────────┐                       │
   │  │ Celery worker       │  retrain ML  ─────────┘
   │  │ + Valkey broker     │  rebuild heatmap
   │  └─────────────────────┘
   │
   ▼
┌──────────────────────────────────────────┐
│  PostgreSQL 17 + PostGIS 3.5 + Timescale │
│  Schemas: geo, ts, auth, ml, ops         │
└──────────────────────────────────────────┘
```

## 2. Kiến trúc backend — 5 tầng Clean Architecture

`services/api-service/src/lora_coverage_api/`:

```
edge/            ← HTTP (FastAPI router, middleware, Pydantic schema)
application/     ← Use-case + Protocol (interface) cho repo/Stage2
domain/          ← Pure types, không I/O, không framework
infrastructure/  ← Repo PostGIS, Stage2 HTTP client, R2, Valkey
config.py        ← Settings (pydantic-settings)
main.py          ← Wire-up dependencies
tasks/           ← Celery task (retrain ML, rebuild coverage)
```

**Quy tắc tách tầng** (`import-linter` enforce trong CI):
- `domain/` KHÔNG import bất kỳ tầng nào khác.
- `application/` KHÔNG import `infrastructure/` (dùng Protocol, DI ngược).
- `edge/` chỉ import `application/` + `domain/`.

Grep no-leaky-strings: tên storage tier (`postgres`, `redis`, `s3`, `GiST`...) không được xuất hiện trong `application/` và `domain/` → vi phạm fail build.

## 3. Cơ sở dữ liệu

### 3.1. Schema layout

| Schema | Mục đích | Bảng tiêu biểu |
|---|---|---|
| `geo` | Spatial entities | `gateways`, `gateway_quarantine`, `devices`, `addresses` |
| `ts` | Time-series (Timescale hypertable) | `survey_training`, `survey_quarantine`, `chirpstack_events` |
| `auth` | Xác thực | `users`, `refresh_tokens`, `login_attempts`, `password_reset_tokens` |
| `ml` | Model registry | `active_models`, `retrain_jobs`, `upload_batches` |
| `ops` | Vận hành | `coverage_rebuild_jobs`, `daily_visits` |

### 3.2. Migration

- Tool: Alembic, file `migrations/versions/0001..0031_*.py` (31 revisions hiện tại).
- Latest: `0031_upload_batches_live_session_kind` (theo dõi trực tiếp).
- Một-chiều: KHÔNG downgrade trong môi trường có data thật.
- Container `migrate` chạy `alembic upgrade head` 1 lần khi `docker compose up`.

### 3.3. Index đặc biệt

- `geo.gateways.location` — GiST cho ST_DistanceSphere.
- `ts.survey_training` — hypertable theo `timestamp`, chunk 7 ngày.
- BRIN cho cột `timestamp` (range scan rẻ).

## 4. Pipeline dự đoán truyền sóng

### 4.1. Stage 1 — Vật lý ITU-R P.1812

Thư viện: `crc-covlib` (vendor wheel + build .so trong Docker, xem `Dockerfile`).

```
Input:  (lat, lon, sf, gateway[]) + DEM + DSM + climatic zone
        ↓
P.1812 path loss  ──► Site-general clutter P.2108 (skip nếu có DSM)
        ↓
Building entry loss P.2109 (nếu environment=indoor)
        ↓
Per-gateway noise floor calibration (từ geo.gateways.noise_floor_dbm)
        ↓
Per-direction link budget (UL/DL):
  RSSI = Tx_power + Tx_gain + Rx_gain − PL − BEL
  SNR  = RSSI − noise_floor
  Margin = SNR − SF_limit
        ↓
Output: Best serving gateway + RSSI/SNR/margin UL+DL + bottleneck causes
```

### 4.2. Stage 2 — Extra Trees end-to-end

```
api-service:
  POST /api/v1/coverage/predict (lat, lon, sf, env)
    ↓
  Stage 1 → (gateway*, rssi_stage1, ...)
    ↓
  ML disabled?  → return Stage 1 only
    ↓ (enabled)
  HTTP POST → ml-service:8001/residual
    body = { target, serving_gateway, stage1_rssi_dbm }
    ↓
  ml-service:
    extract 21 features (DEM + OSM + Fresnel)
    rssi_et = ExtraTreesRegressor.predict(features)
    return { residual_db = rssi_et − stage1_rssi_dbm }
    ↓
  api-service:
    rssi_final = rssi_stage1 + residual_db   (= rssi_et)
    recompute SNR/margin/SF khuyến nghị/PDR/BER
    fail → fallback Stage 1
```

Lưu ý: tên field `residual_db` giữ vì lý do tương thích contract; bản chất hiện tại = delta để chuyển baseline → end-to-end ET prediction. Chi tiết xem `services/ml-service/README.md`.

## 5. API design

- **Spec:** OpenAPI 3.1 trong `openapi.yaml`.
- **Versioning:** URI path `/api/v1/...`.
- **Error format:** RFC 7807 `application/problem+json`.
- **Auth:** JWT access (header) + refresh (HttpOnly cookie, SameSite=Strict).
- **Rate-limit:** Valkey-backed (shared store giữa workers).

### Endpoint chính

| Endpoint | Method | Mô tả |
|---|---|---|
| `/api/v1/coverage/predict` | POST | Dự đoán Stage1+2 cho 1 điểm |
| `/api/v1/coverage/lookup` | POST | Geocode + predict + render |
| `/api/v1/gateways` | GET | Danh mục gateway |
| `/api/v1/sources/*` | CRUD | Quản lý linked source (LPWANMapper/ChirpStack) |
| `/api/v1/me/uploads` | POST | Upload CSV/JSON khảo sát |
| `/api/v1/me/live-sessions/sse` | GET | SSE stream packet thời gian thực |
| `/api/v1/admin/*` | * | Duyệt batch, gateway, retrain ML |
| `/api/v1/auth/{register,login,refresh,logout}` | POST | JWT auth |

## 6. Frontend (web-app)

`apps/web-app/src/`:

```
App.jsx          ← Tab router qua hash (#page=...)
main.jsx         ← React + TanStack Query bootstrap
auth/            ← Login/register modal, store, client, email verify
components/      ← CoverageMap, MapLibre layers, popup
admin/           ← Admin page (review batch, gateway, ML retrain)
sources/         ← Linked source manage, live session panel
lora/            ← LoRa-specific UI (SF picker, link budget panel)
observability/   ← Health badge, error toast
api/             ← fetch wrappers
strings.js       ← i18n VN strings (single source)
```

**Style:**
- JavaScript ES2024 + JSDoc (không TS, check qua `tsc --noEmit`).
- Zod validate runtime trước khi đẩy vào UI.
- Tailwind 4 + class names hoá theo design system.
- MapLibre GL: 1 map instance, layer toggle cho 3 mode (points/heatmap/estimate).

## 7. Authentication & authorization

```
Browser                        api-service                   DB
   │  POST /auth/login               │                        │
   ├────────────────────────────────►│                        │
   │                                 │  bcrypt verify          │
   │                                 │◄──────────────────────►│
   │                                 │  rate-limit (Valkey)    │
   │                                 │  login_attempts check   │
   │  200 + access_token             │                        │
   │  Set-Cookie: refresh=...        │                        │
   │◄────────────────────────────────┤                        │
   │                                 │                        │
   │  GET /api/v1/...                │                        │
   │  Authorization: Bearer ...      │                        │
   ├────────────────────────────────►│                        │
   │                                 │  verify JWT             │
   │                                 │  role check (admin/user)│
   │  200                            │                        │
   │◄────────────────────────────────┤                        │
```

- **Access token:** JWT HS256, TTL 15 phút, role claim (`admin` / `user`).
- **Refresh:** UUID opaque, lưu DB `auth.refresh_tokens`, HttpOnly cookie, TTL 30 ngày, rotate on use.
- **Lockout:** 5 fail trong 15 phút → khoá tài khoản 30 phút (mig 0012).
- **Reset password:** token TTL 1h qua email (SMTP).
- **Email verify:** required cho contributor; token TTL 24h (mig 0019).

## 8. Background jobs (Celery)

`services/api-service/src/lora_coverage_api/tasks/`:

| Task | Trigger | Mô tả |
|---|---|---|
| `retrain_ml_model` | Admin approve batch hoặc manual | Build CSV → train Extra Trees → atomic swap artifact → POST `/admin/reload` tới ml-service |
| `rebuild_coverage_heatmap` | Admin click "Rebuild" hoặc auto sau approve | Chạy `precompute_rssi_heatmap.py` (P.1812 + DTM + per-gw NF + survey overlay) |
| `sync_linked_source` | Schedule 20s | Pull packet mới từ LPWANMapper/ChirpStack API |

- **Broker + result backend:** Valkey 8 (cùng instance dùng cho rate-limit).
- **Concurrency:** worker `--concurrency=1` cho retrain/heatmap (CPU/memory heavy).
- **Idempotency:** task có thể chạy lại; key dedup bằng `(timestamp, device_eui, gw_eui)`.

## 9. Real-time (ChirpStack + SSE)

```
Gateway → ChirpStack server → POST /chirpstack/webhook (api-service)
                                     │
                                     ▼
                              ts.chirpstack_events
                                     │
                  ┌──────────────────┴──────────────────┐
                  ▼                                     ▼
        Celery dedup task                      SSE fan-out
        promote → ts.survey_training           connected clients
                                               (live session panel)
```

- **Webhook auth:** per-tenant token, lưu `mig 0014_chirpstack_webhook_tokens`.
- **SSE:** `GET /api/v1/me/live-sessions/sse?source_id=...` — server-sent events stream, idle timeout 15 phút.
- **Sync cadence:** 20 giây (`project_realtime_troubleshoot_checklist.md`).

## 10. Triển khai

### 10.1. Docker Compose stack

| Container | Image | Vai trò |
|---|---|---|
| `lora-wan-db` | `timescale/timescaledb-ha:pg17-ts2.17-all` | Postgres + PostGIS + Timescale |
| `lora-wan-migrate` | (reuse api-service) | Chạy `alembic upgrade head` 1 lần |
| `lora-wan-api` | Build từ `services/api-service/Dockerfile` | FastAPI |
| `lora-wan-ml` | Build từ `services/ml-service/Dockerfile` | ml-service + sklearn |
| `lora-wan-celery` | (reuse api-service image) | Celery worker |
| `lora-wan-cache` | `valkey/valkey:8-alpine` | Broker + rate-limit store |

- **Network:** bridge `lora-wan-net`. DB chỉ bind `127.0.0.1:5432`.
- **Volume:** `lora-wan-db-data` cho PG; bind mount DEM/OSM/output report.
- **Log rotation:** `json-file` 50MB × 5 file.

### 10.2. Cloud setup (production tham khảo)

- 1 VPS Hetzner CPX31 (8 GB RAM, 4 vCPU).
- Cloudflare R2 cho artifact (model + tile).
- Cloudflare tunnel cho demo public (`demo.<domain>`).
- Postgres tuning: `shared_buffers=2GB`, `effective_cache_size=6GB` (xem `docker-compose.yml` comment).

## 11. CI/CD

`.github/workflows/ci.yml` — 3 job song song:

1. **api-service** — Ruff lint/format → mypy strict → import-linter → grep no-leaky-strings → Alembic upgrade trên Timescale service container → seed gateway → pytest (domain/application/integration).
2. **docker-build** — Multi-stage Dockerfile build cho api + ml + worker → smoke `docker run` healthcheck.
3. **web-app** — npm install → ESLint → JSDoc check (`tsc --checkJs --noEmit`) → Vite build.

Trigger: push & PR vào `main`. Image tag theo git SHA cho rollback.

## 12. Quan sát hệ thống (observability)

- **Log:** structured JSON, log level via `LOG_LEVEL` env. Stdout → Docker log driver.
- **Health probe:** `/healthz` (liveness), `/readyz` (DB + ml-service ping).
- **Trace:** chưa wire OpenTelemetry (deferred).
- **Metric:** Prometheus endpoint chưa expose (deferred).
- **Frontend telemetry:** `daily_visits` table (mig 0028) — basic page view counter, no PII.

## 13. Bảo mật

- **Transport:** HTTPS bắt buộc (Nginx + Let's Encrypt).
- **CORS:** allowlist origin từ env `LORA_CORS_ALLOWED_ORIGINS`.
- **Secret:** từ `.env` (không commit); CI secret qua GitHub Actions secret.
- **DB:** loopback bind only; password ngẫu nhiên 32 ký tự.
- **Input validation:** Pydantic v2 (`extra="forbid"`) + Zod (frontend) — 2 lớp.
- **SQL injection:** SQLAlchemy parameterized; raw SQL chỉ cho geospatial query đã sanitize.
- **Rate limit:** 5 login/15min, 100 predict/phút (Valkey shared).
- **Lockout:** 5 fail → 30 phút.

## 14. Quản lý gateway và dữ liệu khảo sát

```
Người dùng kết nối linked source (LPWANMapper/ChirpStack)
     ↓
Sync packet → ts.survey_quarantine + geo.gateway_quarantine (gateway lạ)
     ↓
Admin duyệt:
  ├─ Gateway → geo.gateways + backfill FK survey
  └─ Survey batch → ts.survey_training
     ↓
Trigger:
  ├─ Reset last_rebuild_at = NULL cho gateway bị ảnh hưởng → next rebuild full
  └─ Optional: trigger retrain ML
```

CSV/JSON upload: alias header linh hoạt, default SNR/freq; gặp gateway lạ → reject row (admin tạo gateway trước qua tab "Tạo mới gateway"). Chi tiết: memory `project_csv_upload_new_gateway_deferred_2026_06_14.md`.
