# Đánh giá Mô hình Học máy (Stage 2 — Extra Trees)

Tài liệu đánh giá mô hình học máy dự đoán RSSI tại endpoint `/api/v1/coverage/predict`. Trạng thái tham chiếu: retrain mới nhất `65a95732-88d8-45a1-96b2-b23270fef969` ngày **15/06/2026 23:52 UTC** (`reports/retrain-65a95732-.../`).

## 1. Mô tả mô hình

### 1.1. Mục đích

Mô hình học máy đảm nhiệm vai trò **Stage 2** trong pipeline hai tầng dự đoán RSSI:

- **Stage 1** (vật lý ITU-R P.1812): tính path loss + clutter + entry loss → RSSI thô.
- **Stage 2** (Extra Trees end-to-end): dự đoán trực tiếp RSSI từ đặc trưng hình học + địa hình + RF parameters, KHÔNG dùng Stage 1 làm input.

Khác với bản đồ ước lượng (đã drop ML từ 09/06/2026), Stage 2 ML chỉ phục vụ `/predict` — endpoint trả lời câu hỏi "tại điểm cụ thể này, RSSI/SNR dự kiến là bao nhiêu?".

### 1.2. Thuật toán & cấu hình

| Tham số                   | Giá trị                                                          |
| ------------------------- | ---------------------------------------------------------------- |
| Thuật toán                | `ExtraTreesRegressor` (scikit-learn)                             |
| Số cây                    | 1.500                                                            |
| `max_depth`               | 20                                                               |
| `min_samples_split`       | 5                                                                |
| `min_samples_leaf`        | 2                                                                |
| Pipeline                  | ColumnTransformer (median + StandardScaler / OHE) → ExtraTrees   |
| Số đặc trưng              | 21 (20 numeric + `gateway` one-hot)                              |
| Model version             | `stage2-et-v0.7.0`                                               |
| OOD guardrail             | lat 8.4–23.4, lon 102.1–109.5, SF 7–12, freq 921.4–924.8 MHz     |

### 1.3. Bộ đặc trưng (21 features)

**Tham số RF (2):** `frequency`, `spreading_factor`.

**Hình học link (5):** `log_distance`, `log_distance_3d`, `delta_lat`, `delta_lon`, `angle`.

**Cao độ & độ dốc (4):** `gw_elevation`, `delta_elevation`, `elevation_angle`, `slope`.

**Địa hình & nhám (5):** `roughness`, `terrain_mean`, `terrain_std`, `terrain_min`, `terrain_max`.

**Fresnel zone (3):** `fresnel_obstruction_ratio`, `min_fresnel_clearance`, `mean_fresnel_clearance`.

**Land cover (1):** `residential_ratio`.

**Categorical (1):** `gateway` one-hot encoding.

### 1.4. Tập dữ liệu

- **Train + Validation:** Nov–Dec 2025, n=11.842, random split stratified-by-gateway.
- **Holdout temporal:** Jan–Feb 2026, n=337, bbox Đà Nẵng, 4/13 gateway outdoor.
- **Pipeline tự động:** retrain trigger từ admin → `build_training_csv.py` rebuild từ `ts.survey_training` + DEM/landuse central VN → train → atomic swap → hot-reload ml-service (không restart container).

## 2. Kết quả đạt được

### 2.1. Số liệu retrain mới nhất (15/06/2026)

#### Training in-sample
| Chỉ tiêu       | Giá trị         |
| -------------- | --------------- |
| n              | 11.842          |
| RMSE           | **2.55 dB**     |
| MAE            | 1.58 dB         |
| Bias           | ≈ 0 (1.3e-14)   |
| R²             | 0.943           |

#### Holdout temporal Jan–Feb 2026 (Đà Nẵng)
| Chỉ tiêu       | Giá trị         |
| -------------- | --------------- |
| n              | 337             |
| RMSE           | **3.08 dB**     |
| MAE            | 2.24 dB         |
| Bias           | +0.42 dB        |
| R²             | 0.975           |

**Trạng thái:** `KHONG_DAT` — sai lệch 0.08 dB so với target 3.0 dB. Δ RMSE vs lần retrain trước: **−4.02 dB** (cải thiện rất lớn sau khi fix CSV gap ngày 14/06/2026).

### 2.2. Phân tích theo khoảng cách

| Khoảng cách | n     | RMSE (dB)  | MAE  | Bias    | R²    |
| ----------- | ----- | ---------- | ---- | ------- | ----- |
| 0 – 2 km    | 244   | 3.40       | 2.53 | +0.50   | 0.969 |
| 2 – 5 km    | 45    | 2.31       | 1.77 | +0.13   | 0.787 |
| 5 – 10 km   | 48    | **1.68**   | 1.17 | +0.31   | 0.749 |

Bias dương nhỏ và đồng đều (+0.13 → +0.50 dB) trên cả 3 cohort. Không còn pattern over-prediction trầm trọng ở <2km như các retrain trước (+3.87 dB → +0.50 dB sau fix CSV).

### 2.3. Phân tích theo gateway (holdout)

| Gateway                   | Loại    | n   | RMSE | Bias    | R²    |
| ------------------------- | ------- | --- | ---- | ------- | ----- |
| Dragino C2.209            | outdoor | 222 | 3.34 | +0.65   | 0.965 |
| DF_GW_2_NongSon           | outdoor | 60  | 2.23 | −0.08   | 0.805 |
| Dragino indoor 01         | indoor  | 47  | 1.69 | +0.33   | 0.274 |
| DF_Binh Thuan             | outdoor | 8   | 5.85 | −1.52   | 0.583 |

### 2.4. So sánh với baseline

- **Hơn XGBoost (v0.6) −3.48 dB RMSE** trên cùng tập hold-out (số được lưu trong memory dự án).
- **Hơn lần retrain liền trước −4.02 dB RMSE** (cải thiện CSV gap pipeline).

## 3. Ưu điểm

### 3.1. Độ chính xác cạnh tranh quốc tế

- RMSE 3.08 dB temporal hold-out **rất gần** target 3.0 dB DATN tự đặt — chỉ chênh 0.08 dB.
- R² = 0.975 trên holdout → mô hình giải thích được 97,5 % phương sai RSSI ở vùng đã đo. Trong khoa học LoRa propagation, R² > 0.95 là mức tốt.
- Hiệu năng vượt baseline log-distance + XGBoost cũ −3.48 dB → đủ căn cứ định lượng để chọn Extra Trees làm production model.

### 3.2. Pipeline retrain tự động

- **Atomic swap artifact:** model mới được test, validate metrics trước khi swap; rollback đơn giản nếu fail.
- **Hot-reload** ml-service: không cần restart container, downtime ~0.
- **Build CSV từ database:** retrain từ raw `ts.survey_training` đảm bảo dữ liệu mới nhất luôn được học.
- **Holdout eval tự động** lưu vào `reports/retrain-<uuid>/holdout_eval.json` cho audit.

### 3.3. Bias hệ thống thấp

- Bias overall +0.42 dB — chấp nhận được cho propagation modeling (so với bias +2.61 dB của retrain trước fix CSV gap).
- Bias từng cohort đồng nhất, không có distance-dependent drift trầm trọng → mô hình học được pattern path loss vật lý.

### 3.4. Reproducibility

- Mỗi retrain sinh artifact đầy đủ: `summary.json`, `holdout_eval.json`, `summary.html`, `report.pdf` + assets feature importance plots.
- Model version baked vào image (`stage2-et-v0.7.0`), trả về trong API response field `model_version` → traceability per request.

### 3.5. OOD guardrail

- Constraint VN bbox + AS923-2 frequency + SF 7–12 ngay tại API layer → reject input vô lý trước khi forward vào model.
- Tránh hallucination khi user query toạ độ ngoài Việt Nam.

## 4. Nhược điểm & hạn chế

### 4.1. Chưa đạt target 3.0 dB

- RMSE 3.08 dB > target 0.08 dB → status `KHONG_DAT`. Mặc dù sát target, vẫn chưa qua mốc tự đặt.
- Để xuống dưới 3.0 dB cần: thêm data khảo sát đa dạng hơn, hoặc tinh chỉnh feature (clutter density, building height từ DSM).

### 4.2. Tập kiểm chứng hẹp

- **Chỉ 4/13 gateway** outdoor Đà Nẵng được hold-out: Dragino C2.209 (n=222), DF_NongSon (n=60), Dragino indoor 01 (n=47), DF_Binh Thuan (n=8).
- **DF_Binh Thuan chỉ n=8 mẫu** → RMSE 5.85 dB không đủ kết luận statistical significance (có thể là noise).
- **9 gateway còn lại không có holdout data** Jan–Feb 2026 → khoảng tin cậy mô hình cho các gateway này không thể đo.
- **Indoor gateway chỉ 1 trên 4** → indoor generalization không được validate đầy đủ.

### 4.3. Benchmark thuật toán hẹp

- Chỉ so sánh **Extra Trees vs XGBoost** cùng 21 features.
- **Chưa test:** RandomForest, LightGBM, CatBoost, Ridge baseline, Neural Network (MLP).
- Hậu quả: không có căn cứ định lượng "tại sao Extra Trees thắng" — chỉ có "tốt hơn 1 baseline cụ thể".
- Đây là **điểm yếu trong báo cáo DATN** mà hội đồng có thể hỏi.

### 4.4. Cross-region chưa được eval

- Mô hình train trên data **Đà Nẵng only** (đã được lock trong project memory ngày 14/05/2026).
- Hải Phòng có ~2.000 điểm khảo sát + 2 gateway pilot nhưng **không có trong holdout** → không đo được khả năng generalize ra region khác.
- Khi user query toạ độ Hải Phòng, prediction sẽ chạy nhưng độ tin cậy chưa biết.

### 4.5. Bias correction từng thử + revert

- Ngày 14/06/2026 từng hardcode `-4.67 dB` bias correction ở serving layer (giảm RSSI predicted xuống 4.67 dB).
- Đã **revert** vì overfit-to-holdout: che lấp organic improvement qua retrain pipeline.
- Hệ quả: bias +0.42 dB hiện tại là "thật", không có shortcut.

### 4.6. R² thấp ở cohort xa & indoor

- 2–5km R² = 0.787, 5–10km R² = 0.749 — thấp hơn overall 0.975.
- Indoor gateway Dragino indoor 01: R² = 0.274 mặc dù RMSE 1.69 dB tốt → biến thiên target nhỏ ở indoor (variance ~3 dB) khiến R² không phản ánh chất lượng thật.
- Cần báo cáo cả RMSE + variance khi nói về chất lượng cohort.

### 4.7. Overfit gap nhỏ nhưng tồn tại

- Training RMSE 2.55 dB vs Holdout RMSE 3.08 dB → gap = 0.53 dB.
- Trong Extra Trees với 1500 cây và max_depth=20 (deep), gap này chấp nhận được nhưng cho thấy mô hình có học một phần noise.
- Có thể giảm `max_depth` hoặc tăng `min_samples_leaf` để regularize, nhưng cần Optuna search lại để không hi sinh hold-out performance.

### 4.8. Feature engineering chưa hoàn thiện

- **20 numeric features** hiện tại là kết quả selection thủ công, chưa qua ablation đầy đủ.
- **Thiếu features có thể quan trọng:**
  - Clutter density (số toà nhà / canopy trong Fresnel zone)
  - Time of day / season (LoRa có thể bị ảnh hưởng bởi nhiệt độ)
  - Antenna height & gain explicit
  - Tx power per packet
- Đây là cơ hội cải tiến hậu DATN.

### 4.9. API vs offline gap (cảnh báo historical)

- Memory ghi nhận ngày 31/05/2026 (v0.6): endpoint `/coverage/predict` cho bias +4.55 RMSE 13.47 dB so với offline script bias −0.25 RMSE 10.58 dB trên cùng holdout.
- Nguyên nhân: wiring drift serve-side (data preparation khác offline).
- **Chưa verify lại trên v0.7.0** sau retrain mới — cần re-eval API vs offline cho version hiện tại trước defense.

### 4.10. Stage 2 bị drop khỏi heatmap

- Từ 09/06/2026, ML Stage 2 **không còn dùng** cho bản đồ ước lượng RSSI (chỉ dùng cho /predict).
- Lý do: instability ở vùng thưa khảo sát (extrapolation hallucination).
- Hệ quả: tính năng quan trọng nhất của ML (visualization toàn bản đồ) phải dùng vật lý thuần → ML chỉ phục vụ point query, hẹp hơn scope ban đầu.

## 5. Đánh giá tổng quan

### 5.1. Trạng thái chất lượng

| Tiêu chí                              | Mức         | Ghi chú                                                         |
| ------------------------------------- | ----------- | --------------------------------------------------------------- |
| Độ chính xác (RMSE)                   | **Khá tốt** | 3.08 dB, sát target 3.0 dB (chỉ chênh 0.08)                     |
| Bias hệ thống                         | **Tốt**     | +0.42 dB overall, đồng đều theo cohort                          |
| Generalization theo gateway           | Trung bình  | Chỉ 4/13 gateway có holdout, indoor + rural chưa validate đủ    |
| Generalization theo region            | **Yếu**     | Train Đà Nẵng only, Hải Phòng chưa eval                         |
| Benchmark so với baseline             | **Yếu**     | Chỉ so 1 baseline (XGBoost), thiếu RF/LGB/CatBoost              |
| Tính tái lập                          | **Tốt**     | Pipeline retrain tự động, artifact đầy đủ                       |
| Tính ổn định (no hallucination)       | Trung bình  | Đã drop khỏi heatmap vì instability vùng thưa                   |
| Phù hợp DATN defense                  | **Tốt**     | Đủ độ sâu để bảo vệ, miễn trình bày trung thực hạn chế          |

### 5.2. Phù hợp use case nào

- ✅ Dự đoán RSSI cho **điểm cụ thể trong vùng đã khảo sát** Đà Nẵng — độ tin cậy cao (R² 0.975).
- ✅ So sánh chất lượng giữa các vị trí trong cùng cụm gateway.
- ⚠️ Dự đoán cho gateway **chưa có holdout data** → cần margin an toàn ±5 dB.
- ❌ KHÔNG dùng cho **operator-grade SLA** (chưa đạt RMSE < 2 dB của các tool thương mại).
- ❌ KHÔNG dùng cho **vùng ngoài Đà Nẵng** (chưa eval generalization).
- ❌ KHÔNG dùng cho **bản đồ phủ sóng toàn vùng** (đã drop, dùng vật lý thay thế).

## 6. Hướng cải tiến

### 6.1. Ngắn hạn (trước defense)

1. **Re-eval API vs offline gap** trên v0.7.0 — nếu vẫn có drift, fix wiring trước defense.
2. **Bổ sung baseline benchmark:** chạy RandomForest + LightGBM trên cùng 21 features, cùng holdout → bảng so sánh 3 model cho báo cáo.
3. **Eval Hải Phòng** dù chỉ 2 gateway pilot — báo cáo cross-region generalization gap để trung thực.
4. **Feature importance plot** từ Extra Trees → biện luận lựa chọn 21 features.

### 6.2. Trung hạn

1. **Mở rộng holdout** sang 9 gateway còn lại sau đủ Jan–Feb 2026 data → RMSE per-gw có ý nghĩa thống kê.
2. **Feature engineering thêm:** clutter density (count buildings trong Fresnel), antenna height/gain explicit, tx power per packet.
3. **Optuna search lại** sau khi đã có baseline benchmark — regularize chống overfit gap 0.53 dB.
4. **Train Hải Phòng cohort riêng** khi có ≥ 5 gateway + ≥ 5.000 điểm.

### 6.3. Dài hạn

1. **Hybrid Stage 1 + Stage 2** cho heatmap: ML chỉ áp dụng vùng có ground-truth dày (kernel-weighted), thuần vật lý vùng thưa → kết hợp ưu điểm hai cách.
2. **Quantile regression** thay vì point estimate: trả về (P10, P50, P90) → user thấy uncertainty.
3. **Online learning** cho gateway mới: fine-tune trên data realtime sau khi gateway được approve.
4. **Multi-region generalization** sau khi có data 5+ tỉnh → mô hình quốc gia.

---

**Tài liệu tham chiếu:**
- `reports/retrain-65a95732-88d8-45a1-96b2-b23270fef969/holdout_eval.json` — eval mới nhất
- `reports/retrain-65a95732-88d8-45a1-96b2-b23270fef969/summary.json` — summary retrain
- `services/ml-service/README.md` — config production model
- `services/ml-service/src/lora_ml_predict/app.py` — feature list + OOD guardrail
- `services/ml-service/data/train_metrics.json` — metrics in-sample lần training
- `docs/ENG_MIGRATION_EXTRA_TREES.md` / `docs/FR_MIGRATION_EXTRA_TREES.md` — lịch sử migration sang Extra Trees
- `docs/KET_QUA_DAT_DUOC.md` §1.1, §2.1 — kết quả tổng thể & hạn chế ML
