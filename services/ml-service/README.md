# ml-service

FastAPI Stage 2 — Extra Trees end-to-end RSSI prediction on top of Stage 1 ITU-R P.1812 baseline.

**Status:** ✅ Active. Model `stage2-et-v0.7.0` deployed. ExtraTreesRegressor (1500 trees, max_depth=20). Test RMSE 3.50 dBm trên random stratified-by-gateway split (n_test=2042) của `devices_history_full.csv`; chưa verify trên temporal hold-out Jan–Feb 2026.

---

## 1. Service contract

| Endpoint | Method | Auth | Mô tả |
|---|---|---|---|
| `/healthz` | GET | none | Liveness probe |
| `/residual` | POST | Bearer | Single-point delta `(residual_db, model_version)` |
| `/residuals/batch` | POST | Bearer | Batch tối đa 5000 target |
| `/admin/reload` | POST | Bearer | Hot-reload joblib artifact sau Celery retrain |

**Lưu ý tên field `residual_db`:** giữ nguyên cho ổn định API contract. Bản chất hiện tại = `rssi_et − stage1_rssi_dbm` (delta dB để chuyển Stage 1 baseline → ET end-to-end prediction). api-service cộng delta này vào Stage 1 RSSI → kết quả cuối = ET prediction.

**Request body** (`/residual`):
```json
{
  "target": {
    "latitude": 16.05, "longitude": 108.21,
    "spreading_factor": 10, "frequency_mhz": 923.0,
    "stage1_rssi_dbm": -108.4
  },
  "serving_gateway": {
    "id": "...", "code": "...", "name": "...",
    "latitude": 16.05480, "longitude": 108.21993,
    "altitude_m": 0.0, "antenna_height_m": 15.0,
    "antenna_gain_dbi": 6.0, "tx_power_dbm": 14.0,
    "frequency_mhz": 923.0
  }
}
```

`stage1_rssi_dbm` bắt buộc — ET train trên RSSI tuyệt đối, phải biết baseline để trả ra delta.

**Response**:
```json
{ "residual_db": -3.42, "model_version": "stage2-et-v0.7.0", "ood": false }
```

OOD (lat/lon ngoài bbox VN, SF ngoài [7,12], freq ngoài AS923-2) → `ood: true`, `residual_db: null`. api-service treat null như Stage 1 only fallback.

**Auth**: shared bearer token qua env `LORA_STAGE2_AUTH_TOKEN`. api-service gửi `Authorization: Bearer <token>` mỗi request.

---

## 2. Model

- **Algorithm**: ExtraTreesRegressor (`scikit-learn`), 1500 trees, max_depth=20, min_samples_split=5, min_samples_leaf=2.
- **Target**: RSSI tuyệt đối (dBm) — end-to-end, KHÔNG phải residual của Stage 1.
- **Features (21)**: 20 numeric + 1 categorical:
  - Geometry: `log_distance`, `log_distance_3d`, `delta_lat`, `delta_lon`, `angle`, `elevation_angle`
  - Terrain DEM: `gw_elevation`, `delta_elevation`, `slope`, `roughness`, `terrain_mean/std/min/max`
  - Fresnel: `fresnel_obstruction_ratio`, `min_fresnel_clearance`, `mean_fresnel_clearance`
  - Land cover: `residential_ratio`
  - Radio: `frequency`, `spreading_factor`
  - Categorical: `gateway` (OneHotEncoded)
- **Training data**: `services/ml-service/reference_wireless/data/processed/devices_history_full.csv` (chuẩn bị từ `ts.survey_training` qua `scripts/build_training_csv.py`).
- **Pipeline**: `ColumnTransformer` (median imputer + StandardScaler cho numeric; most-frequent imputer + OneHotEncoder cho categorical) → `ExtraTreesRegressor`.
- **Artifact**: `data/extra_trees_model.joblib` (~113 MB).

### Performance

| Metric | Extra Trees v0.7 | XGBoost (cùng 21 feat) |
|---|---:|---:|
| Test RMSE | **3.50 dBm** | 3.80 dBm |
| Test MAE | 2.03 dBm | 2.18 dBm |
| Test R² | 0.8955 | 0.8765 |
| Test bias | −0.00 dB | — |
| Train RMSE | 1.89 dBm | 2.20 dBm |

Split: stratified by gateway, 80/20 (n_train=8168, n_test=2042). **Đây là random split chứ không phải temporal hold-out Jan–Feb 2026** — có thể có leakage cùng walk session. Số liệu defendable cho thesis cần chạy `scripts/eval_extra_trees_holdout.py` riêng.

### Known limitations

- Random split (không phải temporal) → optimistic so với production.
- 21-feat phụ thuộc DEM + OSM lookup runtime → latency cao hơn pure-physics. Stage2 timeout 3s ở api-service config có headroom cho việc này.
- Bias correction từng thử (-4.67 dB hardcode) đã revert vì overfit-to-holdout; rely vào retrain pipeline thay vì hardcode (memory `project_ml_bias_correction_2026_06_14.md`).

---

## 3. Local development

```bash
cd services/ml-service
uv sync
LORA_STAGE2_AUTH_TOKEN=dev-token \
LORA_ML_MODEL_PATH=$(pwd)/data/extra_trees_model.joblib \
  uv run uvicorn lora_ml_predict.app:app --reload --port 8001
```

Smoke test:
```bash
curl -s http://localhost:8001/healthz
# {"status":"ok"}

curl -s -X POST http://localhost:8001/residual \
  -H "Authorization: Bearer dev-token" \
  -H "content-type: application/json" \
  -d '{
    "target":{"latitude":16.05,"longitude":108.21,"spreading_factor":10,
              "frequency_mhz":923.0,"stage1_rssi_dbm":-108.4},
    "serving_gateway":{"id":"...","code":"gw1","name":"GW1",
                       "latitude":16.0548,"longitude":108.2199,
                       "altitude_m":0,"antenna_height_m":15,
                       "antenna_gain_dbi":6,"tx_power_dbm":14,
                       "frequency_mhz":923}
  }'
```

---

## 4. Re-train

### Standalone (CLI)
```bash
# Build training CSV từ ts.survey_training community + DEM/landuse
uv run python scripts/build_training_csv.py

# Train Extra Trees từ CSV vừa build
uv run python scripts/train_extra_trees.py

# Eval trên temporal hold-out (Jan–Feb 2026)
uv run python scripts/eval_extra_trees_holdout.py
```

`train_extra_trees.py` atomic-swap artifact (ghi `.new` → rename) để ml-service không serve file dở khi đang load.

### Qua Celery (admin retrain)
Endpoint `/api/v1/admin/ml/retrain` (api-service) enqueue task `retrain_ml_model` → Celery worker chạy `build_training_csv.py` → `train_extra_trees.py` → POST `/admin/reload` tới ml-service (hot reload, không cần restart container). Chi tiết: memory `project_admin_delete_retrain_2026_06_11.md` + `project_retrain_csv_gap_2026_06_11.md`.

Sau khi swap artifact:
- Hot-reload: ml-service tự pickup qua `/admin/reload` call do Celery gọi.
- Cold restart: `docker compose up -d --build ml-service` (không có source volume mount — code COPY at build).

`model_version` là string hardcode trong `src/lora_ml_predict/app.py` (`Settings.model_version`); bump tay khi đổi binding hoặc feature set (memory `project_ml_service_label_baked.md`).

---

## 5. Wiring vào api-service

Trong `.env`:
```
STAGE2_PREDICT_BASE_URL=http://ml-service:8001
LORA_STAGE2_AUTH_TOKEN=<shared-token>
STAGE2_TIMEOUT_SECONDS=3.0
```

Rebuild api-service (cũng không có source volume):
```bash
docker compose up -d --build api-service
```

api-service tự gọi `/residual` cho từng request `/api/v1/coverage/predict`. Timeout/500/503/OOD → graceful fallback Stage 1 only (response vẫn 200, `model_version` không có phần stage2).

Heatmap "Bản đồ ước lượng" KHÔNG dùng ml-service (drop từ 2026-06-09) — chạy P.1812 + DTM + per-gw NF + survey overlay pure-physics. Chi tiết: memory `project_ml_deferred.md`.

---

## 6. File layout

```
services/ml-service/
  Dockerfile                         # Python 3.12 + sklearn + crc-covlib runtime
  pyproject.toml                     # Package name: lora-ml-predict
  src/lora_ml_predict/
    app.py                           # FastAPI app + model loading + endpoints
    processing.py                    # Feature extraction (DEM + OSM + Fresnel)
  data/
    extra_trees_model.joblib         # Active model artifact
    terrain_fallback.json            # Fallback values cho terrain features
    gateway_table.csv                # Gateway lookup (lat/lon/freq) từ train set
    train_metrics.json               # RMSE/MAE/R² của artifact hiện tại
  reference_wireless/                # Upstream reference pipeline, không wire trực tiếp
```

Legacy `data/stage2_xgb.joblib` còn trong repo cho rollback option, không được load runtime.

---

## 7. Production checklist

- [x] Bearer auth required on prediction endpoints
- [x] OOD guard rejects out-of-Vietnam coordinates
- [x] Stateless (no DB connection) — model loaded once at boot
- [x] Hot-reload via `/admin/reload` (Celery retrain không cần container restart)
- [x] Atomic artifact swap (`.new` → rename) trong train script
- [ ] Prometheus metrics endpoint (deferred)
- [ ] Model registry → R2 (currently filesystem only)
- [ ] Temporal hold-out eval (Jan–Feb 2026) làm số chính cho thesis defense
