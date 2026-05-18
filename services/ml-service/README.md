# ml-service

LoRa coverage ML prediction service. **Status: empty — waiting for new ML dev to build from scratch.**

This folder is intentionally empty except for this README and `reference_wireless/`. The previous LightGBM-residual code that the platform owner built before the handoff has been moved to `archive/stage2-lightgbm/` (kept in the repo as a personal-reference benchmark, not deployed). `api-service` currently runs Stage-1-only — `STAGE2_PREDICT_BASE_URL` is empty in `.env`, so the api-service stage2 client short-circuits and responses carry `model_version = "stage1-itu-p1812-v0.1.0"` only.

---

## 1. Platform context (read first)

- **Product**: Vietnam LoRaWAN coverage prediction platform. Two user flows:
  1. **Point prediction** — given (lat, lon, gateway, SF), return RSSI/SNR/coverage/confidence. *This is what `ml-service` will serve.*
  2. **Min-SF coverage map** — precomputed raster showing the minimum reliable SF per pixel. Pure physics.
- **Region**: Vietnam only, AS923-2 frequency plan, 14 dBm TX cap. Pilot data is Đà Nẵng (11 gateways) + Hải Phòng (2 gateways).
- **Stage 1**: ITU-R P.1812-7 + P.2108 clutter loss, via `crc-covlib`. Code lives in `services/api-service/src/lora_coverage_api/application/itu/` + `infrastructure/itu/crc_covlib_backend.py`. **Do not change Stage 1.** You consume it.
- **Measured Stage 1 quality on test set (Jan–Feb 2026 hold-out)**: bias ≈ +11.65 dB systematic underprediction of loss (Stage 1 too pessimistic), RMSE 7–14 dB over 2–30 km. There is signal for ML to recover.
- **Architecture rule**: api-service follows a strict 5-layer split (edge → application → domain ← infrastructure) enforced by `import-linter`. ml-service is a separate process — couple to api-service **only via HTTP** (no direct imports beyond what the workspace exposes as a shared library, if you opt into the workspace).

---

## 2. Reference material in this repo

### `services/ml-service/reference_wireless/` — the model you authored before joining this codebase

This is the `Wireless-Coverage-Prediction` project (XGBoost direct-RSSI predictor) moved here so you find it without grepping. Not wired into anything. Use it as the reference implementation for feature engineering you already validated (Fresnel obstruction, terrain roughness, landuse ratios from OSM) and the `ColumnTransformer + tree model` pipeline shape.

### `archive/stage2-lightgbm/` — the platform owner's personal Stage 2 LightGBM build

Frozen. RMSE **6.41 dB** on the same Jan–Feb 2026 test set. Kept as a benchmark to beat — not as a starting point you must extend. See `archive/stage2-lightgbm/README.md` for the feature list, training scope, hyperparameter search settings, and lessons learned.

### Other repo locations you'll want to know

- `services/api-service/src/lora_coverage_api/infrastructure/stage2_client.py` — HTTP client api-service uses to call your service. You change the contract; this client adapts.
- `migrations/` — DB schema (PostgreSQL 17 + PostGIS 3.5 + TimescaleDB 2.17). Training data lives in the `training` hypertable (validated rows promoted from `quarantine`).
- `scripts/validate_stage1_itu.py` — Stage 1-only validator. Reproduce the +11.65 dB bias / 7–14 dB RMSE numbers against fresh data.

---

## 3. Fixed constraints (you cannot change these)

- **Region**: Vietnam only. AS923-2, 14 dBm TX cap. Multi-region is future work — do not design for it.
- **DEM source**: **Copernicus GLO-30** GeoTIFF tiles. Host path is `LORA_DATA_DIR` (default `E:/DATN/lora-data`), mounted read-only into the container at `/data`. Surface DEM at `/data/dem-surface` is optional and only used by Stage 1 P.1812 surface mode.
- **DB schema**: owned by api-service migrations. Do not migrate the DB yourself; if you need a new column, file an ADR or PR against api-service migrations.
- **Train/val/test split**: train+val = random sample from Nov–Dec 2025, test = Jan–Feb 2026 hold-out. Derived in the query, never persisted. Use the same split if you want to compare against the 6.41 dB baseline.
- **Auth**: bearer token shared via `LORA_STAGE2_AUTH_TOKEN`. api-service sends `Authorization: Bearer <token>`. You must verify it on every request.

---

## 4. What is yours to decide

Everything inside this folder. Specifically:

- **Service stack** — Python deps, package name, entrypoint, framework. Nothing is reserved.
- **Model architecture** — LightGBM, XGBoost, neural net, ensemble, anything. The 6.41 dB RMSE on the Jan–Feb 2026 test set is the bar.
- **Prediction target** — residual (correction to Stage 1) vs direct RSSI (skip Stage 1 at inference). Either works on api-service side; you just need to coordinate the response shape.
- **HTTP contract** — the archived service used `POST /residual` returning `(residual_db, model_version)`. You can keep that, change the route, or split into multiple endpoints (`/predict`, `/batch`, `/lookup`). Coordinate with api-service via `infrastructure/stage2_client.py`.
- **Feature pipeline** — what to extract from DEM/OSM/gateway metadata, how to encode it, whether to precompute per-tile or compute per-request.
- **OOD / guardrail / registry** — how to detect out-of-distribution requests, how to clip residuals (if any), where to store model artifacts (filesystem, S3/R2, MLflow).
- **Training scope** — which devices, which time window, which gateways, whether to include Hải Phòng. Document your choice in the trained artifact's metadata.
- **Workspace integration** — opt-in. If you add a `pyproject.toml` here and register the folder under `[tool.uv.workspace]` in the root `pyproject.toml`, you get free workspace dep access to `lora-coverage-api` (for Stage 1 sharing). Or stay out of the workspace if you prefer a fully separate Python env.
- **Container** — your own `Dockerfile`. Wire it into `docker-compose.yml` when ready (the previous block was removed; see the comment in that file for the placeholder).

---

## 5. Bringing a service online (when you have a model)

1. Add `services/ml-service/pyproject.toml` (and `src/` etc.) with your chosen stack.
2. If joining the uv workspace: add `"services/ml-service"` back to `[tool.uv.workspace] members` in the root `pyproject.toml` and run `uv lock`.
3. Add a Dockerfile and a service block in `docker-compose.yml` (replace the placeholder comment).
4. Set `STAGE2_PREDICT_BASE_URL=http://ml-service:8001` (or whatever route/port you pick) in `.env`.
5. Rebuild api-service: `docker compose up -d --build api-service` (api-service has no source volume — code is `COPY`'d at build time, so `restart` alone is not enough).
6. Smoke-test against `/healthz` first, then through api-service's `/api/v1/coverage/predict`.


Document your answers in this README when you decide.
