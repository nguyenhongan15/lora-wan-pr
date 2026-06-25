# ml-service

FastAPI Stage 2 — Extra Trees end-to-end RSSI prediction on top of Stage 1 ITU-R P.1812 baseline.

**Status:** 🟡 Active nhưng generalization YẾU. Model `stage2-et-v0.7.0` deployed (ExtraTreesRegressor, 1500 trees, max_depth=20). Trên **spatial hold-out không rò rỉ** (H3 res-8 + session split): **test RMSE 6.32 dB, R² −0.08** — tức trên các ô lưới CHƯA thấy lúc train, model gần như **không tốt hơn việc đoán RSSI trung bình**. Số RMSE 3.50 dB / R² 0.90 trong các phiên bản README cũ là **random split bị leakage** (điểm cùng walk-session rơi cả vào train+test) → lạc quan, KHÔNG dùng làm số đại diện.

Nguyên nhân: dữ liệu hẹp (13 gateway, chủ yếu Đà Nẵng, ~10.9k điểm train phần lớn link 0–2 km). Đây là **distribution shift không gian**, không phải overfitting cổ điển — đã thử regularize đều làm val xấu hơn (xem [`scripts/train_extra_trees.py`](../../scripts/train_extra_trees.py) `ET_PARAMS`). Đòn bẩy thật là **thu thập thêm gateway/vùng**, không phải đổi siêu tham số.

Model vẫn được giữ active vì: (1) tốt hơn baseline XGBoost v0.6 (RMSE 10.58 → 6.32 dB), (2) chạy như **lớp tinh chỉnh** trên Stage 1 vật lý — Stage 2 fail thì fallback Stage 1, (3) độ bất định ML giờ được phản ánh trung thực trên UI qua `holdout_mse_db2` (dải ±σ ≈ ±7 dB thay vì chỉ shadow-fading), (4) **promotion gate** chặn retrain kém lên production. Chưa nên dùng làm số "chốt" cho thesis defense nếu chưa mở rộng dữ liệu.

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
{ "residual_db": -3.42, "model_version": "stage2-et-v0.7.0", "ood": false, "holdout_mse_db2": 54.5 }
```

`holdout_mse_db2` = MSE holdout của model (= val RMSE²), đọc từ `data/val_metrics.json` lúc load. api-service dùng làm **epistemic variance** để dải ±σ trên UI phản ánh đúng sai số ML (~±7 dB) thay vì chỉ shadow-fading. `null` nếu không đọc được val metrics.

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

### Performance (chất lượng dự đoán)

Split = **H3 res-8 + session hold-out không rò rỉ** (`scripts/build_training_csv.py` gán cột `data_split`; ô lưới train/val/test tách rời về không gian). Đây là số ĐÁNG TIN, đo bằng `scripts/eval_extra_trees_holdout.py` trên artifact active (`devices_history_full.csv`, 14017 điểm).

| Tập | n | RMSE (dB) | MAE (dB) | R² | Bias (dB) | Ý nghĩa |
|---|---:|---:|---:|---:|---:|---|
| Train (in-sample) | 10 867 | 2.78 | 1.69 | 0.944 | ~0 | Fit trên data đã thấy |
| **Val** (ô H3 mới) | 1 514 | 7.38 | 5.50 | 0.197 | — | Khái quát hóa thực |
| **Test** (ô H3 mới) | 1 636 | **6.32** | **4.75** | **−0.076** | −2.89 | **Số đại diện production** |
| XGBoost v0.6 (baseline) | — | 10.58 | — | — | — | Mốc cũ để so |

> **Đọc bảng:** gap train (R² 0.94) ↔ test (R² −0.08) rất lớn = model học tốt vùng đã thấy nhưng **không chuyển sang vùng mới**. R² âm nghĩa là trên ô lưới chưa thấy, dự đoán model còn tệ hơn hằng số trung bình. RMSE ~6 dB nghe nhỏ chỉ vì RSSI biến thiên hẹp. Bias −2.89 dB: model thiên về đoán RSSI **thấp hơn** thực tế (bi quan).

**Chất lượng theo khoảng cách link** (test split):

| Bin khoảng cách | n | RMSE (dB) | MAE (dB) | Bias (dB) |
|---|---:|---:|---:|---:|
| 0–2 km | 862 | 7.11 | 5.39 | −3.91 |
| 2–5 km | 150 | 9.26 | 8.22 | −7.13 |
| 5–10 km | 276 | 3.77 | 2.94 | +0.14 |
| 10–50 km | 348 | 3.83 | 3.08 | −0.95 |

> Nghịch lý: link ngắn (0–5 km) lại TỆ hơn link xa. Vì test cells ngắn nằm ở khu phố khác hẳn train; còn link xa do vài gateway "nóng" thống trị nên đoán ổn định hơn. Cảnh báo: với điểm 2–5 km model lệch tới −7 dB → trạng thái phủ sóng trên UI dễ bị đánh giá BI QUAN.

### Known limitations

- **Generalization không gian yếu (test R² ≈ 0)** — gốc rễ là dữ liệu hẹp (13 gateway, chủ yếu Đà Nẵng). Regularize KHÔNG cứu được (đã thử, val xấu hơn). Lối ra: thêm gateway + vùng địa lý vào `ts.survey_training` rồi retrain.
- **Gateway mới mất hiệu chuẩn**: `gateway` được OneHotEncode với `handle_unknown="ignore"` → gateway chưa có lúc train ra vector toàn 0 → dự đoán suy biến về "gateway trung bình". Heatmap/điểm cho gateway vừa thêm kém tin cậy tới khi retrain.
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
# Build training CSV từ ts.survey_training community + DEM/landuse (gán data_split)
uv run python scripts/build_training_csv.py

# Train Extra Trees, GHI ĐÈ model active (dùng khi train thủ công)
uv run python scripts/train_extra_trees.py

# …hoặc train ra artifact .candidate, KHÔNG đụng model active
uv run python scripts/train_extra_trees.py --candidate

# Eval trên H3 spatial hold-out (mặc định model active; --model để eval candidate)
uv run python scripts/eval_extra_trees_holdout.py
uv run python scripts/eval_extra_trees_holdout.py --model data/extra_trees_model.candidate.joblib
```

`train_extra_trees.py` atomic-swap artifact (ghi `.new` → rename) để ml-service không serve file dở khi đang load. Cờ `--candidate` đổi mọi output sang biến thể `*.candidate.*`.

### Qua Celery (admin retrain) — có PROMOTION GATE
Endpoint `/api/v1/admin/ml/retrain` (api-service) enqueue task `retrain_ml_model` → Celery worker:
1. `build_training_csv.py` → CSV mới (gán `data_split`).
2. `train_extra_trees.py --candidate` → ghi **artifact `.candidate`** (model active KHÔNG đổi).
3. `eval_extra_trees_holdout.py --model <candidate>` → đo test metrics của candidate.
4. **Promotion gate**: chỉ swap candidate → active + POST `/admin/reload` khi candidate đạt ngưỡng:
   - test RMSE ≤ 15 dB (sanity tuyệt đối), **và**
   - val RMSE không tệ hơn model active quá 1 dB (regression-guard, so với `data/active_model_metrics.json`).
   - Bootstrap (chưa có model active) → promote nếu qua sanity.
5. Trượt gate → **giữ model cũ**, xoá candidate, job vẫn `succeeded` nhưng `metrics.promoted=false` + `metrics.promotion_reason`. Admin panel hiển thị badge "Không áp dụng — giữ model cũ".

Mục tiêu: **một lần retrain tệ hơn không thể tự đẩy lên production** (trước đây model luôn bị ghi đè vô điều kiện). Chi tiết: memory `project_admin_delete_retrain_2026_06_11.md` + `project_retrain_csv_gap_2026_06_11.md`.

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
    processing/                      # Feature extraction (DEM + OSM + Fresnel)
      features.py terrain.py dem_lookup.py __init__.py
  data/
    extra_trees_model.joblib         # Active model artifact (đang serve)
    extra_trees_model.candidate.*    # Candidate (chỉ tồn tại trong lúc retrain; xoá nếu trượt gate)
    val_metrics.json                 # RMSE/MAE/R² trên VAL split → nguồn holdout_mse_db2
    train_metrics.json               # RMSE/MAE/R² in-sample của artifact hiện tại
    active_model_metrics.json        # Snapshot val/test của model active (promotion gate đọc để so sánh)
    terrain_fallback.json            # Fallback values cho terrain features
    gateway_table.csv                # Gateway lookup (lat/lon/freq) từ train set
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
- [x] Spatial hold-out eval không rò rỉ (H3+session) — số đại diện ở §2
- [x] Promotion gate: retrain kém không tự lên production (giữ model cũ)
- [x] Epistemic uncertainty (`holdout_mse_db2`) → dải ±σ trung thực trên UI
- [ ] Prometheus metrics endpoint (deferred)
- [ ] Model registry → R2 (currently filesystem only)
- [ ] **Mở rộng dữ liệu (thêm gateway/vùng) để kéo test R² > 0** — đòn bẩy chính còn lại
- [ ] Bỏ phụ thuộc one-hot `gateway` (thay bằng đặc trưng vật lý) để gateway mới không suy biến
