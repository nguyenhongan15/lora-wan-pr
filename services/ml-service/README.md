# ml-service

ML inference service cho LoRa coverage prediction (Stage 1 → 4).

> **Trạng thái (v2)**: SKELETON — file/folder dựng đúng spec §3.5 nhưng chưa
> implement. Không build/run được. Stage 1 thực tế hiện sống ở `api-service/`
> (pure math, không cần ONNX). Khi Stage 2+ ra đời, sẽ migrate sang đây và
> api-service gọi qua HTTP/gRPC nội bộ.

## Mục đích (theo system-architecture.md §3.5)

- Phục vụ inference cho Stage 1/2/3/4 (mỗi region đang ở stage nào).
- Auto-fallback khi stage cao hơn không khả dụng (model không load được).
- Luôn trả `Prediction` kèm `Confidence` đầy đủ.

## Tại sao tách khỏi `api-service`

- ResNet-18 + LightGBM có thể chiếm vài GB RAM.
- Có thể cần GPU (Stage 3+).
- Restart độc lập để swap model version mà không drop API traffic.

## Communication

Internal HTTP (FastAPI) hoặc gRPC. KHÔNG expose ra public Internet.
`api-service` gọi qua endpoint nội bộ `/predict` với param `lat/lng/sf`.

## Layout

```
services/ml-service/
├── Dockerfile                    # placeholder
├── pyproject.toml                # placeholder
├── src/lora_coverage_ml/
│   ├── api.py                    # FastAPI /predict endpoint (skeleton)
│   ├── router.py                 # stage selection + auto-fallback (skeleton)
│   ├── stages/
│   │   ├── stage1_empirical.py   # log-distance, NumPy (sẽ port từ api-service)
│   │   ├── stage2_lightgbm.py    # LightGBM residual
│   │   ├── stage3_cnn.py         # ResNet-18 ONNX
│   │   └── stage4_bayesian.py    # Ensemble / MC-dropout
│   ├── pipeline/
│   │   ├── tabular_features.py   # Stage 2
│   │   └── raster_features.py    # Stage 3, 4
│   └── calibration/
│       └── ece_monitor.py        # Cảnh báo khi ECE > 0.08
├── data/dem/                     # SRTM v3 tiles (gitignored, ~100MB)
├── models/                       # Cached ONNX artifacts (R2-backed)
└── tests/
```

## Khi nào start build

Khi có ≥ 5000 survey điểm thật cho ít nhất 1 region:
1. Train Stage 2 LightGBM offline trên data đã promote vào `ts.survey_training`.
2. Export ONNX qua `onnxmltools`.
3. Drop artifact vào `models/` (hoặc R2 prefix `lora-models-prod/stage=2/region=danang/calib=v1/`).
4. Bật endpoint `/predict` ở đây, switch traffic từ Stage 1 (api-service) sang.
