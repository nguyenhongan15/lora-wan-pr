# ml-service-predict

Predict-ML service cho LoRa Coverage — phục vụ **point query** + **bulk lookup**.

> **Trạng thái (2026-05-13)**: Phase 4 (training) + Phase 5 (serving) **đã live**. Stage 2 LightGBM residual (`stage2-20260513T131351Z`) đã train + promote + serve qua HTTP nội bộ. api-service gọi `/residual` mỗi `/coverage/predict`, fallback Stage 1 mọi lỗi. Phase 6/7/8 chưa build.

## Phạm vi

| Phục vụ | Endpoint (api-service) | Inference budget |
|---|---|---|
| Tab "Dự đoán điểm" | `POST /api/v1/coverage/predict` | ms-level/query |
| Tab "Tra cứu hàng loạt" | `POST /api/v1/coverage/batch` | ms-level/query |

**KHÔNG** phục vụ `/map` (heatmap). Đó là phạm vi của `services/ml-service-hmap/` — model riêng, owner riêng, deploy độc lập (xem `u-work/ml-plan/plan-v1.md` §0 + §20).

## Architecture (theo plan-v1)

```
Stage 1 (physics, log-distance)   ← sống ở api-service, SHARED với ml-service-hmap
   │
   ▼
Stage 2 (LightGBM residual)        ← service này, LIVE
   │  y_residual = rssi_measured - rssi_stage1
   │  Huber loss (α=0.9), Optuna TPE 100 trial, spatial grid GroupKFold (K=5)
   │  11 feature: geometry + DEM + OSM + pass-through device/gateway
   ▼
Stage 3 (SVGP, optional)           ← service này, DEFER
   Matérn(ν=5/2, ARD), ~1000 inducing points — kích hoạt nếu Moran's I residual > threshold
```

api-service gọi qua HTTP `POST /residual` + Bearer token; nhận `{residual_db, model_version}` rồi cộng vào RSSI Stage 1. Mọi failure path (timeout 0.5s, 503, 4xx) → fallback Stage 1.

## Tại sao tách khỏi `api-service`

- LightGBM + (optional) GPyTorch có thể chiếm vài trăm MB → vài GB RAM.
- Cần swap model version mà không restart api-service.
- Scale ngang riêng theo predict load, không kéo theo HTTP layer.
- 12-Factor V (build/release/run): training artifact là release riêng, runtime tải từ filesystem/R2.

## Layout hiện tại

```
services/ml-service-predict/
├── Dockerfile                       # Multi-stage uv + libpq/libgomp/libexpat
├── pyproject.toml
├── README.md
├── scripts/
│   ├── build_urbanization_grid.py   # Phase 3 — OSM PBF → urbanization GeoTIFF
│   └── train_stage2.py              # Phase 4 — CLI train + (optional) promote
├── artifacts/                       # gitignored — booster + meta.json local cache
└── src/lora_ml_predict/
    ├── config.py                    # Settings (env vars, validation)
    ├── features/
    │   ├── extractor.py             # FeaturePipeline + FeatureVector (11 cột)
    │   ├── dem.py                   # DemLookup (elev + LoS raycast)
    │   └── osm.py                   # UrbanizationLookup
    ├── stages/
    │   └── stage2_residual.py       # Stage2ResidualModel (booster wrapper)
    ├── training/
    │   ├── data.py                  # SQL fetch + residual compute + time split
    │   ├── spatial_cv.py            # Grid GroupKFold + Stratified fallback
    │   ├── objective.py             # Optuna TPE objective + final fit
    │   ├── orchestrator.py          # Compose: data → CV → tune → fit → registry
    │   └── registry_writer.py       # Save artifact + ml.model_runs insert + promote
    ├── registry/
    │   └── client.py                # load_active(): DB → artifact → Stage2ResidualModel
    └── serving/
        └── server.py                # FastAPI /residual + /healthz
```

## Build order

Theo plan-v1 §11 (incremental — không bắt đầu Phase N+1 nếu Phase N chưa green trên staging):

| Phase | Scope | Trạng thái |
|---|---|---|
| 1 | Stage 1 cải tiến (EnvironmentProfile, Confidence variance) | ✅ ở `api-service/.../path_loss.py` + `domain/coverage.py` |
| 2 | Feature pipeline — haversine + bearing + 2nd-gw distance | ✅ `features/extractor.py` |
| 3 | DEM + OSM (LoS raycast, urbanization index) | ✅ `features/dem.py`, `features/osm.py` |
| 4 | Training pipeline (orchestrator, spatial CV, LightGBM fit, model_runs) | ✅ `training/` |
| 5 | Stage 2 serving (FastAPI, PredictionService orchestrator ở api-service) | ✅ `serving/server.py` + `api-service/.../prediction_service.py` |
| 6 | Retrain triggers (drift detector, cron, eligibility) | ⏳ |
| 7 | Observability (SLI/SLO, dashboards, alerts) | ⏳ |
| 8 | Stage 3 SVGP — CHỈ build nếu Moran's I trên Stage 2 residual > threshold | ⏳ |

## Training

Train + insert vào `ml.model_runs` (không promote):

```bash
python services/ml-service-predict/scripts/train_stage2.py
```

Train + auto-promote:

```bash
python services/ml-service-predict/scripts/train_stage2.py --promote
```

Pipeline (`training/orchestrator.py`):

1. **Fetch** `ts.survey_training` DN bbox + time-split Nov-Dec/Jan-Feb (`data.py`).
2. **Compute residual** = `rssi_measured − Stage1Physics.predict()` (`data.py:230-234`).
3. **Extract 11 feature** qua `FeaturePipeline` (haversine, bearing, 2nd-nearest, DEM elev + LoS, OSM urbanization, SF, freq, gw antenna).
4. **Spatial grid GroupKFold (K=5)** 0.025° cell, fallback StratifiedGroupKFold nếu imbalance > 3× (`spatial_cv.py`).
5. **Optuna TPE 100 trial** tune 9 hyperparam, Huber α=0.9, RMSE metric (`objective.py`).
6. **Refit** best params trên full train+val, random 20% val cho early stop.
7. **Eval test** (Jan-Feb hold-out) → RMSE/MAE.
8. **Persist**: `artifacts/stage2/<version>/{model.lgb, meta.json}` + insert `ml.model_runs`.

Metrics run hiện tại:

| | CV mean | per fold | test |
|---|---|---|---|
| RMSE (dB) | 4.58 | [3.63, 4.33, 3.65, 5.62, 5.67] | 12.29 (temporal drift, defer) |

## Serving

Container `lora-wan-ml-predict` (port 8001, mạng nội bộ Docker). Lifespan (`serving/server.py:110-135`):

1. Load `DemLookup` + `UrbanizationLookup` (raster handle, mở 1 lần).
2. Load **all gateway** trong bbox cho `FeaturePipeline.distance_to_2nd_nearest`.
3. `load_active()` query `ml.active_models WHERE domain='predict' AND stage=2` → load LightGBM booster.
4. Pin lên `app.state.{pipeline, stage2, settings}` → concurrent request đọc thread-safe.

Endpoints:

| Method | Path | Auth | Mục đích |
|---|---|---|---|
| GET | `/healthz` | none | Docker healthcheck + readiness — trả `model_version` + `has_stage2` |
| POST | `/residual` | Bearer token | Extract feature + predict residual_db. 503 nếu chưa có active model |

Request schema (`Stage2Request`): `{target: {lat, lon, sf, freq}, serving_gateway: {id, code, name, lat, lon, altitude_m, antenna_height_m, antenna_gain_dbi, tx_power_dbm, frequency_mhz}}`.

Response schema (`Stage2Response`): `{residual_db: float, model_version: str}`.

Smoke test end-to-end (qua api-service):

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/coverage/predict \
  -H 'Content-Type: application/json' \
  -d '{"latitude": 16.06, "longitude": 108.25, "spreading_factor": 10, "frequency_mhz": 923.0}'
```

`model_version` trong response phải là `stage1-loglike-v0.1.0+stage2-<timestamp>` khi Stage 2 còn active. Plain `stage1-...` nghĩa là api-service fallback (timeout / 503 / network).

## FeatureVector — 11 cột (Phase 3+)

| Cột | Đơn vị | Nguồn |
|---|---|---|
| `log10_distance_to_serving_gw_km` | log10 km | haversine, floor 1 m |
| `bearing_sin`, `bearing_cos` | [-1, 1] | atan2 → (sin, cos) chống wrap 359→0° |
| `distance_to_2nd_nearest_gw_km` | km | linear scan candidate gw list |
| `elevation_diff_m` | m | DEM bilinear (target - gw) |
| `los_obstruction_count` | int ≥ 0 | DEM Bresenham raycast |
| `urbanization_index` | [0, 1] | OSM building footprint fraction R=200m |
| `spreading_factor` | int 7..12 | request payload |
| `frequency_mhz` | float ~923 | request payload |
| `gw_antenna_height_m` | m AGL | gateway record |
| `gw_antenna_gain_dbi` | dBi | gateway record |

KHÔNG include `snr_db` (leak — chỉ có lúc đo) hoặc `hour`/`weekday` (API không nhận timestamp). Order tuyệt đối khớp `training.data.FEATURE_COLUMNS` — booster predict theo column index.

**Define errors out of existence** (plan §8.1): < 2 candidate gw → `d_2nd = inf` (→ 999.0 ở training). `target ≡ serving` → `log10` clamp về `-3.0`. Điểm ngoài DEM/OSM bbox → 0.0 (sea level / rural fallback). Không raise per-call. DEM/OSM file missing → raise tại construct (fail-fast).

## Raster prerequisites (Phase 3)

Đặt file ngoài repo (12-Factor III), trỏ qua env var. Docker compose mount `${LORA_DATA_DIR}:/data:ro` (read-only).

| Env var | File hiện tại | Source |
|---|---|---|
| `LORA_DEM_PATH` | `copernicus_glo30_danang.tif` (~85MB, **bbox 15.37-16.63°N, 106.95-108.76°E**) | [OpenTopography](https://portal.opentopography.org/raster?opentopoID=OTSDEM.032021.4326.3) — Copernicus GLO-30. Hiện chỉ phủ Đà Nẵng + lân cận do OpenTopography rate-limit; Hải Phòng cần tải bổ sung sau. |
| `LORA_OSM_PBF_PATH` | `vietnam-260512.osm.pbf` (~310MB) | [Geofabrik](https://download.geofabrik.de/asia/vietnam-latest.osm.pbf) |
| `LORA_URBANIZATION_PATH` | `urbanization_vn.tif` (~10-50MB, full VN bbox) | Build từ PBF qua script (xem dưới) |

Build urbanization GeoTIFF:
```bash
uv pip install -e 'services/ml-service-predict[build]'
python services/ml-service-predict/scripts/build_urbanization_grid.py \
  --pbf $LORA_OSM_PBF_PATH \
  --out $LORA_URBANIZATION_PATH
```
Build time: 5-15 phút CPU (1-shot khi PBF update; OSM dump quarterly là đủ tươi).

## Registry & artifact

- `ml.model_runs` (PostgreSQL) — 1 row mỗi lần train: `model_version`, `dataset_hash`, `artifact_uri`, `metrics` (JSONB), `hyperparams` (JSONB), `notes`.
- `ml.active_models` — pointer (`domain='predict'`, `stage=2`) → `model_version`. Atomic swap qua `registry_writer.promote()`.
- `artifact_uri` lưu **relative** từ repo root, dùng forward slash → cùng path host & container nhờ docker-compose mount mirror (`./services/ml-service-predict/artifacts:/app/services/ml-service-predict/artifacts`).
- Migration: `migrations/versions/0011_ml_schema_and_registry.py`.

## Boundary với `ml-service-hmap`

Xem `u-work/ml-plan/plan-v1.md` §20.

| Shared | Không shared |
|---|---|
| `Stage1Physics` (ở `api-service/.../path_loss.py`) | Feature pipeline (`features/`) |
| `ModelRegistry` (R2 + DB, namespace `domain ∈ {predict, map}`) | Stage 2 (LightGBM), Stage 3 (SVGP) |
| Schema `ml.model_runs`, `ml.active_models` | Container, Dockerfile |
| Bảng `ts.survey_training` (read-only) | R2 prefix (`models/predict/*` vs `models/map/*`) |

Sửa shared module → cần ADR + 2 team approve. Sửa nội bộ (loss, hyperparam, retrain) → tự do.

## Known issues

- **Test RMSE 12.29 dB vs CV 4.58 dB** ⇒ temporal drift Nov-Dec → Jan-Feb (deferred).
- `coverage_status` ở api-service vẫn classify dựa Stage 1 RSSI, chưa re-classify sau khi áp residual. Khi residual lớn (vd -15 dB) có thể over-optimistic. Phase 7 refactor (expose `classify()` public + áp residual cho margin trước classify).
- Phase 6 (retrain trigger), Phase 7 (SLI/SLO dashboard), Phase 8 (Stage 3 SVGP) chưa build.

## Plan đầy đủ

- `u-work/ml-plan/plan-v1.md` — design goals, module breakdown, tradeoffs, risks, boundary contract.
- `u-work/ml-plan/choose-ml-model.md` — lý do chọn Option C (Physics → LightGBM → SVGP).
