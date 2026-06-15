# Kết quả đạt được và chưa đạt được

Tài liệu báo cáo trạng thái dự án tính tới **16/06/2026**. Số liệu định lượng tham khảo `docs/MO_TA_DU_AN.md` §5.2.

## 1. Kết quả đạt được

### 1.1. Mô hình dự đoán

- ✅ **Stage 1 vật lý ITU-R P.1812-7** tích hợp đầy đủ qua thư viện `crc-covlib`:
  - Path loss P.1812 + clutter P.2108 + building entry loss P.2109.
  - Per-gateway noise floor hiệu chỉnh từ dữ liệu khảo sát.
  - Bidirectional link budget (uplink + downlink), per-direction RSSI/SNR/margin.
  - Detection bottleneck: snr_low / sf_mismatch / path_loss / interference / tx_power_cap.
- ✅ **Stage 2 Extra Trees end-to-end** (21 features):
  - Test RMSE **7.10 dB** trên temporal hold-out Jan–Feb 2026 (n=337, 4 gateway).
  - Hơn baseline XGBoost cũ −3.48 dB RMSE.
  - Hot-reload artifact sau retrain, không cần restart container.
- ✅ **Ba đầu ra phủ sóng:**
  - Dự đoán điểm (`/coverage/predict`) — Stage 1 + Stage 2.
  - Bản đồ ước lượng RSSI composite (P.1812 + DTM + per-gw NF + survey overlay).
  - Bản đồ SF tối thiểu (P.1812 + DSM + bias từ khảo sát).

### 1.2. Backend

- ✅ **Kiến trúc 5 tầng Clean Architecture**, enforce bằng `import-linter` trong CI.
- ✅ **31 migration Alembic** — schema đầy đủ cho geo / ts / auth / ml / ops.
- ✅ **REST API** OpenAPI 3.1, error format RFC 7807, versioning `/api/v1/...`.
- ✅ **Authentication v2:**
  - JWT access (15 phút) + refresh opaque HttpOnly cookie (30 ngày, rotate on use).
  - Bcrypt password, rate-limit Valkey-backed, account lockout (5 fail → 30 phút).
  - Reset password + email verify qua SMTP.
- ✅ **Quản lý gateway & khảo sát:**
  - Linked source (LPWANMapper / ChirpStack) mutual-exclusive, sync 20s.
  - Upload CSV/JSON với alias header linh hoạt.
  - Quarantine workflow: dữ liệu mới → admin duyệt → training table.
  - Gateway quarantine: gateway lạ → admin tạo trước khi link.

### 1.3. Background jobs

- ✅ **Celery + Valkey** broker với concurrency=1 cho task heavy.
- ✅ **Retrain ML pipeline:** admin trigger → build CSV từ `ts.survey_training` + DEM/landuse → train Extra Trees → atomic swap artifact → hot reload ml-service.
- ✅ **Rebuild heatmap incremental:** skip khi không có packet mới; full rebuild khi ≥1 gateway có data mới; reset cờ chính xác sau approve/delete batch.
- ✅ **Theo dõi trực tiếp (real-time):** ChirpStack webhook + SSE fan-out tới web client; sync 20s + idle 15 phút + dedup `(ts, device, gw)`.

### 1.4. Frontend

- ✅ **React 19 + Vite + JSDoc** (không TypeScript), check qua `tsc --checkJs --noEmit`.
- ✅ **MapLibre GL** với 3 chế độ bản đồ (points / heatmap / estimate).
- ✅ **Dự đoán điểm** chi tiết: link budget UL+DL, SF khuyến nghị, PDR/BER/FER, bottleneck cause.
- ✅ **Admin panel:** duyệt batch khảo sát, duyệt gateway quarantine, trigger rebuild + retrain.
- ✅ **Panel khảo sát thời gian thực:** SSE stream, picker linked source, status "không hoạt động" / "có độ trễ".

### 1.5. DevOps & hạ tầng

- ✅ **Docker Compose** 6 service, network bridge, log rotation 50MB × 5.
- ✅ **CI/CD GitHub Actions** 3 job song song: api-service (lint + mypy + import-linter + Alembic + pytest), docker-build smoke, web-app (ESLint + JSDoc + Vite build).
- ✅ **Cloudflare R2** sẵn sàng cho artifact (chưa kích hoạt prod).
- ✅ **Cloudflare tunnel** cho demo public.
- ✅ **Postgres tuning** sẵn cho VPS 8GB (Hetzner CPX31 baseline).

### 1.6. Dữ liệu

- ✅ **~10.000 điểm khảo sát Đà Nẵng** (11 gateway DNIIT) + ~2.000 điểm Hải Phòng (2 gateway pilot).
- ✅ **DEM/DSM gap-fill:** Copernicus 30m + ESA WorldCover land cover + Google Buildings + Microsoft Buildings.
- ✅ **Tách tập rõ ràng:** train+val = Nov–Dec 2025 random; test = Jan–Feb 2026 temporal hold-out.

## 2. Kết quả chưa đạt được & hạn chế

### 2.1. Mô hình ML

- ❌ **Benchmark thuật toán hẹp:** chỉ so sánh Extra Trees vs XGBoost cùng 21 features. Chưa test RandomForest / LightGBM / CatBoost / Ridge baseline → không có căn cứ định lượng đầy đủ cho lựa chọn ET.
- ❌ **Bias +2.61 dB trên temporal hold-out** (over-predict RSSI ~2.6 dB), tập trung ở khoảng cách <2km (+3.87 dB) — chưa fix; từng thử hardcode -4.67 dB rồi revert vì overfit-to-holdout.
- ❌ **Tập kiểm chứng hẹp:** temporal hold-out chỉ bao 4/13 gateway Đà Nẵng outdoor. Indoor gateway + 9 gateway còn lại chưa được validate.
- ❌ **Cross-region chưa eval:** Hải Phòng chỉ 2 gateway pilot, chưa chạy `--bbox haiphong` để kiểm tra generalization.
- ❌ **Stage 2 ML cho heatmap bị drop** (từ 2026-06-09) vì không ổn định ở vùng thưa dữ liệu → heatmap hiện thuần vật lý + overlay khảo sát.







### 2.5. Bug đã biết, chờ quyết định product

- ❌ **Bug D — shadowed quarantine never-promote** (`project_bug_d_shadowed_quarantine_2026_06_05.md`): quarantine row của contributor A bị shadow bởi training row của B sẽ kẹt vĩnh viễn vì SQL promotion dùng `NOT EXISTS` không match contributor.



