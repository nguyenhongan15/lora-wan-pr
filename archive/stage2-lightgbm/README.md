# archive/stage2-lightgbm

**Đây là code Stage 2 LightGBM tôi tự build trước handoff cho dev ML mới — giữ làm reference cá nhân để rút kinh nghiệm, KHÔNG còn deploy.**

Hệ thống hiện tại (`services/api-service` + `services/ml-service`) không phụ thuộc folder này. api-service chạy Stage1-only (`STAGE2_PREDICT_BASE_URL` rỗng). Khi dev ML mới deploy model của họ, họ sẽ tự dựng lại service từ đầu trong `services/ml-service/`.

---

## Tóm tắt model

| | |
|---|---|
| Kiến trúc | Stage 1 ITU-R P.1812 + Stage 2 LightGBM residual |
| Output | `residual_db` per (target, serving_gateway) |
| Best run | `artifacts/stage2/stage2-20260517T093146Z` |
| Test set | Jan–Feb 2026 hold-out (Đà Nẵng) |
| Test RMSE | **6.41 dB** (cải thiện Stage 1 40–69 % qua các bucket distance) |
| Stage 1 baseline | bias +11.65 dB, RMSE 7–14 dB |
| Training scope | Đà Nẵng only, 11 gateways |
| Optuna | TPE sampler, 100 trial budget |
| Spatial CV | KMeans K=5 |

## Layout

```
archive/stage2-lightgbm/
  README.md                 ← this file
  pyproject.toml            ← project name `lora-ml-predict` (KHÔNG còn là uv workspace member)
  Dockerfile                ← multi-stage uv + libcrc-covlib build (legacy, không deploy)
  src/lora_ml_predict/      ← package source
    config.py, features/, stages/, registry/, serving/, training/
  evaluation/               ← offline plots & diagnostics
  scripts/
    train_stage2.py         ← Optuna sweep
    eval_stage2_holdout.py  ← test-set scorecard
    retrain_and_report.py   ← one-shot retrain + report (đã rebase path về archive/)
    build_urbanization_grid.py
  artifacts/stage2/
    stage2-20260517T093146Z/   ← booster + meta + active.json (3.3 MB total, commit luôn)
```

## Bài học rút ra

- Stage 1 ITU-R P.1812 với DEM Copernicus GLO-30 có bias systematic +11.65 dB ở Đà Nẵng → ML có signal để recover. Residual ~10 features (distance, frequency, urbanization, slope, terrain mean/std/min/max) đủ để hạ RMSE từ 7–14 dB xuống 6.41 dB.
- crc-covlib không có wheel Linux trên PyPI — phải vendor wheel (Windows .dll) + build `libcrc-covlib.so` từ source trong runtime container. Pattern này hữu dụng nếu dev mới cũng cần Stage 1 ở runtime.
- Spatial CV (KMeans K=5) quan trọng vì measurement points clustered theo route khảo sát; random CV leak gateway/area giữa train↔val.
- Optuna TPE 100 trial đủ cho LightGBM (~10 feature, ~10k row). Trial > 100 không cải thiện meaningful.
- OOD detector dạng đơn giản (range check trên distance + frequency) đủ cho mục đích safe-fallback về Stage 1.

## Trạng thái runnable

Không guarantee. Code đã được rebase path đơn giản (`config.py` artifact_dir, `scripts/retrain_and_report.py` path constants) nhưng các file khác trong `evaluation/`, `scripts/build_urbanization_grid.py`, `Dockerfile`, etc. vẫn còn string `services/ml-service` / `services/ml-service-predict` legacy. Muốn chạy lại:

1. `pyproject.toml` đã có workspace dep `lora-coverage-api` (Stage 1 sharing) — cần đổi thành PyPI dep hoặc add lại vào workspace tạm thời.
2. `vendor/crc_covlib-4.6.2-py3-none-any.whl` path trong `tool.uv.sources` là `../../vendor/...` (giả định archive/stage2-lightgbm/ là 2 levels deep từ repo root — đúng).
3. Grep `services/ml-service` trong folder này và update từng file nếu cần.

Khuyến cáo: nếu muốn rerun benchmark, copy folder ra ngoài workspace và setup fresh thay vì wire ngược vào.
