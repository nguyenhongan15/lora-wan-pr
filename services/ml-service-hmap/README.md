# ml-service-hmap

Map-ML service — phục vụ **heatmap rendering** cho tab "Bản đồ phủ sóng" (`/map`).

> **Trạng thái (2026-05-13)**: SKELETON. Service chưa build, chưa runnable. Chỉ là folder placeholder cho contributor tương lai. Heatmap hiện tại được render thuần client-side qua MapLibre GL từ Stage 1 RSSI grid (xem `apps/web-app`).

## Phạm vi

Phục vụ `/map` heatmap — model tối ưu cho **whole-bbox grid prediction** (10k-100k điểm/render), khác với `ml-service-predict` (point query, ms-level/query).

**KHÔNG** phục vụ `/coverage/predict` hoặc `/coverage/batch` — đó là phạm vi `ml-service-predict` (xem `u-work/ml-plan/plan-v1.md` §0 + §20).

## Tại sao tách khỏi `ml-service-predict`

Plan-v1 §20 quyết định 2 model riêng vì:

- **Inference budget khác biệt**: Predict cần ms-level latency, Map cần throughput cao (batch 10k+) chấp nhận seconds.
- **Feature engineering khác**: Map có thể dùng raster CNN/spatial smoothing, Predict dùng tabular GBM.
- **Owner riêng**: 2 model, 2 release cadence, 2 metric set. Tránh coupling cứng.
- **Container/RAM riêng**: Map model có thể là ResNet/UNet (vài GB GPU), không kéo vào pod predict.

## Shared với `ml-service-predict`

| Shared | Không shared |
|---|---|
| `Stage1Physics` (ở `api-service/.../path_loss.py`) | Architecture (CNN/raster vs GBM/tabular) |
| `ModelRegistry` (DB + R2, namespace `domain='map'` vs `domain='predict'`) | Container, Dockerfile, dependency |
| Schema `ml.model_runs`, `ml.active_models` | Endpoint (Map serve qua tile server hoặc pre-render) |
| Bảng `ts.survey_training` (read-only) | R2 prefix (`models/map/*`) |

## Layout (placeholder hiện tại)

```
services/ml-service-hmap/
├── Dockerfile                       # placeholder
├── pyproject.toml                   # placeholder
├── data/dem/                        # SRTM v3 tiles (gitignored, ~100MB)
├── models/                          # Cached artifacts (R2-backed, gitignored)
└── src/lora_coverage_ml/
    ├── api.py                       # FastAPI /map skeleton
    ├── router.py                    # stage selection + fallback (skeleton)
    ├── stages/                      # Skeleton — chưa implement
    ├── pipeline/                    # Tabular + raster feature skeleton
    └── calibration/                 # ECE monitor skeleton
```

Code skeleton trong `src/` thừa hưởng từ phase đầu khi Predict + Map chung 1 service; **sẽ được refactor** khi contributor cho Map-ML bắt đầu — không phải boilerplate đúng cho Map workload.

## Khi nào start build

Theo plan-v1: bắt đầu khi có rõ requirement Map-ML (bbox VN-wide vs region-specific, refresh cadence, tile zoom levels). Hiện chưa đủ data để fit model bbox lớn — đợi survey coverage rộng hơn.

## DEM tiles

`data/dem/*.hgt` — NASA SRTM v3 tiles, gitignored. Tải qua [USGS EarthExplorer](https://earthexplorer.usgs.gov/) hoặc [JonathanDeWit/elevation](https://github.com/bopen/elevation). Không dùng chung với `ml-service-predict` vì 2 service deploy độc lập (mỗi pod tự mount).

## Plan đầy đủ

- `u-work/ml-plan/plan-v1.md` §20 — boundary contract giữa Predict-ML và Map-ML.
