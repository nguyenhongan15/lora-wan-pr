# ml-service

FastAPI Stage 2 — XGBoost residual correction on top of Stage 1 ITU-R P.1812 path-loss prediction.

**Status:** ✅ Active. Model `stage2-xgb-v0.6.0` deployed. RMSE 10.59 dB on Jan–Feb 2026 hold-out (n=337, 4 gw outdoor).

---

## 1. Service contract

| Endpoint | Method | Auth | Mô tả |
|---|---|---|---|
| `/healthz` | GET | none | Liveness probe |
| `/residual` | POST | Bearer | Single-point residual `(δ_dB, model_version)` |
| `/residuals/batch` | POST | Bearer | Batch tối đa 5000 target |

**Request body** (`/residual`):
```json
{
  "target": { "lat": 16.05, "lon": 108.21, "sf": 10 },
  "serving_gateway": {
    "lat": 16.05480, "lon": 108.21993,
    "altitude_m": 0.0, "antenna_height_m": 15.0,
    "frequency_mhz": 923.0
  }
}
```

**Response**:
```json
{ "residual_db": -3.42, "model_version": "stage2-xgb-v0.6.0", "confidence": "in_distribution" }
```

OOD (lat/lon ngoài bbox VN, SF ngoài [7,12], freq ngoài AS923-2) → `confidence: "out_of_distribution"`, `residual_db: null`. api-service treat null như Stage 1 only fallback.

**Auth**: shared bearer token qua env `LORA_STAGE2_AUTH_TOKEN`. api-service gửi `Authorization: Bearer <token>` mỗi request.

---

## 2. Model

- **Algorithm**: XGBoost regressor (`xgboost==2.x`)
- **Features (8)**: `lat, lon, sf, gw_lat, gw_lon, distance_km, log_distance_km, delta_alt_m`
  - `delta_alt_m = gw_altitude_m + gw_antenna_height_m`
  - `distance_km` = haversine (target, gateway)
- **Training data**: `ts.survey_training` table (PostGIS hypertable). Train+val = Nov–Dec 2025 random sample; test = Jan–Feb 2026 hold-out.
- **Hyperparams**: Optuna 100-trial search (xem `scripts/train_residual_model.py:OPTUNA_CONFIG`)
- **Artifact**: `data/stage2_xgb.joblib` (joblib pickle, ~3 MB)

### Performance (hold-out)

| Metric | v0.6.0 | Stage 1 only |
|---|---:|---:|
| RMSE (overall) | **10.59 dB** | 13.50 dB |
| MAE | 7.80 dB | — |
| Bias | +0.77 dB | −6.44 dB |
| RMSE 5–10 km | 4.2 dB | 25.1 dB |

Stage 2 chính yếu corrected long-range bias (Stage 1 P.1812 under-predicts ở > 5 km).

### Known limitations

- Hold-out chỉ bao 4/13 gateway outdoor. Indoor gw (a84041ffff1ee248) + 8 gw khác chưa được validate.
- Grid cells xa walk-survey path bị extrapolate — residual mean ~−5 dB → map có thể hiển thị weak hơn thực tế. Xem `core-logic/CLAUDE.md` § feedback cho clip option.
- Stage 1 P.1812 + DSM tạo diffraction overshoot ở 250m–2km — đây là vấn đề Stage 1, không phải Stage 2.

---

## 3. Local development

```bash
cd services/ml-service
uv sync
LORA_STAGE2_AUTH_TOKEN=dev-token \
  uv run uvicorn lora_ml_predict.app:app --reload --port 8001
```

Smoke test:
```bash
curl -s http://localhost:8001/healthz
# {"status":"ok","model_version":"stage2-xgb-v0.6.0"}

curl -s -X POST http://localhost:8001/residual \
  -H "Authorization: Bearer dev-token" \
  -H "content-type: application/json" \
  -d '{"target":{"lat":16.05,"lon":108.21,"sf":10},
       "serving_gateway":{"lat":16.0548,"lon":108.2199,
                          "altitude_m":0,"antenna_height_m":15,"frequency_mhz":923}}'
```

---

## 4. Re-train

```bash
# Train từ DB hiện tại (Nov–Dec 2025 train, Jan–Feb 2026 holdout)
uv run python scripts/train_residual_model.py \
  --output services/ml-service/data/stage2_xgb.joblib \
  --optuna-trials 100

# Eval offline trước khi deploy
uv run python scripts/experiments/eval_stage1_vs_stage2_2026_05_31.py
```

Sau khi swap artifact: rebuild image (ml-service không mount source volume — code COPY at build):
```bash
docker compose up -d --build ml-service
```

Đừng quên bump `MODEL_VERSION` constant trong `src/lora_ml_predict/app.py` — nó là string hardcode (xem memory `project_ml_service_label_baked.md`).

---

## 5. Wiring vào api-service

Trong `.env`:
```
STAGE2_PREDICT_BASE_URL=http://ml-service:8001
LORA_STAGE2_AUTH_TOKEN=<shared-token>
STAGE2_TIMEOUT_SECONDS=0.5
```

Rebuild api-service (cũng không có source volume):
```bash
docker compose up -d --build api-service
```

api-service tự gọi `/residual` cho từng request `/api/v1/coverage/predict`. Timeout/500/503 → graceful fallback Stage 1 only (response vẫn 200, chỉ `model_version` không có phần stage2).

---

## 6. File layout

```
services/ml-service/
  Dockerfile                         # Multi-stage Python 3.12 + xgboost wheel
  pyproject.toml                     # Package name: lora-ml-predict
  src/lora_ml_predict/
    app.py                           # FastAPI app + model loading + endpoints
  data/
    stage2_xgb.joblib                # Active model artifact
  reference_wireless/                # Legacy reference (XGBoost direct-RSSI), không wire
```

---

## 7. Production checklist

- [x] Bearer auth required on prediction endpoints
- [x] OOD guard rejects out-of-Vietnam coordinates
- [x] Stateless (no DB connection) — model loaded once at boot
- [x] Health endpoint returns model version cho monitoring
- [ ] Prometheus metrics endpoint (deferred)
- [ ] Model registry → R2 (currently filesystem only)
- [ ] A/B test framework (deferred)
