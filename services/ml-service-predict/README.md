# ml-service-predict

Service Predict-ML cho LoRa Coverage — phục vụ **truy vấn điểm** + **tra cứu hàng loạt**.

## Kiến trúc 

```
Stage 1 (vật lý, ITU-R P.1812 + P.2108)     
   │
   ▼
Stage 2 (LightGBM residual)       
   │  y_residual = rssi_measured - rssi_stage1
   │  Huber loss (α=0.9), Optuna TPE 100 trial, spatial grid GroupKFold (K=5)
   │  11 feature: hình học + DEM + OSM + pass-through device/gateway
   ▼
Stage 3 (SVGP, tùy chọn)         
   Matérn(ν=5/2, ARD), ~1000 inducing point — kích hoạt nếu Moran's I của residual > threshold
```

## Tại sao tách khỏi `api-service`

- LightGBM + (tùy chọn) GPyTorch có thể chiếm vài trăm MB → vài GB RAM.
- Cần hoán đổi version model mà không restart api-service.
- Scale ngang riêng theo tải predict, không kéo theo tầng HTTP.

## Layout hiện tại

```
services/ml-service-predict/
├── Dockerfile                       # Multi-stage uv + libpq/libgomp/libexpat
├── pyproject.toml
├── README.md
├── scripts/
│   ├── build_urbanization_grid.py   # Phase 3 — OSM PBF → GeoTIFF urbanization
│   └── train_stage2.py              # Phase 4 — CLI train + (tùy chọn) promote
├── artifacts/                       # gitignored — booster + meta.json cache local
└── src/lora_ml_predict/
    ├── config.py                    # Settings (env vars, validation)
    ├── features/
    │   ├── extractor.py             # FeaturePipeline + FeatureVector (11 cột)
    │   ├── dem.py                   # DemLookup (độ cao + LoS raycast)
    │   └── osm.py                   # UrbanizationLookup
    ├── stages/
    │   └── stage2_residual.py       # Stage2ResidualModel (wrapper booster)
    ├── training/
    │   ├── data.py                  # SQL fetch + compute residual + chia theo thời gian
    │   ├── spatial_cv.py            # Grid GroupKFold + Stratified fallback
    │   ├── objective.py             # Optuna TPE objective + final fit
    │   ├── orchestrator.py          # Compose: data → CV → tune → fit → registry
    │   └── registry_writer.py       # Lưu artifact + insert ml.model_runs + promote
    ├── registry/
    │   └── client.py                # load_active(): DB → artifact → Stage2ResidualModel
    └── serving/
        └── server.py                # FastAPI /residual + /healthz
```


## Training

Train + insert vào `ml.model_runs` (không promote):

```bash
python services/ml-service-predict/scripts/train_stage2.py
```

Train + tự động promote:

```bash
python services/ml-service-predict/scripts/train_stage2.py --promote
```

Pipeline (`training/orchestrator.py`):

1. **Fetch** `ts.survey_training` bbox ĐN + chia thời gian Nov-Dec/Jan-Feb (`data.py`).
2. **Tính residual** = `rssi_measured − Stage1Physics.predict()` (`data.py:230-234`).
3. **Trích 11 feature** qua `FeaturePipeline` (haversine, bearing, gần thứ 2, DEM độ cao + LoS, OSM urbanization, SF, freq, anten gw).
4. **Spatial grid GroupKFold (K=5)** cell 0.025°, fallback StratifiedGroupKFold nếu mất cân bằng > 3× (`spatial_cv.py`).
5. **Optuna TPE 100 trial** tinh chỉnh 9 hyperparam, Huber α=0.9, metric RMSE (`objective.py`).
6. **Refit** best params trên toàn bộ train+val, random 20% val cho early stop.
7. **Eval test** (hold-out Jan-Feb) → RMSE/MAE.
8. **Persist**: `artifacts/stage2/<version>/{model.lgb, meta.json}` + insert `ml.model_runs`.

## Serving

Container `lora-wan-ml-predict` (port 8001, mạng Docker nội bộ). Lifespan (`serving/server.py:110-135`):

1. Load `DemLookup` + `UrbanizationLookup` (handle raster, mở 1 lần).
2. Load **toàn bộ gateway** trong bbox cho `FeaturePipeline.distance_to_2nd_nearest`.
3. `load_active()` truy vấn `ml.active_models WHERE domain='predict' AND stage=2` → load booster LightGBM.
4. Pin lên `app.state.{pipeline, stage2, settings}` → request đồng thời đọc thread-safe.

Endpoint:

| Method | Path | Auth | Mục đích |
|---|---|---|---|
| GET | `/healthz` | none | Healthcheck Docker + readiness — trả `model_version` + `has_stage2` |
| POST | `/residual` | Bearer token | Trích feature + dự đoán residual_db. 503 nếu chưa có model active |

Schema request (`Stage2Request`): `{target: {lat, lon, sf, freq}, serving_gateway: {id, code, name, lat, lon, altitude_m, antenna_height_m, antenna_gain_dbi, tx_power_dbm, frequency_mhz}}`.

Schema response (`Stage2Response`): `{residual_db: float, model_version: str}`.

Smoke test đầu-cuối (qua api-service):

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/coverage/predict \
  -H 'Content-Type: application/json' \
  -d '{"latitude": 16.06, "longitude": 108.25, "spreading_factor": 10, "frequency_mhz": 923.0}'
```

`model_version` trong response phải là `stage1-itu-p1812-v0.1.0+stage2-<timestamp>` khi Stage 2 còn active. `stage1-...` trơn nghĩa là api-service đã fallback (timeout / 503 / network).

## FeatureVector — 11 cột (Phase 3+)

| Cột | Đơn vị | Nguồn |
|---|---|---|
| `log10_distance_to_serving_gw_km` | log10 km | haversine, floor 1 m |
| `bearing_sin`, `bearing_cos` | [-1, 1] | atan2 → (sin, cos) chống wrap 359→0° |
| `distance_to_2nd_nearest_gw_km` | km | linear scan danh sách gw candidate |
| `elevation_diff_m` | m | DEM bilinear (target - gw) |
| `los_obstruction_count` | int ≥ 0 | DEM Bresenham raycast |
| `urbanization_index` | [0, 1] | tỷ lệ OSM building footprint R=200m |
| `spreading_factor` | int 7..12 | request payload |
| `frequency_mhz` | float ~923 | request payload |
| `gw_antenna_height_m` | m AGL | bản ghi gateway |
| `gw_antenna_gain_dbi` | dBi | bản ghi gateway |

KHÔNG bao gồm `snr_db` (leak — chỉ có lúc đo) hay `hour`/`weekday` (API không nhận timestamp). Thứ tự tuyệt đối khớp `training.data.FEATURE_COLUMNS` — booster predict theo index cột.


## Yêu cầu raster 

Đặt file ngoài repo, trỏ qua env var. Docker compose mount `${LORA_DATA_DIR}:/data:ro` (chỉ đọc).

| Env var | File hiện tại | Nguồn |
|---|---|---|
| `LORA_DEM_PATH` | `copernicus_glo30_danang.tif` (~85MB, **bbox 15.37-16.63°N, 106.95-108.76°E**) | [OpenTopography](https://portal.opentopography.org/raster?opentopoID=OTSDEM.032021.4326.3) — Copernicus GLO-30. Hiện chỉ phủ Đà Nẵng + lân cận do OpenTopography rate-limit; Hải Phòng cần tải bổ sung sau. |
| `LORA_OSM_PBF_PATH` | `vietnam-260512.osm.pbf` (~310MB) | [Geofabrik](https://download.geofabrik.de/asia/vietnam-latest.osm.pbf) |
| `LORA_URBANIZATION_PATH` | `urbanization_vn.tif` (~10-50MB, bbox toàn VN) | Build từ PBF qua script (xem bên dưới) |

Build GeoTIFF urbanization:
```bash
uv pip install -e 'services/ml-service-predict[build]'
python services/ml-service-predict/scripts/build_urbanization_grid.py \
  --pbf $LORA_OSM_PBF_PATH \
  --out $LORA_URBANIZATION_PATH
```
Thời gian build: 5-15 phút CPU (chạy 1 lần khi PBF update; OSM dump theo quý là đủ tươi).

## Registry & artifact

- `ml.model_runs` (PostgreSQL) — 1 row mỗi lần train: `model_version`, `dataset_hash`, `artifact_uri`, `metrics` (JSONB), `hyperparams` (JSONB), `notes`.
- `ml.active_models` — con trỏ (`domain='predict'`, `stage=2`) → `model_version`. Swap atomic qua `registry_writer.promote()`.
- `artifact_uri` lưu dạng **tương đối** từ repo root, dùng forward slash → cùng path ở host & container nhờ docker-compose mount mirror (`./services/ml-service-predict/artifacts:/app/services/ml-service-predict/artifacts`).
- Migration: `migrations/versions/0011_ml_schema_and_registry.py`.



