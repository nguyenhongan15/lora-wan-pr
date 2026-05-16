# ml-service-hmap

Service Map-ML — phục vụ **render heatmap** cho tab "Bản đồ phủ sóng" (`/map`).

> **Trạng thái (2026-05-13)**: SKELETON. Service chưa build, chưa chạy được. Chỉ là folder placeholder cho contributor tương lai. Heatmap hiện tại được render thuần phía client qua MapLibre GL từ lưới RSSI của Stage 1 (xem `apps/web-app`).

## Phạm vi

Phục vụ heatmap `/map` — model tối ưu cho **dự đoán lưới trên toàn bbox** (10k-100k điểm/render), khác với `ml-service-predict` (truy vấn điểm, ms-level/query).

**KHÔNG** phục vụ `/coverage/predict` hoặc `/coverage/batch` — đó là phạm vi của `ml-service-predict` (xem `u-work/ml-plan/plan-v1.md` §0 + §20).

## Tại sao tách khỏi `ml-service-predict`

Plan-v1 §20 quyết định 2 model riêng vì:

- **Ngân sách inference khác biệt**: Predict cần latency ms-level, Map cần throughput cao (batch 10k+) chấp nhận hàng giây.
- **Feature engineering khác**: Map có thể dùng raster CNN/làm mịn không gian, Predict dùng tabular GBM.
- **Owner riêng**: 2 model, 2 nhịp release, 2 bộ metric. Tránh coupling cứng.
- **Container/RAM riêng**: Map model có thể là ResNet/UNet (vài GB GPU), không kéo vào pod predict.

## Dùng chung với `ml-service-predict`

| Dùng chung | Không dùng chung |
|---|---|
| `Stage1Physics` (ở `api-service/.../path_loss.py`) | Kiến trúc (CNN/raster vs GBM/tabular) |
| `ModelRegistry` (DB + R2, namespace `domain='map'` vs `domain='predict'`) | Container, Dockerfile, dependency |
| Schema `ml.model_runs`, `ml.active_models` | Endpoint (Map phục vụ qua tile server hoặc pre-render) |
| Bảng `ts.survey_training` (chỉ đọc) | Prefix R2 (`models/map/*`) |

## Layout (placeholder hiện tại)

```
services/ml-service-hmap/
├── Dockerfile                       # placeholder
├── pyproject.toml                   # placeholder
├── data/dem/                        # Tile SRTM v3 (gitignored, ~100MB)
├── models/                          # Artifact cache (R2-backed, gitignored)
└── src/lora_coverage_ml/
    ├── api.py                       # Skeleton FastAPI /map
    ├── router.py                    # Lựa stage + fallback (skeleton)
    ├── stages/                      # Skeleton — chưa implement
    ├── pipeline/                    # Skeleton feature tabular + raster
    └── calibration/                 # Skeleton monitor ECE
```

Code skeleton trong `src/` thừa hưởng từ giai đoạn đầu khi Predict + Map chung 1 service; **sẽ được refactor** khi contributor cho Map-ML bắt đầu — không phải boilerplate đúng cho workload Map.

## Khi nào bắt đầu build

Theo plan-v1: bắt đầu khi có yêu cầu rõ ràng cho Map-ML (bbox toàn VN vs vùng cụ thể, nhịp refresh, mức zoom tile). Hiện chưa đủ data để fit model bbox lớn — đợi survey phủ rộng hơn.

## Tile DEM

`data/dem/*.hgt` — tile NASA SRTM v3, gitignored. Tải qua [USGS EarthExplorer](https://earthexplorer.usgs.gov/) hoặc [JonathanDeWit/elevation](https://github.com/bopen/elevation). Không dùng chung với `ml-service-predict` vì 2 service deploy độc lập (mỗi pod tự mount).

## Plan đầy đủ

- `u-work/ml-plan/plan-v1.md` §20 — hợp đồng ranh giới giữa Predict-ML và Map-ML.
