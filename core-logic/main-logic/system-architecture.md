# System Architecture Document

## LoRa Network Coverage Mapping Platform with ML-Based Coverage Analysis

> **Audience.** This is an **in-depth technical document for developers** who write code, review code, and set up environments. It describes the components (modules), how they interact, the database, infrastructure, load balancer & caching, CI/CD, and design principles.
>
> **NOT for:** funders, executives, or researchers — they should read `system-design.md` (the parent document).
>
> **Design philosophy.** Every decision traces back to two anchors — *A Philosophy of Software Design* (Ousterhout, 2018) and **operating-cost discipline** (the platform is donation/grant funded; Day-1 budget < USD 100/month).
>
> **Non-negotiable rules for developers:** The `application/` layer **must never** import from `infrastructure/`. The `application/` layer **must never** see the strings `postgres`, `redis`, `valkey`, `s3`, `stage_4`, `GiST`, `BRIN`. If your code violates this, `import-linter` will block the merge.

---

## Table of Contents

1. High-level architecture overview
2. Consolidated tech stack
3. Components/Modules in detail
4. Interactions/Connections (data flows)
5. Database
6. Object Storage
7. Infrastructure (Docker, environments, deployment)
8. Load Balancer & Caching
9. CI/CD and GitHub workflow
10. Observability (Monitoring, Logging, Tracing)
11. Security
12. Design Principles (Ousterhout) — applied concretely
13. Project Structure (source code folder layout)
14. Coding conventions
15. Environment variables (.env)
16. Appendix — quick setup commands

---

## 1. High-level architecture overview

The system is divided into **5 clear layers**. Each layer communicates only with adjacent layers through a predefined interface.

```
┌────────────────────────────────────────────────────────────────────┐
│  LAYER 1 — CLIENT (end users)                                      │
│  ┌────────────────────┐  ┌────────────────────┐  ┌──────────────┐  │
│  │  Web App           │  │  Mobile App        │  │  Embedded    │  │
│  │  React 19 + Vite 7 │  │  React Native      │  │  Widget      │  │
│  │  + JavaScript ES24 │  │  (Expo)            │  │  (iframe)    │  │
│  │  + Mapbox GL JS    │  │  + Mapbox/MapLibre │  │  + Leaflet   │  │
│  └────────────────────┘  └────────────────────┘  └──────────────┘  │
└────────────────────────────────────────────────────────────────────┘
                                ↑↓  HTTPS / WSS
┌────────────────────────────────────────────────────────────────────┐
│  LAYER 2 — EDGE (CDN, Load Balancer, Rate-limit)                   │
│  Cloudflare CDN  +  Cloudflare R2 (tiles, model artifacts)         │
│  Nginx (reverse proxy, gzip, SSL termination)                      │
└────────────────────────────────────────────────────────────────────┘
                                ↑↓
┌────────────────────────────────────────────────────────────────────┐
│  LAYER 3 — APPLICATION (Business Logic + API)                      │
│  ┌──────────────────────────┐  ┌──────────────────────────────┐    │
│  │  API Service (FastAPI)   │  │  ML Inference Service        │    │
│  │  Python 3.12             │  │  Python 3.12 + ONNX Runtime  │    │
│  │  Pydantic v2             │  │  (LightGBM/PyTorch by stage) │    │
│  └──────────────────────────┘  └──────────────────────────────┘    │
│  ┌──────────────────────────┐  ┌──────────────────────────────┐    │
│  │  Background Worker       │  │  Tile Server (Go) — triggered│    │
│  │  Celery + Redis broker   │  │  When tile traffic > 1M req/d│    │
│  └──────────────────────────┘  └──────────────────────────────┘    │
└────────────────────────────────────────────────────────────────────┘
                                ↑↓
┌────────────────────────────────────────────────────────────────────┐
│  LAYER 4 — REPOSITORY (4 Capabilities — NO MORE)                   │
│  CoverageQuery │ SurveyIngest │ GatewayDirectory │ AddressResolution│
│  Common language: data-access methods                              │
│  Hides: SQL, geocoding cascade, ML stage routing, cache logic      │
└────────────────────────────────────────────────────────────────────┘
                                ↑↓
┌────────────────────────────────────────────────────────────────────┐
│  LAYER 5 — STORAGE                                                 │
│  PostgreSQL 17 + PostGIS 3.5 + TimescaleDB 2.17  (MANDATORY v1)    │
│  Cloudflare R2 (S3-compatible)                   (MANDATORY v1)    │
│  Valkey 8                                        (TRIGGERED, not deployed v1) │
└────────────────────────────────────────────────────────────────────┘
```

**Layer-to-layer communication rules:**

- Layer N **only** calls layer N+1 below; **no** skipping.
- Every cross-layer call must go through a defined interface (Repository, not raw SQL).
- Business errors (predictable) are returned via `Result[T, E]`, **not** thrown as exceptions. Exceptions are reserved for unexpected failures (out-of-memory, dead DB connection).

---

## 2. Consolidated tech stack

Quick reference — every technology a developer will touch.

### 2.1 Frontend Web

| Component | Technology | Version | Role |
|---|---|---|---|
| Framework | **React** | 19.x | UI library |
| Build tool | **Vite** | 7.x | Dev server + bundler |
| Language | **JavaScript (ES2024)** | — | Vite supports ES modules + JSX natively, no TypeScript compile step |
| Type-hint (optional) | **JSDoc** + `// @ts-check` | — | IDE IntelliSense without a TS build; can run mypy-style check via `tsc --noEmit --allowJs --checkJs` if desired |
| Runtime validation | **Zod** schemas (at boundaries) | 3.x | Validate API/form data at the boundary — NOT PropTypes (deprecated in React 19) |
| Primary map | **Mapbox GL JS** | 3.x | Tile rendering, vector layers (requires sponsor token) |
| Fallback map | **MapLibre GL JS** | 4.x | Open-source fork of Mapbox; used when no sponsor |
| Widget map | **Leaflet** | 1.9+ | Iframe widget for hardware vendors (P6) — lighter than Mapbox |
| State management | **Zustand** | 5.x | Simple client state |
| Server state | **TanStack Query** | 5.x | Cache, retry, background refetch for API |
| Routing | **React Router** | 7.x | SPA routing |
| Forms | **React Hook Form** + **Zod** | latest | Form validation (Zod schemas work in JS via `.parse()`) |
| UI components | **shadcn/ui** + **Radix UI** | latest | Component primitives (shadcn/ui ships JS variants) |
| Styling | **Tailwind CSS** | 4.x | Utility-first CSS |
| Charting | **Recharts** | 2.x | Uncertainty / RSSI / SNR charts |
| HTTP client | **Axios** | 1.x | Fetch wrapper with interceptors |
| i18n | **i18next** + **react-i18next** | latest | Vietnamese + English |
| Test | **Vitest** + **Playwright** | latest | Unit + E2E |
| Linter/Formatter | **ESLint 9** + **Prettier 3** | latest | Code style (flat config with `eslint-plugin-react`, `react-hooks`) |

### 2.2 Frontend Mobile

| Component | Technology | Role |
|---|---|---|
| Framework | **React Native** + **Expo SDK 52+** | Cross-platform iOS/Android |
| Map | **@rnmapbox/maps** (Mapbox) or **maplibre-react-native** | Native map rendering |
| State / Server state | **Zustand** + **TanStack Query** | Same as web |
| Storage | **expo-secure-store** | Tokens, API keys |
| Push notifications | **expo-notifications** | Signal-loss alerts (Persona 5) |
| Geolocation | **expo-location** | Lookup at current location |

> **Note:** At v1, if engineering bandwidth is tight, ship a **PWA (responsive web app)** instead of a native app — Vietnamese users are familiar with Zalo & Facebook PWAs and don't require native immediately.

### 2.3 Backend

| Component | Technology | Version | Role |
|---|---|---|---|
| Primary API framework | **FastAPI** | 0.115+ | REST API, OpenAPI auto-gen |
| Primary language | **Python** | 3.12 | Backend + ML |
| Secondary language (triggered) | **Go** | 1.23+ | High-performance tile server (when tile traffic > 1M req/day) |
| Validation | **Pydantic v2** | 2.x | Type-safe DTOs |
| ORM / Query builder | **SQLAlchemy 2.0** + **GeoAlchemy 2** | latest | ORM with PostGIS support |
| Migration | **Alembic** | 1.13+ | Schema versioning |
| ASGI server | **Uvicorn** + **Gunicorn** | latest | Production server |
| Background jobs | **Celery 5** + **Redis broker** | latest | Survey ingest, model training trigger |
| Scheduler | **APScheduler** or **systemd timers** | latest | Cron-like jobs (recalibration check, audit cleanup) |
| Auth | **python-jose** + **passlib[bcrypt]** | latest | JWT + password hashing |
| Rate limit | **slowapi** | latest | Per-tier rate limiting |
| HTTP client | **httpx** | latest | Calling VietMap/Goong/Google geocoding |
| Test | **pytest** + **pytest-asyncio** + **httpx.AsyncClient** | latest | Unit + integration |
| Linter/Formatter | **Ruff** + **Black** + **mypy** + **import-linter** | latest | Code quality + layer-boundary enforcement |

### 2.4 Machine Learning Stack

| Stage | Library | Why |
|---|---|---|
| Stage 1 (Empirical) | NumPy + SciPy | Sufficient for log-distance path-loss model |
| Stage 2 (Hybrid + GBT) | **LightGBM** 4.x | 3–5× faster training, native categorical handling |
| Stage 3 (Hybrid + CNN) | **PyTorch** 2.5+ | ResNet-18 modified for regression |
| Stage 4 (Bayesian) | PyTorch + ensemble logic | Deep ensembles / MC-dropout |
| Inference runtime | **ONNX Runtime** | One runtime for both LightGBM and PyTorch; framework-agnostic |
| Feature engineering | **Pandas** + **Rasterio** + **GeoPandas** | DEM, NDVI, building footprints |
| Calibration | **scikit-learn** (Platt, isotonic) | ECE, NLL computation |
| Experiment tracking | **MLflow** (self-hosted) or **Weights & Biases** (free tier) | Model + metric logging |

### 2.5 Database & Storage

| Type | Technology | Role |
|---|---|---|
| Primary RDBMS | **PostgreSQL 17** | OLTP + OLAP at v1 scale |
| Spatial extension | **PostGIS 3.5** + **postgis_raster** | Spatial queries, R-tree |
| Time-series extension | **TimescaleDB 2.17** | Hypertables for `survey_*` |
| Text-search extensions | **pg_trgm** + **unaccent** | Vietnamese fuzzy match |
| Object storage | **Cloudflare R2** (S3-compatible) | PMTiles, model artifacts (zero egress fee) |
| Cache (triggered) | **Valkey 8** | NOT deployed at v1; only deployed when geocoding cache miss > 30% sustained for 7 days |
| Message broker | **Redis** (for Celery) | Single instance; can share with Valkey once deployed |

### 2.6 DevOps & Infrastructure

| Component | Technology | Role |
|---|---|---|
| Container | **Docker** + **Docker Compose** | Dev + production single-host |
| Orchestrator (triggered) | **Docker Swarm** or **K3s** | When multi-host is needed |
| Reverse proxy | **Nginx** | SSL termination, gzip, static files |
| CDN | **Cloudflare** (free tier) | Edge cache for tiles + frontend assets |
| TLS | **Let's Encrypt** + **certbot** | Free TLS auto-renew |
| VPS | **Hetzner** or **Contabo** (EU/SG) | 4 vCPU, 16 GB RAM, 200 GB SSD |
| CI/CD | **GitHub Actions** | Test + build + deploy |
| Container registry | **GitHub Container Registry (ghcr.io)** | Free for public repos |
| IaC (optional) | **Ansible** | VPS provisioning |
| Secret management | `.env` file + GitHub Actions secrets | NO Vault at v1 |

### 2.7 Observability

| Component | Technology | Tier |
|---|---|---|
| Metrics | **Prometheus** client + **Grafana Cloud free** | Free 10k series, 14-day retention |
| Logging | **Python logging** → **Loki** (Grafana Cloud) | Structured JSON logs |
| Tracing | **OpenTelemetry** SDK | Push to Grafana Cloud Tempo (free tier) |
| Alerting | **Grafana Cloud Alerts** | Pager / email / Slack |
| Error tracking | **Sentry** (free tier 5k events/month) | Backend + frontend errors |

### 2.8 API Tooling

| Component | Technology |
|---|---|
| API spec | **OpenAPI 3.1** (FastAPI auto-generated) |
| API doc UI | **Swagger UI** + **Redoc** (built into FastAPI) |
| Postman collection | Public, hosted on Postman workspace |
| Python SDK | Auto-generated from OpenAPI via `openapi-python-client` |
| JS/TS SDK | Hand-written axios wrapper from OpenAPI (~200 LOC) plus a separate `types.d.ts` for IntelliSense |
| Go SDK | Auto-generated via `oapi-codegen` |

---

## 3. Components/Modules in detail

Each component below is an **independent module** with clear boundaries. The repo where each module lives is specified.

### 3.1 `web-app/` — Frontend Web (React 19 + Vite 7)

**Responsibilities:**

- Render the LoRa coverage map (Feature 1).
- Address/coordinate lookup form (Feature 2).
- Dashboards for Professional/Enterprise tier.
- Project management screens, bulk CSV upload.
- Iframe-embeddable widget for Persona 6 (separate `<script>` build output).

**Internal sub-modules:**

| Module | Description |
|---|---|
| `features/coverage-map/` | Mapbox/MapLibre layer + uncertainty layer + SF selector |
| `features/lookup/` | Two-layer form (Layer 1: Good/Marginal/None — Layer 2: RSSI/SNR/CI on click) |
| `features/project-workspace/` | Project CRUD (Professional/SI tier) |
| `features/survey-upload/` | Drag-drop CSV/JSON, validate before POST `/survey/upload` |
| `features/api-playground/` | Postman-like, calls API directly from UI |
| `features/admin/` | Sponsor dashboard, API key management |
| `shared/components/` | shadcn/ui wrappers |
| `shared/lib/api-client.js` | Axios instance + auth interceptor |
| `shared/lib/i18n/` | vi-VN (default) + en-US |
| `shared/types/*.js` | JSDoc `@typedef` shapes for Prediction, Confidence, Coordinates… (shared with mobile via workspace) |

**Connections:** Calls REST API only via `api-client.js`. Never accesses DB or object storage directly. Map tiles are loaded via **signed URLs** from R2 CDN (no proxy through backend).

### 3.2 `mobile-app/` — Frontend Mobile (React Native + Expo)

**Responsibilities:**

- Simple Vietnamese-language lookup for Persona 5 (Good/Weak/No Coverage).
- Site survey mode for Persona 7 — log RSSI/SNR while walking the field.
- Push notifications when a device loses signal.

**Internal sub-modules:**

| Module | Description |
|---|---|
| `screens/Lookup/` | Minimal UI, single "Check here" button |
| `screens/SiteSurvey/` | Records GPS + RSSI during a walking survey |
| `screens/Devices/` | Real-time device status |
| `services/ble/` | (Optional) read RSSI directly from LoRa device via BLE |
| `services/sync/` | Sync survey logs to backend when network is available |

**Connections:** Same REST API as the web app. Shares JSDoc typedefs and constants via npm workspace `@lora/api-shared` (plain `.js` files, no build step).

### 3.3 `widget/` — Embedded Widget for Hardware Vendors

**Responsibilities:**

- Lets a Persona 6 site embed `<iframe src="https://app.com/widget?address=...">`.
- White-label per-customer branding.
- Deep-link tracking for partner reporting.

**Tech:** Vanilla JavaScript (ES2024 modules) + Leaflet (lightweight; doesn't require Mapbox token per vendor).
**Build output:** Single ESM bundle < 100 KB, hosted on Cloudflare Pages.

### 3.4 `api-service/` — FastAPI Backend (business core)

**Responsibilities:**

- Public REST API (the 6 endpoints in `system-design.md` §8.1).
- Auth (JWT for users + API key for machine-to-machine).
- Rate-limit by tier.
- Orchestrate calls to the ML service and the Repository.

**Internal layout (3 layers):**

```
api-service/
├── app/
│   ├── api/                     # Presentation layer (FastAPI routers)
│   │   ├── v1/
│   │   │   ├── coverage.py
│   │   │   ├── gateways.py
│   │   │   ├── survey.py
│   │   │   └── auth.py
│   │   └── deps.py              # Dependency injection
│   ├── application/             # Business logic layer
│   │   ├── services/
│   │   │   ├── coverage_service.py
│   │   │   ├── survey_service.py
│   │   │   └── gateway_service.py
│   │   ├── domain/              # Value objects, types
│   │   │   ├── coordinates.py
│   │   │   ├── prediction.py
│   │   │   └── confidence.py
│   │   └── errors.py            # Result[T, E]
│   ├── repository/              # Data-access layer (4 capabilities)
│   │   ├── coverage_query/
│   │   ├── survey_ingest/
│   │   ├── gateway_directory/
│   │   └── address_resolution/
│   └── infrastructure/          # Concrete implementation layer
│       ├── db/                  # SQLAlchemy session, engine
│       ├── object_storage/      # R2 client
│       ├── geocoding/           # VietMap, Goong, Nominatim, Google clients
│       └── audit_writer.py
├── migrations/                  # Alembic
├── tests/
└── pyproject.toml
```

**Lint rules (import-linter):**

- `app/application/` **must not** import `app/infrastructure/`.
- `app/application/` **must not** import `app/api/`.
- `app/repository/` **must not** import `app/api/` or `app/application/services/`.
- A violation fails CI.

### 3.5 `ml-service/` — ML Inference Service

**Responsibilities:**

- Serve inference for Stage 1/2/3/4 (depending on which stage each region is operating at).
- Auto-fallback when a higher stage is unavailable.
- Always return `Prediction` with full `Confidence`.

**Separated from `api-service` because:**

- ResNet-18 + LightGBM models can occupy several GB of RAM.
- May require GPU (Stage 3+).
- Independent restart for swapping model versions without dropping API traffic.

**Communication:** Internal HTTP (FastAPI) or gRPC. Not exposed to the public Internet.

**Layout:**

```
ml-service/
├── app/
│   ├── stages/
│   │   ├── stage1_empirical.py     # Log-distance, NumPy
│   │   ├── stage2_lightgbm.py      # LightGBM residual
│   │   ├── stage3_cnn.py           # ResNet-18 ONNX
│   │   └── stage4_bayesian.py      # Ensemble
│   ├── pipeline/
│   │   ├── tabular_features.py     # For Stage 2
│   │   └── raster_features.py      # For Stages 3, 4
│   ├── router.py                   # Stage selection + auto-fallback
│   ├── calibration/
│   │   └── ece_monitor.py          # Alerts when ECE > 0.08
│   └── api.py                      # FastAPI /predict endpoint
└── models/                         # Cached artifacts (R2 backed)
```

### 3.6 `worker-service/` — Background Jobs (Celery)

**Responsibilities:**

- Consume tasks from Redis queue.
- Validate + quarantine survey uploads.
- Trigger model retraining.
- Daily recalibration check.
- Cleanup audit logs > 90 days.
- Pre-compute tiles for new provinces.

**Queue design:**

| Queue | Task type | Concurrency |
|---|---|---|
| `default` | Validate survey, send email | 4 |
| `ml-train` | Train models (one at a time) | 1 |
| `tiles` | Pre-compute PMTiles | 2 |
| `audit` | Async compliance log writes | 4 |

### 3.7 `tile-server/` (TRIGGERED — Go) — Tile Serving

**NOT deployed at v1.** Deployed only when tile traffic exceeds 1M req/day AND Cloudflare CDN alone is insufficient.

**Why Go instead of Python:** Tile serving is I/O-bound, latency-critical, and simple (read PMTiles from R2 → return bytes). Go yields 5–10× higher throughput with the same resources.

**Tech:** `go-pmtiles` + `chi` router + `aws-sdk-go-v2`.

### 3.8 `sdk-python/`, `sdk-js/`, `sdk-go/` — Official SDKs

Auto-generated from the OpenAPI spec. Each SDK has its own subrepo and publishes to PyPI / npm / pkg.go.dev.

| SDK | Generator | Publish |
|---|---|---|
| Python | `openapi-python-client` | PyPI: `lora-coverage` |
| JavaScript | `swagger-typescript-api` with `--no-client` flag plus a post-process step that emits plain `.js` and a separate `.d.ts` for IDE hints; or hand-written ~200-line axios wrapper | npm: `@lora/coverage-sdk` |
| Go | `oapi-codegen` | `github.com/<org>/lora-coverage-go` |

CI auto-regenerates SDKs whenever `openapi.yaml` changes.

### 3.9 `docs/` — Documentation (Docusaurus)

Hosted on Cloudflare Pages. Includes:

- API reference (auto-imports OpenAPI).
- Per-tier guides.
- Tutorials for Persona 4 (researchers).
- Public Postman collection link.
- Public roadmap + financial transparency report (a business-model requirement).

---

## 4. Interactions/Connections (data flows)

### 4.1 Address-based lookup flow (Feature 2)

```
[User] types "Hoa Vang, Da Nang"
   │
   ▼
[Web App] POST /api/v1/coverage/lookup
   │           {address: "Hoa Vang, Da Nang", sf: 7}
   ▼
[Nginx] → [api-service]
   │
   ▼
[CoverageService.lookup_by_address()]
   │
   ├─→ [AddressResolution.resolve()]
   │       │
   │       ├─→ Postgres canonical (P95 < 50ms, ~95% hit)
   │       ├─→ (if miss) Self-hosted Nominatim — if deployed
   │       ├─→ (if miss) VietMap / Goong API
   │       └─→ (if INCLUDE_PAID + sponsor configured) Google Geocoding
   │
   │       Returns: Coordinates(16.07, 108.22)
   │       Side-effect: write back to canonical (learns Vietnamese addresses over time)
   │
   ├─→ [CoverageQuery.predict(coords, sf=SF7)]
   │       │
   │       ├─→ [TileLookup] try fetching pre-computed tile from R2
   │       │   if tile exists → return Prediction from tile (P95 < 200ms)
   │       │
   │       └─→ [On-demand inference] if no tile available
   │               │
   │               ├─→ Internal HTTP call to [ml-service]
   │               │       /predict?lat=...&lng=...&sf=7
   │               │
   │               └─→ [Stage Router] picks the highest stage available
   │                   for this region; auto-fallback if needed
   │
   ▼
[CoverageService] packages into Prediction + Confidence
   │
   ▼
[FastAPI] returns JSON
   {
     "status": "GOOD",                          // Layer 1
     "rssi_dbm": -98.4,                         // Layer 2
     "snr_db": 6.2,
     "serving_gateway_id": "gw_dn_07",
     "confidence": {"value": 0.87, "source": "PRIMARY"},
     "model_stage": 2
   }
   │
   ▼
[Web App] renders 🟢 + map snapshot. Click → reveal Layer 2.
```

**SLA:** P95 end-to-end < 3 seconds. If exceeded, page on-call.

### 4.2 Survey Upload flow (Feature 3 — reverse direction)

```
[Client SDK] POST /api/v1/survey/upload
              {records: [{lat, lng, rssi, snr, ts, device_id, sf}, ...]}
   │
   ▼
[api-service] authenticates API key, checks tier (Academic+)
   │
   ▼
[SurveyService.ingest_batch()]
   │
   ├─→ Schema validation (Pydantic)
   ├─→ Outlier detection: RSSI ∈ [-150, -30], SNR ∈ [-30, 30]
   ├─→ Geographic plausibility check (not in water unless declared maritime)
   │
   ▼
[SurveyIngest.write_quarantine()]
   │
   ├─→ INSERT into ts.survey_quarantine (TimescaleDB hypertable)
   │
   └─→ Push task onto Celery queue `default`
       {task: "validate_survey_batch", batch_id: "..."}
   │
   ▼
Returns 202 Accepted immediately (does not wait for validation)
   {batch_id: "abc-123", status: "QUARANTINED", estimated_review_hours: 24}

           ─── Async, outside the request lifecycle ───

[worker-service] consumes the task
   │
   ├─→ Reputation weighting (verified gateway? high-rep account?)
   ├─→ Cross-check against known gateways
   │
   ├─→ If OK: MOVE from ts.survey_quarantine → ts.survey_training
   │           (deleted from quarantine, inserted into training set)
   │
   └─→ If rejected: kept in quarantine + flagged, never deleted
                    (audit trail)
```

**Note:** `quarantine` and `training` are **two separate tables**, not one table with a `quarantined: bool` flag. See §5.3.

### 4.3 Tile Rendering flow (Feature 1 — web map)

```
[Web App] initializes Mapbox GL JS with source:
  {
    type: "vector",
    tiles: ["https://cdn.app.com/tiles/v=v17/layer=coverage/{z}/{x}/{y}.pmtiles"]
  }
   │
   ▼
[Browser] requests tile {z=10, x=812, y=487}
   │
   ▼
[Cloudflare CDN] checks edge cache
   │
   ├─→ HIT (95%+) → returns immediately, P95 < 100ms
   │
   └─→ MISS → fetch from Cloudflare R2 origin
              R2 missing → 404 (not yet pre-computed)
              R2 hit → cached for 7 days at edge, returned to client
   │
   ▼
[Mapbox GL JS] renders using the configured style (color ramp by RSSI)
   │
   ├─→ Layer "coverage" (RSSI heatmap)
   └─→ Layer "uncertainty" (hatching/transparency)
```

**Critical:** Tiles **never** pass through `api-service`. The backend pre-computes and pushes to R2; the client downloads directly from CDN. This is the only way to keep costs in USD/month rather than thousands of USD.

### 4.4 "What-if" Simulation flow (drag a hypothetical gateway)

```
[User] drags a hypothetical gateway marker onto the map
   │
   ▼
[Web App] POST /api/v1/coverage/simulate
              {hypothetical_gateway: {...}, area: polygon, sf: 7}
   │
   ▼
[api-service] → [CoverageQuery.simulate_with_gateway()]
   │
   ├─→ DOES NOT read tiles (pre-computed tiles don't include the hypothetical gateway)
   ├─→ Calls [ml-service] directly with gateway list = real + hypothetical
   │
   ▼
[ml-service] inference over 100m × 100m grid within polygon
   (CPU/GPU intensive — P95 < 5s)
   │
   ▼
Returns CoverageGrid (GeoJSON heatmap)
   │
   ▼
[Web App] renders as a temporary overlay layer (not cached)
```

### 4.5 Authentication flow

```
[User] logs in with email + password → POST /auth/login
   │
   ▼
[api-service] verifies password (bcrypt) → issues JWT (HS256, exp 1h)
   │
   ▼
[Client] stores JWT in:
  - Web: httpOnly Secure SameSite=Lax cookie
  - Mobile: expo-secure-store
  - Server-to-server: Authorization Bearer header
   │
   ▼
On every subsequent request:
  - Browser auto-sends the cookie
  - Mobile/SDK sends `Authorization: Bearer <token>`
   │
   ▼
[FastAPI dependency `get_current_user`] decodes JWT, returns User
```

**API key (machine-to-machine):**

```
Authorization: Bearer lora_live_xxx_yyy
```

Stored hashed (SHA-256) in `auth.api_keys`. Compared by hash on authentication.

---

## 5. Database

### 5.1 Database Engine: PostgreSQL 17

**One engine for ~90% of the logic:**

- Full ACID (required for project workspaces, gateway directory).
- PostGIS = the OGC Simple Features reference → directly compatible with QGIS/ArcGIS (Persona 3).
- TimescaleDB hypertables for `survey_*` → automatic partitioning + 10–20× compression.
- Free cross-domain joins: "all RSSI within polygon X for the past 7 days" = one query.

**Required extensions:**

```sql
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_raster;
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
```

### 5.2 Schema layout — one schema per capability

```sql
CREATE SCHEMA geo;        -- Gateway directory (C3)
CREATE SCHEMA ts;         -- Survey time-series (C2)
CREATE SCHEMA address;    -- Geocoding canonical (C4)
CREATE SCHEMA audit;      -- Compliance log
CREATE SCHEMA auth;       -- User, API key, session (separate sub-domain)
```

Schema = namespace. Easier to migrate, back up, audit. Application code never sees schema names — only the Repository sees them.

### 5.3 Core tables

#### `geo.gateways` — gateway directory

```sql
CREATE TABLE geo.gateways (
    id              TEXT PRIMARY KEY,                -- "gw_dn_07"
    operator        TEXT NOT NULL,                   -- "viettel" | "vnpt" | "private_<org>"
    location        GEOGRAPHY(POINT, 4326) NOT NULL,
    altitude_m      REAL,
    antenna_height  REAL NOT NULL,
    tx_power_dbm    REAL NOT NULL,
    antenna_gain    REAL NOT NULL,
    pattern         JSONB,                           -- Radiation pattern
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX gateways_location_gix ON geo.gateways USING GIST (location);
CREATE INDEX gateways_active_idx   ON geo.gateways (operator) WHERE is_active = TRUE;
```

#### `ts.survey_quarantine` and `ts.survey_training` — survey logs

```sql
CREATE TABLE ts.survey_quarantine (
    id              UUID DEFAULT gen_random_uuid(),
    timestamp       TIMESTAMPTZ NOT NULL,
    location        GEOGRAPHY(POINT, 4326) NOT NULL,
    rssi_dbm        REAL NOT NULL,
    snr_db          REAL NOT NULL,
    spreading_factor SMALLINT NOT NULL,
    device_id       TEXT,
    serving_gateway_id TEXT REFERENCES geo.gateways(id),
    uploader_id     UUID NOT NULL,
    uploaded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reject_reason   TEXT,                            -- NULL = pending; non-NULL = rejected
    PRIMARY KEY (timestamp, id)
);
SELECT create_hypertable('ts.survey_quarantine', 'timestamp');

CREATE TABLE ts.survey_training (
    id              UUID,
    timestamp       TIMESTAMPTZ NOT NULL,
    location        GEOGRAPHY(POINT, 4326) NOT NULL,
    rssi_dbm        REAL NOT NULL,
    snr_db          REAL NOT NULL,
    spreading_factor SMALLINT NOT NULL,
    device_id       TEXT,
    serving_gateway_id TEXT REFERENCES geo.gateways(id),
    uploader_id     UUID NOT NULL,
    weight          REAL NOT NULL DEFAULT 1.0,       -- Reputation weighting
    promoted_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (timestamp, id)
);
SELECT create_hypertable('ts.survey_training', 'timestamp');

CREATE INDEX survey_quarantine_loc_gix ON ts.survey_quarantine USING GIST (location);
CREATE INDEX survey_quarantine_ts_brin ON ts.survey_quarantine USING BRIN (timestamp);

CREATE INDEX survey_training_loc_gix ON ts.survey_training USING GIST (location);
CREATE INDEX survey_training_ts_brin ON ts.survey_training USING BRIN (timestamp);
```

> **Why two tables?** Querying the training set never requires `WHERE quarantined = false` → this is "Define special cases out of existence" (Ch. 10) applied to data structure.

> **Why BRIN on timestamp?** `survey_*` is append-only. BRIN is ~1000× smaller than B-tree at billion-row scale.

#### `address.canonical` — geocoding cache

```sql
CREATE TABLE address.canonical (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    raw_text        TEXT NOT NULL,
    normalized_text TEXT GENERATED ALWAYS AS (
        lower(unaccent(raw_text))
    ) STORED,
    location        GEOGRAPHY(POINT, 4326) NOT NULL,
    province        TEXT,
    district        TEXT,
    ward            TEXT,
    source          TEXT NOT NULL,                   -- "nominatim" | "vietmap" | "goong" | "google" | "user_pin"
    confidence      REAL NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at    TIMESTAMPTZ
);

CREATE INDEX canonical_norm_trgm ON address.canonical
    USING GIN (normalized_text gin_trgm_ops);
CREATE INDEX canonical_loc_gix   ON address.canonical USING GIST (location);
```

> **`normalized_text` is a generated column** — the DBMS guarantees it stays in sync with `raw_text`. Application code **cannot** write inconsistent data. Information hiding at the DDL level.

#### `audit.compliance_log`

```sql
CREATE TABLE audit.compliance_log (
    id              BIGSERIAL PRIMARY KEY,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_type      TEXT NOT NULL,                   -- "EXPORT_SHAPEFILE" | "EXPORT_GEOTIFF" | "SURVEY_UPLOAD" | "ADMIN_ACTION"
    actor_id        UUID,
    actor_kind      TEXT,                            -- "user" | "api_key" | "system"
    target_kind     TEXT,
    target_id       TEXT,
    metadata        JSONB
);

CREATE INDEX compliance_log_time_idx ON audit.compliance_log (occurred_at);
CREATE INDEX compliance_log_actor_idx ON audit.compliance_log (actor_id);
```

Plain table (not hypertable) — low volume, no partitioning needed. 90-day retention; cleaned by cron.

### 5.4 Roles & Permissions

**Only 2 roles:**

```sql
CREATE ROLE readonly_role;
CREATE ROLE app_role;

GRANT CONNECT ON DATABASE lora TO readonly_role, app_role;
GRANT USAGE ON SCHEMA geo, ts, address, audit, auth TO readonly_role, app_role;

GRANT SELECT ON ALL TABLES IN SCHEMA geo, ts, address, audit, auth TO readonly_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA geo, ts, address, audit, auth TO app_role;
```

Admin operations (DROP TABLE, CREATE USER) only via Alembic migrations or DBA SSH. **No** standing admin role.

### 5.5 Migration with Alembic

```
migrations/
├── env.py
├── script.py.mako
└── versions/
    ├── 202601150900_initial_schema.py
    ├── 202602010800_add_survey_training.py
    └── ...
```

Every migration **must** include both `upgrade()` and `downgrade()`.

**Zero-downtime rules:**

- NEVER DROP COLUMN in production until new code has run stably for ≥ 7 days.
- ADD COLUMN always with DEFAULT (avoids table lock).
- ADD INDEX uses `CONCURRENTLY` (does not block writes).
- Renames: introduce a wrapping view first, then rename later.

---

## 6. Object Storage (Cloudflare R2)

### 6.1 Why R2 instead of AWS S3

- **Free egress** — tiles are read heavily; every other provider charges egress.
- S3-compatible API — easy to migrate to AWS/MinIO later.
- Built-in CDN integration (Cloudflare).

### 6.2 Bucket layout

```
lora-tiles-prod/
└── v=v17/                              # model_version in key prefix
    ├── layer=coverage/
    │   └── z=10/x=812/y=487.pmtiles
    └── layer=uncertainty/
        └── z=10/x=812/y=487.pmtiles

lora-models-prod/
├── stage=1/region=mekong/calib=v17/model.bin
├── stage=2/region=mekong/calib=v17/lightgbm.txt
├── stage=3/region=mekong/calib=v17/cnn.onnx
└── stage=4/region=mekong/calib=v17/ensemble/
    ├── m1.onnx
    ├── m2.onnx
    └── ...

lora-static-prod/
├── frontend/                           # web-app build output
└── widget/                             # widget bundle
```

### 6.3 Invalidation rule

`model_version` lives in the **key prefix**, not in metadata. When recalibrating v17 → v18:

- New tiles are written under prefix `v=v18/`.
- Production code points at `v=v18/` (config change).
- Old tiles in `v=v17/` automatically "disappear" from production.
- No CDN purge, no stale flag, no cleanup job needed.

This is "Define errors out of existence" (Ch. 10) applied to cache invalidation.

### 6.4 Versioning

- `lora-models-prod/`: bucket versioning ON (model artifacts are valuable).
- `lora-tiles-prod/`: OFF (tiles can be recomputed from inputs).
- `lora-static-prod/`: OFF (lives in Git).

---

## 7. Infrastructure

### 7.1 v1 deployment model (single VPS)

```
┌─────────────────────────────────────────────────────────────┐
│  VPS: Hetzner CPX31 (4 vCPU, 16 GB RAM, 200 GB SSD)         │
│  OS: Ubuntu 24.04 LTS                                       │
│  Region: Singapore (closest to Vietnam)                     │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  Docker Compose stack:                              │    │
│  │  - nginx (reverse proxy + TLS)                      │    │
│  │  - api-service (FastAPI x 2 replicas via Gunicorn)  │    │
│  │  - ml-service (FastAPI, 1 replica)                  │    │
│  │  - worker-service (Celery, 2 workers)               │    │
│  │  - redis (broker + cache)                           │    │
│  │  - postgres-17 (PostGIS + TimescaleDB)              │    │
│  │  - certbot (cron renew TLS)                         │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
        │
        ├──→ Cloudflare CDN (frontend + tiles)
        ├──→ Cloudflare R2 (object storage)
        └──→ Grafana Cloud (logs + metrics + traces)
```

**Rule:** **One VPS** until traffic proves more is needed. Don't split into microservices early. No Kubernetes at v1.

### 7.2 Docker Compose layout

```yaml
# docker-compose.prod.yml
version: "3.9"

services:
  nginx:
    image: nginx:1.27-alpine
    ports: ["80:80", "443:443"]
    volumes:
      - ./nginx/conf.d:/etc/nginx/conf.d:ro
      - ./certs:/etc/letsencrypt:ro
    depends_on: [api-service]
    restart: unless-stopped

  api-service:
    image: ghcr.io/your-org/api-service:${VERSION}
    env_file: .env.prod
    depends_on: [postgres, redis]
    deploy:
      replicas: 2
    restart: unless-stopped

  ml-service:
    image: ghcr.io/your-org/ml-service:${VERSION}
    env_file: .env.prod
    depends_on: [postgres]
    restart: unless-stopped

  worker-service:
    image: ghcr.io/your-org/worker-service:${VERSION}
    env_file: .env.prod
    depends_on: [postgres, redis]
    deploy:
      replicas: 2
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    volumes: ["redis_data:/data"]
    command: redis-server --appendonly yes --maxmemory 1gb --maxmemory-policy allkeys-lru
    restart: unless-stopped

  postgres:
    image: timescale/timescaledb-ha:pg17  # Already includes PostGIS + TimescaleDB
    env_file: .env.prod
    volumes:
      - pg_data:/var/lib/postgresql/data
      - ./postgres/init:/docker-entrypoint-initdb.d:ro
    restart: unless-stopped
    shm_size: 1g

  certbot:
    image: certbot/certbot:latest
    volumes: ["./certs:/etc/letsencrypt"]
    entrypoint: "/bin/sh -c 'trap exit TERM; while :; do certbot renew; sleep 12h & wait $${!}; done;'"

volumes:
  pg_data:
  redis_data:
```

### 7.3 Environments

| Environment | Purpose | Infrastructure |
|---|---|---|
| `local` | Dev laptop | Docker Compose, hot reload |
| `staging` | QA + sponsor demos | Hetzner CPX21 VPS (cheaper), domain `staging.app.com` |
| `prod` | Live | Hetzner CPX31 VPS |

### 7.4 Deployment (simple Ansible playbook)

```
ops/
├── ansible/
│   ├── inventory/
│   │   ├── staging.yml
│   │   └── prod.yml
│   ├── playbooks/
│   │   ├── provision.yml      # Setup Ubuntu, Docker, ufw
│   │   ├── deploy.yml         # Pull new image, docker compose up
│   │   └── backup.yml         # WAL + pg_dump → R2
│   └── roles/
└── nginx/
    └── conf.d/app.conf
```

---

## 8. Load Balancer & Caching

### 8.1 Multi-layer caching diagram

```
[Client]
   │
   ▼
[Cloudflare CDN]                ← Layer 1: edge cache (95% hit on tiles)
   │
   ▼
[Nginx]                         ← Layer 2: reverse proxy + gzip + static
   │
   ▼
[FastAPI in-memory]             ← Layer 3: per-process LRU (functools)
   │
   ▼
[Redis / Valkey]                ← Layer 4: shared cache (geocoding, hot predictions)
   │   (Valkey TRIGGERED — not deployed at v1)
   ▼
[Postgres canonical table]      ← Layer 5: persistent address cache
   │
   ▼
[External provider]             ← Layer 6: VietMap, Goong, Google
```

### 8.2 Main Nginx configuration

```nginx
# /etc/nginx/conf.d/app.conf
upstream api_backend {
    least_conn;
    server api-service:8000 max_fails=3 fail_timeout=10s;
    server api-service:8001 max_fails=3 fail_timeout=10s;
    keepalive 32;
}

server {
    listen 443 ssl http2;
    server_name app.com;

    ssl_certificate     /etc/letsencrypt/live/app.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/app.com/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;

    gzip on;
    gzip_types application/json text/css application/javascript;

    # Static frontend (build output)
    location / {
        root /var/www/web-app;
        try_files $uri /index.html;
        expires 1h;
    }

    # API
    location /api/ {
        proxy_pass http://api_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 30s;

        # Rate limit
        limit_req zone=api_zone burst=20 nodelay;
    }

    # Tile redirect → Cloudflare R2
    location /tiles/ {
        return 302 https://cdn.app.com$request_uri;
    }
}

limit_req_zone $binary_remote_addr zone=api_zone:10m rate=10r/s;
```

### 8.3 Load Balancer

**v1:** Nginx `least_conn` upstream balancing 2 replicas of `api-service` on the same VPS. Sufficient for 50,000 lookups/day.

**Triggered:** When traffic outgrows a single VPS:

- Stage 1: Move DB to its own VPS (Postgres VPS + App VPS).
- Stage 2: Add a second App VPS, place **HAProxy** or **Cloudflare Load Balancer** in front.
- Stage 3: Add a Postgres read replica (logical replication).

### 8.4 Specific caching strategies

| Type | Cache location | TTL | Invalidation |
|---|---|---|---|
| Map tiles | Cloudflare CDN | 7 days | Change `model_version` in key prefix |
| Geocoding | Postgres `address.canonical` (v1), Valkey (triggered) | Permanent (updates `last_used_at`) | Manual if address is wrong |
| Hot point predictions | Redis LRU 1 GB | 1 hour | Don't invalidate; let TTL expire |
| Gateway directory | FastAPI in-memory (LRU functools) | 5 minutes | Redis pub/sub on update |
| OpenAPI spec | Nginx static file | 1 day | Redeploy |
| Frontend bundle | Cloudflare CDN | 1 year (hash in filename) | New filename per build |

### 8.5 When to deploy Valkey

**Trigger (both must be true):**

- Geocoding cache miss > 30% sustained for 7 days, **OR**
- P95 lookup latency > 2s due to address resolution.

When deploying: changes happen **only** in `infrastructure/geocoding/cascade.py`. Repository interface unchanged. Application unaware.

---

## 9. CI/CD and GitHub workflow

### 9.1 Branching model

- `main` — production-ready, tagged releases `v1.2.3`.
- `develop` — integration, auto-deploy to staging.
- `feature/<ticket>` — dev branch, PR'd into `develop`.
- `hotfix/<ticket>` — urgent fix, PR straight to `main` + cherry-pick into `develop`.

**Required:**

- PR must have ≥ 1 reviewer approval.
- CI must be green (test, lint, security scan).
- Branch protection prevents force-push to `main` and `develop`.

### 9.2 GitHub Actions workflows

```
.github/workflows/
├── ci.yml              # Test, lint, type-check on every PR
├── deploy-staging.yml  # Auto-deploy on merge to develop
├── deploy-prod.yml     # Manual approval on tag v*.*.*
├── sdk-publish.yml     # When openapi.yaml changes
└── security-scan.yml   # Nightly: Snyk, Trivy
```

#### `ci.yml` (abbreviated)

```yaml
name: CI
on:
  pull_request:
    branches: [main, develop]
jobs:
  test-backend:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: timescale/timescaledb-ha:pg17
        env:
          POSTGRES_PASSWORD: test
        ports: ["5432:5432"]
      redis:
        image: redis:7-alpine
        ports: ["6379:6379"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e ".[dev]"
      - run: ruff check .
      - run: black --check .
      - run: mypy app/
      - run: lint-imports                   # import-linter layer check
      - run: pytest --cov=app --cov-fail-under=80

  test-frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: "22" }
      - run: npm ci
      - run: npm run lint
      - run: npm run jsdoc-check          # tsc --noEmit --allowJs --checkJs (validates JSDoc if present)
      - run: npm run test
      - run: npm run build

  build-images:
    needs: [test-backend, test-frontend]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/build-push-action@v5
        with:
          context: ./api-service
          push: true
          tags: ghcr.io/${{ github.repository }}/api-service:${{ github.sha }}
```

#### `deploy-prod.yml`

```yaml
name: Deploy Production
on:
  push:
    tags: ["v*.*.*"]
jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: production         # GitHub environment with manual approval
    steps:
      - uses: actions/checkout@v4
      - name: SSH deploy
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.PROD_HOST }}
          username: deploy
          key: ${{ secrets.PROD_SSH_KEY }}
          script: |
            cd /opt/lora
            export VERSION=${{ github.ref_name }}
            docker compose pull
            docker compose up -d --no-deps api-service ml-service worker-service
            docker compose exec -T api-service alembic upgrade head
```

### 9.3 GitHub repo structure (monorepo or multi-repo)

**Recommended monorepo for v1** (one repo, many packages):

```
lora-platform/
├── .github/workflows/
├── apps/
│   ├── web-app/                # React 19 + Vite 7 (JavaScript)
│   ├── mobile-app/             # React Native + Expo (JavaScript)
│   ├── widget/                 # Vanilla JS + Leaflet
│   └── docs/                   # Docusaurus
├── services/
│   ├── api-service/            # FastAPI
│   ├── ml-service/             # FastAPI ML
│   ├── worker-service/         # Celery
│   └── tile-server/            # Go (triggered)
├── packages/
│   ├── api-shared/             # @lora/api-shared — JSDoc typedefs + constants (plain JS)
│   ├── sdk-python/             # Auto-generated
│   ├── sdk-js/                 # Hand-written axios wrapper + types.d.ts
│   └── sdk-go/                 # Auto-generated
├── ops/
│   ├── ansible/
│   ├── docker-compose.prod.yml
│   ├── docker-compose.dev.yml
│   └── nginx/
├── migrations/                 # Alembic
├── openapi.yaml                # Source of truth for API
└── README.md
```

Workspace management: `pnpm` for JS, `uv` for Python (10× faster than pip).

### 9.4 Quality gates

| Gate | Tool | Threshold |
|---|---|---|
| Lint Python | Ruff | 0 errors |
| Format Python | Black | clean |
| Type Python | mypy --strict | 0 errors |
| Layer boundary | import-linter | 0 violations |
| Test coverage | pytest-cov | ≥ 80% |
| Lint JS | ESLint 9 (eslint-plugin-react, react-hooks) | 0 errors |
| JSDoc check (optional) | `tsc --noEmit --allowJs --checkJs` | 0 errors on files that opt in via `// @ts-check` |
| Frontend test | Vitest | ≥ 70% |
| E2E | Playwright | Critical paths green |
| Security | Trivy + Snyk | 0 CRITICAL, 0 HIGH |
| Docker image size | dive | API < 500 MB, ML < 2 GB |

---

## 10. Observability

### 10.1 Metrics (Prometheus + Grafana Cloud)

**The Repository publishes; the application does not.** Each capability emits standard metrics:

```python
# infrastructure/metrics.py
from prometheus_client import Counter, Histogram

capability_request_duration = Histogram(
    "lora_capability_request_duration_seconds",
    "Request duration per capability method",
    ["capability", "method", "status"],
    buckets=[0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0],
)

capability_requests_total = Counter(
    "lora_capability_requests_total",
    "Total requests per capability method",
    ["capability", "method", "status"],
)

coverage_query_stage_fallback_total = Counter(
    "lora_coverage_query_stage_fallback_total",
    "Number of fallbacks to a lower stage",
    ["from_stage", "to_stage", "region"],
)
```

**Alert thresholds (Grafana Cloud Alerts):**

| Alert | Threshold | Severity |
|---|---|---|
| `address_resolution.resolve` P95 > 2s for 5 min | page on-call |
| `coverage_query.predict` P95 > 500ms for 5 min | warning |
| Any capability error rate > 1% for 5 min | page |
| Stage 4 ECE rolling 7-day > 0.08 | auto-rollback to Stage 3 + alert |
| Postgres disk > 70% | warning |
| Postgres disk > 85% | page |

### 10.2 Logging (Loki)

**Format:** Structured JSON, one line per event.

```python
import structlog
log = structlog.get_logger()

log.info("survey_uploaded",
         batch_id=str(batch.id),
         records=len(batch.records),
         uploader_id=str(uploader.id),
         tier=uploader.tier.value)
```

**Rules:**

- NEVER log passwords, API keys, JWT tokens, PII (specific phone numbers/emails in production logs).
- Every request carries a `request_id` (UUID v4) across all logs.
- Log level: `DEBUG` only in dev; `INFO`/`WARNING`/`ERROR` in prod.

### 10.3 Tracing (OpenTelemetry → Tempo)

Auto-instrument FastAPI + SQLAlchemy + httpx + Celery. Trace 10% sampling in production (cost control).

### 10.4 Error tracking (Sentry)

- Backend: `sentry-sdk[fastapi]`.
- Frontend: `@sentry/react`.
- Every unhandled exception is auto-shipped to Sentry with context.

---

## 11. Security

### 11.1 Authentication

| Tier | Method |
|---|---|
| Community (anonymous) | No login required, IP-based rate limit |
| Academic+ | JWT (HS256, exp 1h) via login form |
| Machine-to-machine | API key formatted `lora_live_xxx_yyy` (SHA-256 hashed in DB) |

### 11.2 Authorization

- Tier-based permission, checked in the FastAPI dependency `require_tier(Tier.PROFESSIONAL)`.
- Per-tier quotas (rate-limit middleware `slowapi`).
- Resource ownership: project workspaces editable only by owner and collaborators.

### 11.3 Input validation

- **All** input goes through Pydantic v2 models with constraints (`Field(ge=-150, le=-30)` for RSSI).
- SQL injection: parameterized SQLAlchemy only; NEVER raw f-string SQL.
- Path traversal: validate paths during upload via `secure_filename`.
- XSS: React auto-escapes; avoid `dangerouslySetInnerHTML` (don't use it).

### 11.4 Transport

- TLS 1.2/1.3 only, HSTS enabled (`max-age=31536000`).
- Certbot auto-renews Let's Encrypt every 60 days.

### 11.5 Secrets

- `.env.prod` lives only on the server, mode 600, owned by deploy user.
- NEVER committed to Git. Tool: `git-secrets` pre-commit hook.
- GitHub Actions: use repository secrets.

### 11.6 Audit

The following events are written **synchronously** (not async) to `audit.compliance_log` (compliance requirement):

- Shapefile / GeoTIFF exports.
- Survey uploads (reversible if needed).
- Admin actions on users / API keys.

### 11.7 OWASP Top 10 checklist

All 10 items applied: A01 Broken Access Control, A02 Cryptographic Failures, A03 Injection, A04 Insecure Design, A05 Security Misconfiguration, A06 Vulnerable Components (Snyk), A07 Auth Failures, A08 Integrity Failures, A09 Logging Failures, A10 SSRF.

---

## 12. Design Principles (Ousterhout) — applied concretely

| # | Principle | Concrete application in code |
|---|---|---|
| 1 | **Deep modules (Ch. 4)** | Repository has 4 capabilities + ~14 methods, but hides SQL, geospatial, time-series, cache cascade, ML stage fallback. Small interface; large functionality. |
| 2 | **Information hiding (Ch. 5)** | `application/` never sees `postgres`, `redis`, `s3`, `GiST`. Database type, index type, schema layout — all hidden. Linter enforces. |
| 3 | **Pull complexity downwards (Ch. 8)** | Geocoding cascade, ML stage fallback, retries, version mismatch — all live in the Repository. Application calls `predict()` and manages nothing. |
| 4 | **Different layer, different abstraction (Ch. 7)** | Application speaks "predict at this point". Repository speaks "query coverage". Storage speaks SQL. No layer borrows another layer's vocabulary. |
| 5 | **Define errors out of existence (Ch. 10)** | `Result[T, E]` instead of exceptions. `Confidence` instead of `degraded_mode: bool`. Empty list instead of "not found". `quarantine` and `training` are two separate tables. `model_version` lives in S3 key prefix. |
| 6 | **Code should be obvious (Ch. 18)** | Names are clear: `simulate_with_gateway`, not `predict_v2`. Comments explain "why", not "what". No magic numbers — every constant has a name. |

**Anti-patterns to strictly avoid:**

- **Shallow module (Ch. 7):** wrapping S3 as a "TileService" with 3 pass-through methods. Wrong. Fold into `CoverageQuery.fetch_tile`.
- **Pass-through method (Ch. 7):** API service has `get_gateway()` that just calls `gateway_repo.get()`. Wrong. Inject the repo directly into the router.
- **Status quo bias (Ch. 3):** "The old code did it that way, so I'll do it that way." Wrong. Ask: which principle supports this?

---

## 13. Project Structure (source code folder layout)

```
lora-platform/                          ← Monorepo
│
├── apps/
│   ├── web-app/                        ← React 19 + Vite 7 (JavaScript)
│   │   ├── src/
│   │   │   ├── features/
│   │   │   ├── shared/
│   │   │   ├── pages/
│   │   │   ├── App.jsx
│   │   │   └── main.jsx
│   │   ├── public/
│   │   ├── index.html
│   │   ├── vite.config.js
│   │   ├── tailwind.config.js
│   │   ├── jsconfig.json                ← Tells the IDE about `@/` alias + checkJs (NOT tsconfig)
│   │   └── package.json
│   │
│   ├── mobile-app/                     ← React Native + Expo
│   │   ├── app/                        (expo-router)
│   │   ├── components/
│   │   ├── services/
│   │   ├── app.config.ts
│   │   └── package.json
│   │
│   ├── widget/                         ← Embedded iframe widget
│   └── docs/                           ← Docusaurus
│
├── services/
│   ├── api-service/                    ← FastAPI
│   │   ├── app/
│   │   │   ├── api/
│   │   │   ├── application/
│   │   │   ├── repository/
│   │   │   └── infrastructure/
│   │   ├── tests/
│   │   ├── Dockerfile
│   │   └── pyproject.toml
│   │
│   ├── ml-service/                     ← FastAPI ML
│   ├── worker-service/                 ← Celery
│   └── tile-server/                    ← Go (triggered)
│
├── packages/
│   ├── api-shared/                     ← @lora/api-shared (JSDoc typedefs + constants, JS)
│   ├── sdk-python/
│   ├── sdk-js/
│   └── sdk-go/
│
├── migrations/                         ← Alembic versions
├── ops/
│   ├── ansible/
│   ├── nginx/
│   ├── docker-compose.prod.yml
│   └── docker-compose.dev.yml
│
├── .github/
│   ├── workflows/
│   ├── CODEOWNERS
│   └── pull_request_template.md
│
├── openapi.yaml                        ← Source of truth
├── pnpm-workspace.yaml
├── pyproject.toml                      ← Root Python config
├── .gitignore
├── .editorconfig
├── README.md
└── CONTRIBUTING.md
```

---

## 14. Coding conventions

### 14.1 Python

- **Format:** Black, line-length 100.
- **Lint:** Ruff with rules `E,F,I,N,UP,B,SIM,TID`.
- **Type:** mypy `--strict`. Every public function has full type hints.
- **Naming:**
  - Module: `snake_case.py`.
  - Class: `PascalCase`.
  - Function/variable: `snake_case`.
  - Constant: `UPPER_SNAKE`.
  - Domain types: `GatewayId`, `Coordinates` (NEVER raw primitives).
- **Docstring:** Google style. Required on every module and every public class/function.
- **Async:** Default `async def` for I/O. Sync only for pure CPU-bound work.

### 14.2 JavaScript (Frontend)

- **Format:** Prettier, single-quote, semi true.
- **Lint:** ESLint 9 flat config with plugins: `eslint-plugin-react`, `eslint-plugin-react-hooks`, `eslint-plugin-jsx-a11y`, `eslint-plugin-import`. Do **NOT** use `@typescript-eslint` (no TypeScript in this project).
- **IDE config (`jsconfig.json`):** enable `"checkJs": true`, `"strict": true`, `"baseUrl": "./src"`, `"paths": { "@/*": ["*"] }`. This is for the IDE and `tsc --noEmit --allowJs --checkJs` (check-only, no emit), NOT a build step. Vite does not use `tsc` to build — Vite parses JSX with esbuild.
- **Type-hints via JSDoc** (strongly recommended; not 100% mandatory but required in `shared/`, `lib/`, `services/`):

  ```js
  /**
   * @typedef {Object} Coordinates
   * @property {number} lat
   * @property {number} lng
   */

  /**
   * @typedef {Object} Prediction
   * @property {number} rssi_dbm
   * @property {number} snr_db
   * @property {'GOOD'|'MARGINAL'|'NONE'} status
   * @property {string} serving_gateway_id
   * @property {Confidence} confidence
   */

  /**
   * Lookup coverage at a point.
   * @param {Coordinates} coords
   * @param {number} [sf=7]
   * @returns {Promise<Prediction>}
   */
  export async function lookupCoverage(coords, sf = 7) { /* ... */ }
  ```

- **Validate boundaries with Zod** instead of runtime types: data received from API/forms passes through `Schema.parse()` at the boundary — internal logic then trusts the validated shape. This replaces TypeScript's runtime "type guards":

  ```js
  import { z } from 'zod';

  const PredictionSchema = z.object({
    rssi_dbm: z.number(),
    snr_db: z.number(),
    status: z.enum(['GOOD', 'MARGINAL', 'NONE']),
    serving_gateway_id: z.string(),
    confidence: z.object({
      value: z.number().min(0).max(1),
      source: z.enum(['PRIMARY', 'FALLBACK', 'DEGRADED']),
    }),
  });

  // In api-client.js
  const data = PredictionSchema.parse(response.data);  // throws if shape is wrong
  ```

- **Do NOT use PropTypes.** PropTypes is deprecated in React 19 and no longer recommended. Use JSDoc `@param` for component props, or Zod schemas for complex data shapes.
- **Naming:**
  - Component file: `PascalCase.jsx` (e.g. `LookupForm.jsx`).
  - Util/lib/hook file: `camelCase.js` (e.g. `useCoverage.js`, `apiClient.js`).
  - Hook: `useCamelCase`.
  - Constant: `UPPER_SNAKE` (e.g. `MAX_LOOKUPS_PER_DAY`).
  - JSDoc typedef: `PascalCase`, **no** `I` prefix (e.g. `Prediction`, not `IPrediction`).
- **Import order:** External (`react`, `axios`) → Internal alias `@/...` → Relative (`./LookupForm`). Enforced by ESLint rule `import/order`.
- **Component:** Function component, **no** Class component. One component per file.
- **Default vs named export:**
  - Components → `export default` (HMR-friendly with Vite).
  - Utils/hooks/constants → named `export` (avoids naming drift on rename).
- **Strict mode:** Enable `<React.StrictMode>` in `main.jsx`. Components must not depend on a single dev-mode double render.

### 14.3 JavaScript (Mobile — React Native)

Same conventions as 14.2 plus:

- File extension: `.jsx` for components (Expo + Metro bundler accept JSX in both `.js` and `.jsx`, but keeping `.jsx` for components makes intent obvious).
- Babel preset: `babel-preset-expo` (already in the Expo template).
- Do **NOT** use the legacy `react-native-reanimated` v2 syntax — only the v3 worklet syntax.

### 14.4 Git commits

Conventional Commits:

```
feat(api): add /coverage/area endpoint
fix(web-app): handle null prediction in lookup form
docs(architecture): update Valkey trigger criteria
chore(deps): bump fastapi to 0.115.5
refactor(repository): merge TileService into CoverageQuery
test(ml): add ECE calibration test for Stage 4
```

Scope corresponds to the package/service. PR title also follows this format (becomes the commit on squash-merge).

### 14.5 PR description template

```
## What
<bullet points of changes>

## Why
<ticket link + rationale>

## How to test
<step-by-step for the reviewer>

## Checklist
- [ ] Test coverage didn't drop
- [ ] import-linter passes (no layer violations)
- [ ] Docs updated if public API changed
- [ ] Migration added if schema changed
```

---

## 15. Environment variables (.env)

`.env.example` lives at the repo root (committed). `.env.prod` lives only on the server (not committed).

```bash
# ─── Application ──────────────────────────────
ENV=production                              # local | staging | production
LOG_LEVEL=INFO
SERVICE_NAME=api-service

# ─── Database ─────────────────────────────────
DATABASE_URL=postgresql+asyncpg://app_role:xxx@postgres:5432/lora
DATABASE_POOL_SIZE=10
DATABASE_MAX_OVERFLOW=20

# ─── Redis (broker + cache) ───────────────────
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/1
CELERY_RESULT_BACKEND=redis://redis:6379/2

# ─── Cloudflare R2 ────────────────────────────
R2_ENDPOINT=https://<accountid>.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=xxx
R2_SECRET_ACCESS_KEY=xxx
R2_BUCKET_TILES=lora-tiles-prod
R2_BUCKET_MODELS=lora-models-prod

# ─── Auth ─────────────────────────────────────
JWT_SECRET=<random 32 bytes>
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=60

# ─── Geocoding (cascade) ──────────────────────
GEOCODING_DEFAULT_DEPTH=CACHE_AND_LOCAL      # CACHE_ONLY | CACHE_AND_LOCAL | INCLUDE_PROVIDERS | INCLUDE_PAID
NOMINATIM_URL=                               # Empty = not yet deployed
VIETMAP_API_KEY=
GOONG_API_KEY=
GOOGLE_GEOCODING_API_KEY=                    # ONLY set when sponsor account is configured
GOOGLE_SPONSOR_BUDGET_USD=0                  # >0 lets the cascade reach step 4

# ─── ML Service ───────────────────────────────
ML_SERVICE_URL=http://ml-service:8001
ML_DEFAULT_REGION=mekong

# ─── Map providers ────────────────────────────
MAPBOX_PUBLIC_TOKEN=                         # Sponsor token; empty → fallback to MapLibre
MAPBOX_STYLE_URL=mapbox://styles/<org>/<style>
MAPLIBRE_TILE_URL=https://demotiles.maplibre.org/style.json

# ─── Observability ────────────────────────────
GRAFANA_CLOUD_PROMETHEUS_URL=
GRAFANA_CLOUD_LOKI_URL=
GRAFANA_CLOUD_TEMPO_URL=
GRAFANA_CLOUD_API_KEY=
SENTRY_DSN=
OTEL_TRACE_SAMPLE_RATE=0.1

# ─── Frontend (Vite) ──────────────────────────
VITE_API_BASE_URL=https://api.app.com
VITE_MAPBOX_PUBLIC_TOKEN=                    # Public token, OK to bundle
VITE_SENTRY_DSN=
VITE_ENV=production
```

---

## 16. Appendix — quick setup commands

### 16.1 Local dev setup

```bash
# Clone
git clone https://github.com/<org>/lora-platform.git
cd lora-platform

# Python (uv is pip 10× faster)
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync                                      # Installs deps for every service

# Node
npm install -g pnpm
pnpm install                                 # Installs deps for every app

# Start local Postgres + Redis
docker compose -f ops/docker-compose.dev.yml up -d postgres redis

# Migrate schema
cd services/api-service
uv run alembic upgrade head

# Seed demo data
uv run python -m app.scripts.seed_demo

# Run api-service
uv run uvicorn app.main:app --reload --port 8000

# In another terminal — frontend web
cd apps/web-app
pnpm dev                                     # http://localhost:5173

# In another terminal — ml-service
cd services/ml-service
uv run uvicorn app.main:app --reload --port 8001

# In another terminal — worker
cd services/worker-service
uv run celery -A app.celery_app worker --loglevel=info
```

### 16.2 Create a new migration

```bash
cd services/api-service
uv run alembic revision --autogenerate -m "add_survey_weight_column"
# Inspect the generated file in migrations/versions/
# Hand-edit if autogenerate is wrong
uv run alembic upgrade head
```

### 16.3 Build & deploy production

```bash
# Tag a release
git tag v1.2.3
git push --tags
# GitHub Actions builds, pushes the image, waits for manual approval, SSH-deploys
```

### 16.4 Manual backup (outside the scheduled job)

```bash
# Logical dump (geo + address — small schemas)
docker compose exec postgres pg_dump -U postgres \
    -n geo -n address -Fc lora > backup_$(date +%F).dump

# Push to R2
aws s3 cp backup_*.dump s3://lora-backups-prod/manual/ \
    --endpoint-url=$R2_ENDPOINT
```

### 16.5 Restore drill (run quarterly)

```bash
# On the staging VPS
docker compose exec postgres pg_restore -U postgres \
    -d lora_restore_test backup_2026-04-15.dump

# Verify row counts match
docker compose exec postgres psql -U postgres -d lora_restore_test \
    -c "SELECT COUNT(*) FROM geo.gateways;"
```

---

## Summary — onboarding checklist for new developers

After reading this document, you should be able to:

- [ ] Understand the 5 system layers and the rules for communication between them.
- [ ] Understand the 4 Repository capabilities and **not** try to add a fifth.
- [ ] Know when to use Mapbox, when MapLibre, when Leaflet.
- [ ] Know why `quarantine` and `training` are two separate tables.
- [ ] Know why `model_version` lives in the S3 key prefix.
- [ ] Know that Valkey is **triggered**, not deployed at v1.
- [ ] Know that Google Geocoding only runs when a sponsor is configured.
- [ ] Successfully set up locally using the commands in §16.1.
- [ ] Understand the `import-linter` rules and why they exist.
- [ ] Read further: `system-design.md` (strategic layer), `data-architecture.md` (DB details), `core-feature.md` (ML details), Ousterhout *A Philosophy of Software Design* Ch. 4–10, 17, 18.

---

*This document is the single source of truth for system architecture. Any technical decision contradicting this document must be recorded as an ADR (Architecture Decision Record) under `docs/adr/` and reviewed by the tech lead before merging.*

*Document version: v1.0 — May 2026*