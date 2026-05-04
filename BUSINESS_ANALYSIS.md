# Phân Tích Nghiệp Vụ — Hệ Thống Phân Tích Vùng Phủ Sóng LoRa

> **Dự án:** DATN (Đồ Án Tốt Nghiệp)  
> **Ngày phân tích:** 2026-05-01  
> **Người phân tích:** Claude Code (chỉ đọc, không sửa code)

---

## 1. Tổng Quan Dự Án

Hệ thống phân tích vùng phủ sóng **LoRaWAN** phục vụ đo kiểm thực địa (drive test), dự đoán vùng phủ bằng Machine Learning, và tư vấn vùng phủ cho người dùng cuối — được triển khai thực tế tại **thành phố Đà Nẵng**.

### Mục Tiêu Nghiệp Vụ

| # | Mục tiêu | Chi tiết |
|---|----------|----------|
| 1 | Thu thập dữ liệu tín hiệu | Nhận đo lường từ thiết bị LoRa qua ChirpStack webhook hoặc nhập thủ công |
| 2 | Trực quan hóa vùng phủ | Hiển thị điểm đo, heatmap, lưới dự đoán ML trên bản đồ Mapbox |
| 3 | Dự đoán vùng phủ ML | Huấn luyện mô hình XGBoost/Random Forest/Gaussian Process, dự đoán RSSI theo lưới không gian |
| 4 | Tư vấn vùng phủ | API cho người dùng cuối: kiểm tra tín hiệu tại tọa độ, gợi ý hướng di chuyển để bắt sóng |
| 5 | Mô phỏng giả định | Cho phép đặt cổng giả định để xem trước vùng phủ trước khi triển khai thực tế |
| 6 | Giám sát gateway | Theo dõi trạng thái uptime của từng gateway (online / degraded / offline) |
| 7 | Xuất dữ liệu | Xuất GeoJSON, KML, Excel BoQ, PDF báo cáo chiến dịch |

---

## 2. Kiến Trúc Tổng Thể

```
┌────────────────────────────────────────────────────────────┐
│                        FRONTEND                            │
│  React 19 + Vite + Mapbox GL + Deck.gl                     │
│  Giao diện bản đồ, toolbar, bảng thống kê, xuất dữ liệu    │
└─────────────────────────┬──────────────────────────────────┘
                          │ HTTP / REST
┌─────────────────────────▼──────────────────────────────────┐
│                    BACKEND API                             │
│  Python FastAPI  —  /api/v1/...                            │
│  Routers (thin) → Services (logic) → ML modules           │
└───────────┬─────────────────────────┬──────────────────────┘
            │ SQLAlchemy Async        │ joblib
┌───────────▼──────────┐   ┌──────────▼───────────────────┐
│   PostgreSQL 16      │   │   ML Model Files (.joblib)   │
│   + PostGIS 3.4      │   │   + DEM SRTM tiles (.hgt)    │
│   15 bảng, spatial   │   │   Gateway metadata JSON      │
└──────────────────────┘   └──────────────────────────────┘
            ▲
┌───────────┴──────────┐
│  ChirpStack Server   │
│  (Webhook uplink →   │
│   POST /webhook/{slug})│
└──────────────────────┘
```

---

## 3. Các Nghiệp Vụ Chính

### 3.1. Quản Lý Dự Án & Cấu Hình

**Multi-tenant:** Hệ thống hỗ trợ nhiều tổ chức sử dụng đồng thời thông qua header `X-Project-Id`. Mỗi project có gateway, thiết bị, chiến dịch riêng biệt.

**Luồng khởi tạo:**
```
POST /campaigns/import-config
  → Upsert danh sách gateways (theo gateway_eui — chuẩn LoRaWAN TS002, 16 ký tự hex)
  → Upsert danh sách devices (theo dev_eui)
  → Trả về token webhook + URL để cấu hình ChirpStack
```

---

### 3.2. Thu Thập Dữ Liệu Đo Lường

**Hai nguồn chính:**

| Nguồn | Cơ chế | Ghi chú |
|-------|--------|---------|
| ChirpStack Webhook | `POST /webhook/{slug}` | Thời gian thực, tự động |
| Nhập thủ công / CSV | Script `lpwan_import.py` | Batch, từ lpwanmapper JSON |

**Xử lý webhook:**
1. Xác thực chữ ký HMAC-SHA256 (header `X-Signature: sha256=...`) — ngăn giả mạo payload
2. Parse JSON ChirpStack → trích xuất GPS từ payload thiết bị (hỗ trợ 3 format: `default`, `cayenne`, `precise7`)
3. Kiểm tra trùng lặp (dedup): `(device_id, gateway_id, frame_count, measured_at)` trong cửa sổ 5 phút — đúng chuẩn LoRaWAN TS002 DedupWindowSize
4. Lưu vào bảng `measurements`
5. Trả về `201 Created` (mới) hoặc `200 OK` (đã tồn tại)

**Dữ liệu mỗi phép đo bao gồm:**
- Vị trí GPS (kinh độ, vĩ độ)
- `rssi_dbm` (cường độ tín hiệu, -200 ~ +20 dBm)
- `snr_db` (tỷ lệ tín hiệu/nhiễu, -30 ~ +30 dB)
- `spreading_factor` (SF7–SF12) — ảnh hưởng đến tốc độ và độ xa
- `bandwidth_khz` (125/250/500 kHz)
- `tx_power_dbm`, `coding_rate`
- Thời gian đo, nguồn dữ liệu, độ chính xác GPS (HDOP)

---

### 3.3. Phân Loại Vùng Phủ (Coverage Classification)

Theo tiêu chuẩn **LoRa Alliance CVT (Coverage Verification Tests)**:

| Mức | Ngưỡng RSSI | Ý nghĩa |
|-----|-------------|---------|
| `strong` (Tốt) | ≥ -90 dBm | Tín hiệu mạnh, ổn định |
| `medium` (Trung bình) | -105 ~ -90 dBm | Sử dụng được, đôi khi ngắt |
| `weak` (Yếu) | -120 ~ -105 dBm | Kết nối không ổn định |
| `none` (Không có sóng) | < -120 dBm | Ngoài vùng phủ |

---

### 3.4. API Tư Vấn Vùng Phủ (End-User Coverage Advisory)

Đây là **nghiệp vụ hướng người dùng cuối** — cho phép ứng dụng khác (app di động, dashboard) tích hợp để hỏi "Vị trí này có sóng không?":

**Kiểm tra vùng phủ tại tọa độ:**
```
GET /coverage/check?lat=16.047&lng=108.206&radiusM=300

Response:
{
  "lat": 16.047,
  "lng": 108.206,
  "level": "medium",
  "verdict": "Tín hiệu trung bình",       ← tiếng Việt
  "predictedRssiDbm": -98.5,
  "samplesUsed": 12,
  "nearestGateway": {
    "name": "GW-DaNang-01",
    "distanceM": 420,
    "bearingDeg": 45,
    "direction": "Đông Bắc"              ← tiếng Việt
  }
}
```

**Gợi ý hướng di chuyển để bắt sóng:**
```
GET /coverage/suggest-move?lat=16.047&lng=108.206&searchRadiusM=500

Response:
{
  "found": true,
  "bearingDeg": 270,
  "distanceM": 180,
  "direction": "Tây",
  "expectedLevel": "strong",
  "expectedVerdict": "Tín hiệu tốt",
  "predictedRssiDbm": -86.0
}
```

**Thuật toán:**
- Lấy các phép đo trong bán kính 300m
- Tính RSSI dự đoán bằng IDW (Inverse Distance Weighting): `RSSI = Σ(w_i × rssi_i) / Σ(w_i)` với `w_i = 1/d²`
- Tìm điểm gần nhất có RSSI ≥ -105 dBm (mức medium+) để gợi ý di chuyển

---

### 3.5. Machine Learning — Dự Đoán Vùng Phủ

#### Quy trình đầy đủ:

```
1. Thu thập đủ phép đo (≥ minMeasurements điểm)
         ↓
2. POST /predict/train/{campaignId}
   → Fetch dữ liệu training + join với gateway
   → Làm giàu đặc trưng bằng DEM (elevation SRTM)
   → Kỹ thuật đặc trưng 19 features
   → Huấn luyện mô hình + cross-validation
   → Lưu bundle .joblib + metadata vào DB
         ↓
3. POST /predict/run/{campaignId}
   → Tạo lưới không gian (50m × 50m)
   → Dự đoán RSSI + độ không chắc cho mỗi ô lưới
   → Lưu vào bảng prediction_grids
         ↓
4. Frontend hiển thị lưới dự đoán (MLGridLayer)
   + UncertaintyLayer (lớp độ không chắc chắn)
```

#### 19 Đặc Trưng (Features) Kỹ Thuật:

| Nhóm | Feature | Mô tả |
|------|---------|-------|
| Khoảng cách | `log_distance` | log(khoảng cách Haversine tính bằng mét) |
| Khoảng cách | `distance_3d` | Khoảng cách 3D (kể cả độ cao) |
| Khoảng cách | `fresnel_ratio` | Tỷ lệ chiếm dụng vùng Fresnel |
| Địa hình (DEM) | `h_diff` | Độ cao thiết bị nhận − độ cao gateway |
| Địa hình (DEM) | `los_flag` | Line-of-sight (1 = thông thoáng, 0 = bị chặn) |
| Địa hình (DEM) | `terrain_roughness` | Độ gồ ghề địa hình cục bộ |
| Môi trường | `building_density` | Mật độ tòa nhà (0–1) từ bảng environment_zones |
| Môi trường | `land_use_enc` | Loại đất mã hóa (đô thị=2, nông thôn=1, rừng=0) |
| Môi trường | `obstacle_count_los` | Số vật cản trên đường thẳng |
| Tham số LoRa | `spreading_factor` | SF7–SF12 |
| Tham số LoRa | `antenna_height_tx` | Chiều cao anten gateway (mét) |
| Tham số LoRa | `freq_mhz` | Tần số (thường 868 MHz) |
| Hướng | `azimuth_sin`, `azimuth_cos` | Góc phương vị TX→RX |
| Hướng | `elevation_sin`, `elevation_cos` | Góc ngẩng |
| Tác động địa hình | `max_obstacle_height` | Chiều cao vật cản tối đa (từ DEM) |
| Tác động địa hình | `terrain_crossings` | Số lần cắt địa hình |
| Tác động địa hình | `excess_path_height` | Chiều cao thừa so với đường LoS |

#### Ba Thuật Toán ML:

| Thuật toán | Thông số | Phù hợp khi |
|-----------|----------|-------------|
| **XGBoost** (mặc định) | n_estimators=500, lr=0.05, max_depth=6 | Dữ liệu nhiều, cần độ chính xác cao |
| **Random Forest** | n_estimators=300, oob_score=True | Cần giải thích feature importance |
| **Gaussian Process** | Kernel: ConstantKernel × (Matern + WhiteKernel) | Cần ước lượng độ không chắc; tối đa 300 mẫu do độ phức tạp O(n³) |

#### Ngoài ML — Nội suy Truyền Thống:

- **IDW** (Inverse Distance Weighting): Nội suy nhanh, không cần huấn luyện
- **Kriging**: Nội suy địa thống kê (geostatistical), dùng thư viện `pykrige`

---

### 3.6. Mô Phỏng Giả Định (What-If Simulator)

Cho phép kỹ sư đặt **cổng giả định** để xem trước vùng phủ **trước khi lắp đặt thực tế**:

```
POST /simulator/coverage
{
  "transmitters": [
    {"lat": 16.047, "lng": 108.206, "txPowerDbm": 27, "antennaGainDbi": 5}
  ],
  "bbox": {"minLat": 16.0, "maxLat": 16.1, "minLng": 108.1, "maxLng": 108.3},
  "gridResolutionM": 100,
  "environment": "urban"
}
```

**Mô hình suy hao đường truyền (Log-distance Path Loss):**
```
PL(d) = 40 dB + 10 × n × log10(d)
RSSI = TxPower + AntennaGain − PL(d)
```

Hệ số suy hao `n` theo môi trường:

| Môi trường | n | Đặc điểm |
|-----------|---|----------|
| Urban (đô thị) | 3.5 | Nhiều tòa nhà, che chắn cao |
| Suburban (ngoại ô) | 3.0 | Thưa thớt hơn |
| Rural (nông thôn) | 2.5 | Thoáng, ít vật cản |
| Forest (rừng) | 3.8 | Tán cây hấp thụ mạnh |
| Coastal (ven biển) | 2.7 | Nước giúp truyền xa |
| Mountain (núi) | 3.2 | Địa hình phức tạp |

Với nhiều gateway giả định: lấy RSSI **tốt nhất** (max) tại mỗi ô lưới.

---

### 3.7. Giám Sát Sức Khỏe Gateway

```
GET /gateway-health?projectId=...&notify=false
```

**Trạng thái gateway:**

| Trạng thái | Điều kiện | Hành động |
|-----------|-----------|----------|
| `online` | lastSeenAt < 1 giờ | Bình thường |
| `degraded` | 1–24 giờ không có uplink | Cảnh báo |
| `offline` | > 24 giờ không có uplink | Cảnh báo + webhook nếu `notify=true` |

Kết quả bao gồm: `uplinkCount24h`, `uptimePercent24h`, `hoursSinceLastSeen`.

---

### 3.8. Xuất Dữ Liệu

| Format | Endpoint | Mục đích |
|--------|----------|---------|
| **GeoJSON** | `GET /exports/{id}/measurements.geojson` | Nhập vào QGIS, Mapbox Studio |
| **KML** | `GET /exports/{id}/measurements.kml` | Mở trong Google Earth |
| **Excel BoQ** | `GET /exports/{id}/boq.xlsx` | Bill of Quantities — danh sách gateway cho đấu thầu |
| **PDF Report** | `GET /reports/{id}.pdf` | Báo cáo chiến dịch (tổng quan, thống kê, ML metrics, danh sách gateway) |

---

### 3.9. Các Nghiệp Vụ Bổ Sung

| Nghiệp vụ | Endpoint/Service | Mô tả |
|----------|-----------------|-------|
| **Snapshot Grid** | `/snapshots` | Lưu/phục hồi lưới dự đoán theo thời gian — so sánh vùng phủ qua các chiến dịch |
| **Calibration** | `/calibration` | Hiệu chỉnh offset tín hiệu theo từng gateway (bù sai số anten) |
| **Scenario Compare** | `/scenarios` + `ComparePage` | So sánh nhiều kịch bản vùng phủ cạnh nhau |
| **Outbound Webhook** | `/webhooks` + `webhook_dispatcher` | Gửi sự kiện ra ngoài (gateway.offline, model.trained, grid.ready) với retry tự động |
| **Optimizer** | `/optimizer` | Tối ưu vị trí đặt gateway |
| **Sandbox** | `SandboxPage` | API explorer tích hợp trong UI |

---

## 4. Cấu Trúc Cơ Sở Dữ Liệu

### 4.1. Sơ Đồ Quan Hệ (ERD — Dạng Text)

```
projects (1)──────────────────────────────────────────────────────────────(N) gateways
    │                                                                          │
    │                                                                          │
    └──(N) devices                                                             │
    │                                                                          │
    └──(N) campaigns ──(N:N)── environment_zones                              │
              │                                                                │
              └──(N) measurements ────────────────────────────────────────────┘
                          │         \                  \
                          │          (N) ml_predictions  \
                          │               (1) ml_models    \
                          │                    │             │
                          └──(N) prediction_grids            └── devices (1)
                                    │
                                    └──(N) heatmap_caches (TTL)

webhook_subscriptions ── webhook_events
snapshot_grids
calibration_factors ── gateways
```

### 4.2. Các Bảng Quan Trọng

| Bảng | Số cột chính | Ghi chú |
|------|-------------|---------|
| `measurements` | 18 cột | Bảng trung tâm, ~7300+ bản ghi seed |
| `prediction_grids` | 7 cột | Lưới dự đoán ML, index không gian GIST |
| `ml_models` | 10 cột | Metadata model + metrics (RMSE, MAE, R²) |
| `gateways` | 10 cột | Vị trí PostGIS POINT + thông số anten |
| `heatmap_caches` | 8 cột | Cache tile heatmap với `expires_at` TTL |

### 4.3. Soft Delete & Audit

Tất cả bảng chính dùng `deleted_at IS NULL` để lọc — không xóa vật lý, đảm bảo lịch sử.

---

## 5. Stack Công Nghệ

| Tầng | Công nghệ | Phiên bản |
|------|----------|----------|
| **Frontend** | React + Vite | React 19.2.4 |
| **Map** | Mapbox GL + Deck.gl | mapbox-gl 3.0.0 |
| **HTTP Client** | Axios | 1.14.0 |
| **Backend** | Python FastAPI | 0.111.0 |
| **ASGI Server** | Uvicorn | 0.29.0 |
| **ORM** | SQLAlchemy Async | 2.0.30 |
| **DB Driver** | asyncpg | 0.29.0 |
| **Database** | PostgreSQL + PostGIS | 16 + 3.4 |
| **ML** | XGBoost + scikit-learn | 2.0.3 + 1.4.2 |
| **Kriging** | pykrige | 1.7.2 |
| **DEM** | rasterio (SRTM HGT) | 1.3.10 |
| **Serialization** | joblib | 1.4.2 |
| **Export** | openpyxl + ReportLab | 3.1.2 + 4.2.0 |
| **Container** | Docker + docker-compose | — |

---

## 6. Bảo Mật & Quan Sát

### 6.1. Bảo Mật

| Cơ chế | Nơi áp dụng | Chi tiết |
|--------|-------------|---------|
| HMAC-SHA256 | Webhook inbound | Header `X-Signature: sha256=...` |
| CORS whitelist | Toàn bộ API | Chỉ `localhost:3000`, `localhost:5173` |
| Rate limiting | `/predict/train` | 5 req/phút (CPU nặng) |
| Multi-tenant | Mọi query | Header `X-Project-Id` + DB filter |
| Path traversal | Load model file | UUID validation + safe path resolution |

### 6.2. Quan Sát (Observability)

| Cơ chế | Endpoint/Cơ chế |
|--------|----------------|
| Structured JSON logging | stdout (12-Factor F11) |
| Correlation ID | Header `X-Request-ID` → lan truyền qua log |
| RED Metrics | `GET /metrics` → requests, errors, duration |
| Health check | `GET /health` → `{status: "ok"}` |

---

## 7. Luồng Dữ Liệu End-to-End

```
[Thiết bị LoRa]
      │ uplink (radio)
      ▼
[ChirpStack Server]
      │ POST /webhook/{slug} (HMAC signed)
      ▼
[Backend: webhook.py]
  1. Xác thực HMAC-SHA256
  2. Parse JSON, trích GPS
  3. Dedup check (5-phút window)
  4. INSERT INTO measurements
      │
      ▼
[Bảng measurements] ──────────────────────────────────────────┐
      │                                                        │
      │ POST /predict/train/{campaignId}                       │
      ▼                                                        │
[ML Pipeline]                                                  │
  - Fetch + enrich DEM                                        │
  - Feature engineering (19 features)                         │
  - Train XGBoost / RF / GP                                   │
  - K-fold cross-validation                                   │
  - Save .joblib + metrics to DB                              │
      │                                                        │
      │ POST /predict/run/{campaignId}                         │
      ▼                                                        │
[Grid Generation]                                              │
  - Tạo lưới 50m × 50m                                       │
  - Dự đoán RSSI + uncertainty mỗi ô                         │
  - INSERT INTO prediction_grids                              │
      │                                                        │
      ▼                                                        ▼
[Frontend — React]                                     [API Tư Vấn]
  ├── ScatterLayer (điểm thô)              GET /coverage/check
  ├── HeatmapLayer (nội suy IDW)           GET /coverage/suggest-move
  ├── MLGridLayer (dự đoán ML)
  └── UncertaintyLayer (độ không chắc)
```

---

## 8. Các Điểm Đặc Biệt Đáng Chú Ý

### 8.1. Tính Năng Nổi Bật

1. **Chuẩn hóa theo LoRa Alliance CVT** — ngưỡng -90/-105/-120 dBm được triển khai nhất quán từ backend đến frontend
2. **DEM SRTM Integration** — dữ liệu địa hình thực tế nâng cao độ chính xác 19 features ML
3. **Dedup LoRaWAN chuẩn** — xử lý đúng cửa sổ 5 phút theo TS002
4. **19-feature engineering** — kết hợp địa hình, LoRa params, hướng, Fresnel zone — toàn diện hơn mô hình đơn giản
5. **Tiếng Việt end-user API** — `verdict`, `direction` trả về tiếng Việt sẵn cho tích hợp app
6. **Snapshot Grid** — cho phép phân tích xu hướng vùng phủ theo thời gian

### 8.2. Giới Hạn Hiện Tại

| Hạn chế | Nguyên nhân | Tác động |
|--------|-------------|---------|
| GP tối đa 300 mẫu | O(n³) complexity | Dùng XGBoost/RF cho dataset lớn |
| DEM phải tải tay | SRTM tiles không tự động | Cần chạy script thủ công |
| Không có xác thực | Dùng nội bộ | Không deploy public nếu chưa thêm auth |
| Tiêu thụ bộ nhớ cao | Mapbox + Deck.gl layers | Cần thiết bị đủ mạnh |

---

## 9. Hướng Mở Rộng Tiềm Năng

| Hướng | Chi tiết |
|-------|---------|
| Xác thực người dùng | Thêm JWT / OAuth2 để hỗ trợ nhiều người dùng với phân quyền |
| MLflow Integration | `mlflow_run_id` đã có trong schema — chỉ cần kết nối MLflow server |
| Mobile App | `MobilePage.jsx` đã có — có thể đóng gói thành PWA |
| Real-time WebSocket | Cập nhật live khi có phép đo mới từ ChirpStack |
| Heatmap cache cron | `expires_at` đã có trong schema — thêm cron job để xóa cache hết hạn |
| Mô hình Okumura-Hata | `algorithm` enum đã có `okumura_hata` — cần implement thêm |

---

## 10. Từ Điển Thuật Ngữ

| Thuật ngữ | Giải thích |
|----------|-----------|
| **LoRaWAN** | Giao thức mạng không dây tầm xa, tiêu thụ điện thấp |
| **RSSI** | Received Signal Strength Indicator — cường độ tín hiệu nhận (dBm) |
| **SNR** | Signal-to-Noise Ratio — tỷ lệ tín hiệu/nhiễu (dB) |
| **SF (Spreading Factor)** | SF7–SF12: càng cao → càng xa, càng chậm |
| **Gateway / Cổng** | Thiết bị trung gian, nhận tín hiệu LoRa → gửi lên server |
| **Campaign / Chiến dịch** | Đợt đo kiểm thực địa (drive test) tại một khu vực |
| **DEM** | Digital Elevation Model — mô hình số địa hình (SRTM HGT tiles) |
| **IDW** | Inverse Distance Weighting — nội suy theo nghịch khoảng cách |
| **Kriging** | Nội suy địa thống kê (geostatistical interpolation) |
| **BoQ** | Bill of Quantities — bảng danh mục vật tư cho đấu thầu |
| **HMAC** | Hash-based Message Authentication Code — xác thực webhook |
| **ChirpStack** | Phần mềm LoRaWAN Network Server mã nguồn mở |
| **PostGIS** | Extension không gian của PostgreSQL — hỗ trợ ST_DWithin, GIST index |
| **GeoJSON** | Định dạng dữ liệu địa lý theo chuẩn JSON (RFC 7946) |
| **KML** | Keyhole Markup Language — định dạng Google Earth |
| **Fresnel Zone** | Vùng không gian quan trọng trên đường truyền sóng vô tuyến |

---

*File này được tạo bởi Claude Code — chỉ đọc và phân tích, không sửa đổi code dự án.*
