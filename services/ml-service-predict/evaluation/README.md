# Đánh giá Stage 2

Sinh 5 biểu đồ bắt buộc đánh giá mô hình hồi quy LightGBM Stage 2. **Offline / build-time** —
không chạy trong runtime serving.

## Setup

```bash
cd services/ml-service-predict
uv sync --extra eval    # cài matplotlib + shap
```

## Chạy

```bash
uv run python -m evaluation.generate_report --version stage2-20260513T131351Z

# Bỏ qua group training (cần retrain ~30s)
uv run python -m evaluation.generate_report --version stage2-20260513T131351Z --skip training
```

Output: `evaluation/reports/<model_version>/` chứa 5 PNG + `summary.txt`.

## 5 biểu đồ sinh ra

| # | File | Mục đích |
|---|---|---|
| 01 | `scatter_rssi.png` | RSSI dự đoán vs thực tế — RMSE/MAE/bias đọc trên biểu đồ |
| 02 | `residual_plot.png` | Sai số vs RSSI dự đoán — phát hiện bias theo dải |
| 03 | `cv_per_fold.png` | RMSE từng spatial fold — kiểm tra khả năng tổng quát không gian |
| 04 | `boosting_curve.png` | RMSE train/val vs iteration — kiểm overfit, early-stop |
| 05 | `shap_summary.png` | SHAP beeswarm — feature nào điều khiển hiệu chỉnh, theo hướng nào |

Đây là bộ tối thiểu đủ để defense + audit. Nếu cần thêm CM/ROC/PR/learning curve
cho báo cáo chính thức sau này, có thể khôi phục từ git history (commit trước).

## Lưu ý

- **Re-fetch dataset**: `data_loader` chạy lại `training.data.collect()` (~30s với
  DEM raycast). Nếu DB có survey mới sau ngày train, `dataset_hash` sẽ mismatch
  — log cảnh báo, eval vẫn chạy nhưng số liệu khác meta.json.
- **Boosting curve = 1 lần retrain**: tốn ~30s. Dùng `--skip training` nếu chỉ cần
  regression + SHAP.
