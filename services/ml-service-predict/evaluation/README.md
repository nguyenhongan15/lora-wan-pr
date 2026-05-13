# Stage 2 Evaluation

Sinh 5 biểu đồ must-have đánh giá Stage 2 LightGBM regression. **Offline / build-time** —
không chạy trong serving runtime.

## Setup

```bash
cd services/ml-service-predict
uv sync --extra eval    # cài matplotlib + shap
```

## Chạy

```bash
uv run python -m evaluation.generate_report --version stage2-20260513T131351Z

# Bỏ qua training group (cần retrain ~30s)
uv run python -m evaluation.generate_report --version stage2-20260513T131351Z --skip training
```

Output: `evaluation/reports/<model_version>/` chứa 5 PNG + `summary.txt`.

## 5 chart sinh ra

| # | File | Mục đích |
|---|---|---|
| 01 | `scatter_rssi.png` | Predicted vs actual RSSI — RMSE/MAE/bias đọc trên chart |
| 02 | `residual_plot.png` | Error vs predicted RSSI — phát hiện bias theo dải |
| 03 | `cv_per_fold.png` | RMSE từng spatial fold — kiểm tra spatial generalization |
| 04 | `boosting_curve.png` | Train/val RMSE vs iteration — overfit check, early-stop |
| 05 | `shap_summary.png` | SHAP beeswarm — feature nào drive correction, hướng nào |

Đây là bộ tối thiểu đủ để defense + audit. Nếu cần thêm CM/ROC/PR/learning curve
cho báo cáo formal sau, có thể restore từ git history (commit trước).

## Caveats

- **Re-fetch dataset**: `data_loader` chạy lại `training.data.collect()` (~30s với
  DEM raycast). Nếu DB có survey mới sau ngày train, `dataset_hash` sẽ mismatch
  — log warning, eval vẫn chạy nhưng số liệu khác meta.json.
- **Boosting curve = 1 retrain**: cần ~30s. Dùng `--skip training` nếu chỉ cần
  regression + SHAP.
