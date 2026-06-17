# Mô tả dự án — Hệ thống lập bản đồ phủ sóng LoRaWAN

## 1. Mục tiêu

Xây dựng nền tảng web ước lượng và hiển thị vùng phủ sóng LoRaWAN cho mạng AS923-2 tại Việt Nam (thực nghiệm tại Đà Nẵng), kết hợp **mô hình truyền sóng vật lý ITU-R P.1812** với **học máy Extra Trees**. Người dùng có thể:

- Dự đoán RSSI/SNR/PDR cho một điểm bất kỳ.
- Xem bản đồ phủ sóng ước lượng theo từng gateway (cổng kết nối).
- Đóng góp dữ liệu khảo sát thực địa (qua app LPWANMapper, chirpstack hoặc upload CSV/JSON).

## 2. Phạm vi

- **Khu vực:** Việt Nam, băng tần AS923-2 (921.4–924.8 MHz).
- **Trọng tâm:** Đà Nẵng (11 gateway DNIIT, ~10.000 điểm khảo sát).
- **Không thuộc phạm vi:** Multi-region, băng tần khác (US915/EU868), mobile native app.

## 3. Kiến trúc tổng quan

```
Người dùng
    │
    ▼
React Web App (MapLibre GL, Tailwind, TanStack Query)
    │
    ▼
FastAPI api-service ──► PostgreSQL 17 + PostGIS + TimescaleDB
    │                       (gateway, survey, ML registry)
    │
    ├─► Stage 1: ITU-R P.1812 + P.2108 (vật lý, thư viện crc-covlib)
    │
    └─► Stage 2 (tuỳ chọn): ml-service ──► Extra Trees end-to-end
                            (FastAPI riêng)

Celery worker + Valkey: retrain ML, rebuild bản đồ ước lượng nền.
ChirpStack webhook: nhập gói tin trực tiếp từ gateway.
```

Code chia 5 tầng (`edge → application → domain ← infrastructure`), tách bạch nhờ `import-linter` trong CI.

## 4. Các thành phần chính

| Thành phần | Vai trò | Công nghệ |
|---|---|---|
| `apps/web-app` | Giao diện bản đồ, dự đoán điểm, panel khảo sát thời gian thực, admin duyệt dữ liệu | React 19, Vite, MapLibre, Zod |
| `services/api-service` | REST API, xác thực JWT, link-budget Stage 1, điều phối Stage 2, quản lý gateway/khảo sát | FastAPI, SQLAlchemy, Alembic |
| `services/ml-service` | Inference Extra Trees, hot-reload artifact sau khi retrain | FastAPI, scikit-learn |
| Celery worker | Retrain mô hình, rebuild heatmap incremental, sync ChirpStack | Celery + Valkey |
| Cơ sở dữ liệu | Lưu gateway, survey (hypertable Timescale), ML registry, auth | PostgreSQL 17 + PostGIS + TimescaleDB |

## 5. Mô hình truyền sóng

### 5.1. Stage 1 — Vật lý ITU-R P.1812

- Tính path loss theo ITU-R P.1812-7 (terrain) + P.2108 (clutter) + P.2109 (building entry loss).
- Đầu vào: DEM/DSM, vùng khí hậu, độ cao anten, công suất, độ nhạy thu.
- Đầu ra: RSSI/SNR uplink + downlink, độ dư công suất, gateway phục vụ tốt nhất.
- Hiệu chỉnh: **per-gateway noise floor** từ dữ liệu khảo sát thực địa.

### 5.2. Stage 2 — Extra Trees (học máy)

- **Thuật toán:** ExtraTreesRegressor (1500 cây, max_depth=20).
- **Vai trò:** dự đoán RSSI **end-to-end** (không phải hiệu chỉnh phần dư). API contract giữ tên `residual_db = RSSI_ET − RSSI_Stage1` chỉ để cộng vào kết quả Stage 1 → giữ tính nhất quán SNR/margin.
- **Đặc trưng (21):** khoảng cách log, hình học 3D, độ cao và độ dốc địa hình DEM, thống kê terrain, độ che Fresnel, tỉ lệ vùng dân cư, tần số, SF, gateway one-hot.
- **Hiệu năng (số chính cho báo cáo — temporal hold-out Jan–Feb 2026 Đà Nẵng, n=337, 4 gateway):**

  | Chỉ số | Extra Trees | XGBoost v0.6 (baseline cũ) |
  |---|---:|---:|
  | RMSE | **7.10 dB** | 10.58 dB |
  | MAE | 4.98 dB | 7.80 dB |
  | Bias | +2.61 dB | +0.77 dB |
  | R² | 0.8671 | — |

  ET tốt hơn baseline XGBoost cũ **3.48 dB RMSE** trên cùng tập kiểm chứng.

- **Phân tích theo khoảng cách:**

  | Bin | RMSE | Bias | n |
  |---|---:|---:|---:|
  | 0–2 km | 8.21 | +3.87 | 244 (~72%) |
  | 2–5 km | 2.32 | +0.14 | 45 |
  | 5–10 km | 2.44 | −1.45 | 48 |

  Bin gần (0–2km) sai số cao chủ yếu do urban clutter + building entry loss biến thiên lớn. Bin xa (2–10km) sai số ~2.3 dB — rất tốt cho ứng dụng LoRa.

- **Số trên random split (KHÔNG dùng làm số defense):** RMSE 3.50 dBm trên `devices_history_full.csv` (stratified 80/20 by gateway). Gap so với temporal hold-out (~2×) phản ánh leakage cùng walk session ở random split.
- **Khi chọn thuật toán:** so sánh với XGBoost cùng 21 đặc trưng trên random split — ET hơn 0.30 dB (3.50 vs 3.80). Không benchmark với RandomForest/LightGBM/CatBoost.

## 6. Ba đầu ra phủ sóng

| Đầu ra | Vai trò | Mô hình dùng |
|---|---|---|
| **Dự đoán điểm** (`/coverage/predict`) | Click 1 toạ độ → RSSI/SNR/PDR/SF khuyến nghị | Stage 1 + Extra Trees |
| **Bản đồ ước lượng** | Heatmap RSSI vùng (composite max-aggregate qua tất cả gateway) | Stage 1 P.1812 + DTM + per-gw NF + survey overlay (ML đã drop từ 2026-06-09) |
| **Bản đồ SF tối thiểu** | Vùng cần SF nào để link khả thi | Stage 1 P.1812 + DSM + bias từ khảo sát |

## 7. Dữ liệu

- **DEM nền (terrain):** Copernicus Global DEM 30m.
- **DSM bề mặt:** Copernicus + gap-fill ESA WorldCover (land cover) + Google Buildings + Microsoft Buildings.
- **Khảo sát thực địa:** ~10.000 điểm walk-measure Đà Nẵng, lưu trong hypertable `ts.survey_training` (Timescale).
- **Tách tập:** train+val = Nov–Dec 2025 (random); test = Jan–Feb 2026 (temporal hold-out).
- **Luồng kiểm duyệt:** dữ liệu mới → `ts.survey_quarantine` → admin duyệt → `ts.survey_training`.

## 8. Luồng vận hành chính

1. **Đăng nhập** (JWT + refresh cookie HttpOnly, rate-limit, lockout).
2. **Khảo sát:** chọn nguồn (LPWANMapper hoặc ChirpStack) → web nhận packet real-time qua SSE.
3. **Đóng góp dữ liệu:** sync từ nguồn linked hoặc upload CSV/JSON → vào hàng chờ admin duyệt.
4. **Admin duyệt:** 4 chế độ approve batch (`all` / `points_only` / `gateways_only` / `reject`); approve điểm → ghi vào training table + trigger retrain ML (Celery) + reset cờ rebuild heatmap cho gateway bị ảnh hưởng; approve gateway → promote `geo.gateway_quarantine` → `geo.gateways` + backfill FK qua `serving_gateway_eui`.
5. **Dự đoán/hiển thị:** web gọi API → Stage 1 + Stage 2 → hiển thị bản đồ.

## 9. Hạ tầng triển khai

- **Container:** Docker Compose, image `timescale/timescaledb-ha:pg17-ts2.17-all`.
- **Reverse proxy:** Nginx (template trong `ops/`).
- **Object storage:** Cloudflare R2 (tile-server và artifact ML — chưa kích hoạt cho prod).
- **CI:** GitHub Actions — Ruff + mypy + import-linter + pytest + Alembic migrate + Docker smoke + ESLint + JSDoc + Vite build.

## 10. Kết quả & hạn chế

**Đã làm được:**
- Pipeline Stage 1 vật lý + Stage 2 ML đầy đủ, có hot-reload sau retrain.
- Luồng đóng góp dữ liệu cộng đồng + admin duyệt + retrain tự động hoàn chỉnh.
- 3 chế độ bản đồ + dự đoán điểm chi tiết (bidirectional link budget).

**Hạn chế cần nêu rõ trong báo cáo:**
- Benchmark thuật toán còn hẹp (chỉ ET vs XGBoost cùng pipeline 21-feat).
- Bias +2.61 dB trên temporal hold-out cho thấy mô hình over-predict RSSI ~2.6 dB ở khoảng cách gần (<2km), nhiều khả năng do urban clutter biến thiên.
- Tập kiểm chứng temporal chỉ bao 4/11 gateway Đà Nẵng outdoor; chưa cover indoor gateway và 7 gateway còn lại.
- Dữ liệu khảo sát thưa ở vùng xa walk-survey → ngoại suy ML kém tin cậy.
- Stage 2 áp cho heatmap đã bị drop vì không ổn định trên vùng thưa dữ liệu → heatmap hiện thuần vật lý + overlay khảo sát.

## 11. Hướng phát triển

- Mở rộng tập kiểm chứng sang gateway indoor và 7 gateway Đà Nẵng còn lại chưa có trong hold-out.
- Hiệu chỉnh bias +2.61 dB ở serving layer hoặc qua retrain với feature mới (urban density biến thiên).
- Mở rộng benchmark sang RandomForest / LightGBM / Ridge baseline.
- Mobile app (React Native) cho khảo sát thực địa.
- Tile-server PMTiles thay vì GeoJSON tĩnh để giảm tải client.
