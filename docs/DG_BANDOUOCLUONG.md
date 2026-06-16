# Đánh giá Bản đồ Ước lượng Phủ sóng RSSI

Tài liệu đánh giá đầu ra "Bản đồ ước lượng" (RSSI composite heatmap) — một trong ba đầu ra phủ sóng của hệ thống. Trạng thái tham chiếu: rebuild ngày **16/06/2026 03:07 UTC**, manifest tại `apps/web-app/public/coverage/rssi/manifest.json`.

## 1. Mô tả đầu ra

### 1.1. Mục đích

Bản đồ ước lượng cung cấp cho người dùng (cộng đồng, kỹ sư triển khai) một bản đồ phủ sóng RSSI dự kiến cho toàn bộ khu vực Đà Nẵng dưới dạng raster 50m, tổng hợp đóng góp của tất cả gateway đang hoạt động. Khác với chế độ "Dự đoán điểm" (chỉ 1 toạ độ) và "Bản đồ SF tối thiểu" (vùng cần SF nào), bản đồ ước lượng trả lời câu hỏi: *"Tại bất kỳ điểm nào trên Đà Nẵng, RSSI tốt nhất nhận được từ mạng gateway hiện tại là bao nhiêu?"*.

### 1.2. Mô hình & cấu hình

| Tham số                     | Giá trị                                                              |
| --------------------------- | -------------------------------------------------------------------- |
| Mô hình                     | `ITU-R P.1812 + DTM + per-gw NF + survey overlay (per-gw)`           |
| Lưới                        | 50 m × 50 m                                                          |
| Bounding box                | lat 15.8 – 16.3, lon 107.9 – 108.5 (Đà Nẵng)                         |
| Kích thước lưới             | 1.285 × 1.115 ≈ 1.43 triệu ô (~3.580 km²)                            |
| `location_percent`          | 10 % (quantile vị trí bảo thủ — chỉ 10 % điểm tệ hơn)                |
| `redundancy_threshold_dbm`  | −130 dBm                                                             |
| Sea mask                    | DEM-based, ngưỡng ≤ 0.5 m → 510.780 ô bị mask (biển + sông lớn)      |
| Aggregation đa gateway      | Max-agg (lấy RSSI tốt nhất trong các gateway)                        |
| Survey overlay              | bật, scope = `per_gw`, max link 50 km                                |

### 1.3. Stack vật lý

- **Path loss:** ITU-R P.1812-7 (Recommendation cho VHF/UHF 30 MHz – 6 GHz, time/location variability).
- **Clutter loss:** ITU-R P.2108 (skip khi đã có surface DEM tích hợp building, tránh double-count — đã verify n=500: bias +26.27 → +2.66 dB, RMSE 29.66 → 12.33 dB).
- **Building entry loss:** ITU-R P.2109 cho thuê bao indoor.
- **DEM/DSM:** Copernicus 30 m + ESA WorldCover 10 m gap-fill + Google Buildings + Microsoft Buildings.
- **Per-gateway noise floor:** hiệu chỉnh từ dữ liệu khảo sát thực địa (Migration 0020).

### 1.4. Lý do KHÔNG dùng ML cho bản đồ này

Ngày 09/06/2026, Stage 2 ML (Extra Trees) bị **drop** khỏi bản đồ ước lượng vì không ổn định ở vùng thưa dữ liệu khảo sát — extrapolation ML sang 99,8 % cell không có ground-truth tạo ra artifact phi vật lý (RSSI "đẹp" ở vùng chưa từng đi khảo sát). Bản đồ hiện tại dùng thuần mô hình vật lý + overlay điểm khảo sát thực, đảm bảo tính nhất quán địa hình.

## 2. Kết quả đạt được

### 2.1. Số liệu rebuild gần nhất (16/06/2026)

- **Coverage:** 13/13 gateway có dữ liệu được compose vào bản đồ.
- **Khảo sát overlay:** 12.361 điểm sau filter d<50 km (chống corruption survey ETL).
- **Cell có ground-truth:** 2.837 ô (~7.1 km²) — vùng người dùng đã đi khảo sát thực.
- **Thời gian rebuild per gateway:** 263 – 347 s (trung bình ~310 s).
- **Per-gateway noise floor đo thật:**
  - 6/13 gateway có NF từ dữ liệu thực (range −97.5 → −111.7 dBm).
  - 7/13 gateway dùng giá trị fallback (NF = null trong manifest).

### 2.2. Cải tiến định lượng tích lũy

Các stage tinh chỉnh đã đo và xác nhận trên holdout (số liệu trích từ project memory):

| Stage                                    | Tác động RMSE                    | Trạng thái      |
| ---------------------------------------- | -------------------------------- | --------------- |
| Stage 1 ITU swap (bỏ log-distance)       | Baseline                         | ✅ Đã áp dụng   |
| Per-gateway noise floor (fix #3)         | 23.80 → 11.11 dB (SF12 holdout)  | ✅ Đã áp dụng   |
| Bottleneck label fix (fix #6)            | SF12 flip 100% downlink → uplink | ✅ Đã áp dụng   |
| Stage B — landcover gap-fill DSM         | −1.25 dB tổng, **−4.73 dB d<2km**| ✅ Đã áp dụng   |
| Stage D — Google + LC buildings          | **−2.40 dB Đà Nẵng**             | ✅ Đã áp dụng   |
| Stage A2 — climatic zones                | ≈ 0 dB tại p_time=50             | ✅ Wiring đúng, impact thấp |
| Stage C — canopy height                  | ≈ 0 dB urban Đà Nẵng             | ✅ Wiring đúng, giữ data cho rural |
| Stage A1 — antenna pattern omni default  | **+0.07 dB tệ hơn**              | ❌ Reject       |

## 3. Ưu điểm

### 3.1. Tính trung thực vật lý

- **Hoàn toàn dựa vào ITU-R chuẩn quốc tế** — không có "ảo giác ML" ở vùng thưa data. Mọi giá trị RSSI có thể truy ngược về công thức path loss + clutter + entry loss có nguồn gốc khuyến nghị ITU.
- **Per-gw NF đo thực** thay cho giả định NF đồng nhất (sai số phổ biến trong các nghiên cứu LoRa academic): tránh bias hệ thống tới ±10 dB do indoor/outdoor mixing.
- **Sea-mask DEM-based** loại 510.780 cell biển/sông → tránh hiện tượng "phủ sóng trên biển" thiếu thực tế thường thấy trong các tool free space.

### 3.2. Kết hợp data thực + dự đoán

- **Survey overlay 10 m** đè điểm khảo sát thực lên dự đoán: tại 2.837 cell đã đi đo, người dùng thấy số liệu thật, không phải dự đoán → tăng độ tin cậy ở khu vực dân cư.
- Per-gateway slice (`per_gw/*.geojson`) cho phép user kiểm tra đóng góp của từng gateway, hỗ trợ debug khi composite không hợp lý.

### 3.3. Tính tái lập (reproducibility)

- Manifest ghi đầy đủ: `generated_at`, `model`, `grid_m`, bbox, `location_percent`, sea mask path, NF per gw, sub-grid bounds — đủ để re-run từ raw data.
- Pipeline rebuild incremental qua Celery + Valkey: skip khi không có packet mới, full rebuild khi ≥1 gateway có data mới, reset cờ đúng sau approve/delete batch (bug đã fix 15/06/2026, test 8/8 PASS).

### 3.4. Đáp ứng performance demo

- Pre-generate GeoJSON tĩnh, frontend load qua MapLibre vector tiles không cần round-trip backend.
- Rebuild full 13 gateway ~70 phút trên VPS Hetzner CPX31 — chấp nhận được cho tần suất daily/weekly.

## 4. Nhược điểm & hạn chế

### 4.1. Validation coverage rất hẹp

- **12.361 điểm khảo sát chỉ map vào 2.837 cell (~0.2 % grid).** 99,8 % diện tích bản đồ là **extrapolation P.1812 thuần**, không có ground-truth đối chứng. Số RMSE Stage 1 cải tiến (−1.25 dB) chỉ valid trong vùng đã đo, không generalize cho toàn bbox.
- Phần lớn cell được đi đo nằm trong cụm DNIIT trung tâm Đà Nẵng. Vùng ngoại ô + đồi núi không có data → không thể đo bias hệ thống tại đó.

### 4.2. Per-gateway NF thiếu cho 7/13 gateway

Các gateway sau dùng NF fallback (null trong manifest):
- Kerlink iStation AEC
- Gateway Indoor2 S04.10
- DF_Binh Thuan
- DF_GW_2_NongSon
- DNIIT GW 0fd63b
- DF_RAK7268V2
- Gateway Indoor VNGALAXY

Hậu quả: vùng phủ của 7 gateway này (đặc biệt các gateway indoor + cluster Bình Thuận) có thể bias systematic, không được hiệu chỉnh.

### 4.3. Composite max-agg che dead-zone gateway yếu

- Max-aggregation lấy RSSI tốt nhất → bản đồ "đẹp" nhưng che lấp dead-zone của từng gateway riêng lẻ.
- 11 gateway cụm gần nhau ở trung tâm Đà Nẵng → composite tự nhiên thiên về SF7 dominant (đã được xác nhận và accept ngày 16/05/2026).
- Khi triển khai operator-grade: cần thêm chế độ **min-agg** hoặc per-gw view để định vị vùng yếu của từng gateway.

### 4.4. Không có RMSE riêng cho heatmap

- Số liệu RMSE 7.10 dB (Stage 2 temporal holdout) **không phải** số đánh giá bản đồ ước lượng — nó là số của `/coverage/predict` (Stage 1+2 endpoint).
- Bản đồ ước lượng hiện chưa có holdout-eval riêng theo cohort distance + per-gw. Báo cáo cuối nên bổ sung.

### 4.5. Scope chỉ Đà Nẵng

- Bounding box manifest cố định 15.8–16.3 lat / 107.9–108.5 lon — **không phủ Hải Phòng**, dù backend đã có data 2 gateway Hải Phòng.
- Mở rộng tới Hải Phòng cần thêm bbox + rebuild riêng, hiện chưa làm.

### 4.6. Các stage không cải thiện (negative results)

Phải báo cáo trung thực, không tô vẽ:
- **Stage A2 climatic zones** ≈ 0 dB tại p_time=50 — wiring đúng nhưng vô hiệu trong điều kiện thời gian trung bình.
- **Stage C canopy height** ≈ 0 dB urban Đà Nẵng — chỉ có giá trị cho khu vực rural (chưa eval).
- **Stage A1 antenna pattern omni default** TỆ HƠN +0.07 dB → đã reject. Spike +43 dB tại d=5-10 km không phải do pattern, mà là **artifact DSM-receiver-inside-building** của 1 gateway + 1 site cụ thể.

### 4.7. Smoothing & morphology tắt

- `smooth_sigma_cell = null`, `opening_size_cell = null` → bản đồ giữ nguyên artefact của lưới, không Gaussian-smooth.
- Lợi: tính chính xác cell-level. Hại: hiển thị có thể "vỡ hạt" ở zoom cao, gây impression noisy.

## 5. Đánh giá tổng quan

### 5.1. Trạng thái chất lượng

| Tiêu chí                            | Mức   | Ghi chú                                                    |
| ----------------------------------- | ----- | ---------------------------------------------------------- |
| Tính khoa học (ITU compliance)      | Tốt   | Stack vật lý đầy đủ, chuẩn quốc tế                         |
| Độ phủ data ground-truth            | Yếu   | 0.2 % cell có data — phần lớn là extrapolation             |
| Tính ổn định (không hallucination)  | Tốt   | Loại ML khỏi heatmap → bỏ qua artifact phi vật lý          |
| Tính tái lập                        | Tốt   | Manifest đầy đủ, pipeline Celery incremental               |
| Validation quantitative             | Trung | Chỉ −1.25 ~ −4.73 dB RMSE measured; chưa có eval riêng     |
| Phù hợp DATN defense                | Tốt   | Đủ depth để bảo vệ, miễn trình bày trung thực hạn chế      |

### 5.2. Phù hợp use case nào

- ✅ Định hướng triển khai gateway mới (vùng nào yếu trong cụm Đà Nẵng).
- ✅ Visualization cho cộng đồng + báo cáo DATN.
- ⚠️ KHÔNG dùng cho operator-grade SLA (cần coverage data dày hơn nhiều).
- ❌ KHÔNG dùng cho vùng ngoài Đà Nẵng (không có data calibration).

## 6. Hướng cải tiến

### 6.1. Ngắn hạn (trước defense)

- Bổ sung **holdout eval riêng cho heatmap**: RMSE per-cohort distance + per-gw, để báo cáo có số liệu định lượng cho riêng bản đồ ước lượng (không borrow số của `/predict`).
- Đo NF thực cho 7/13 gateway còn thiếu — đã có khảo sát, chỉ cần chạy lại extractor.

### 6.2. Trung hạn

- Mở rộng bbox cho Hải Phòng + rebuild riêng, sau khi đủ data calibration (≥ 5 gateway, ≥ 2.000 điểm).
- Thêm chế độ visualization per-gw / min-agg để định vị dead-zone.
- Bật smoothing tuỳ chọn (Gaussian σ=1 cell) cho display layer, giữ raw cho eval.

### 6.3. Dài hạn

- PMTiles tile server thay GeoJSON tĩnh khi grid > 5 triệu cell.
- Kết hợp Stage 2 ML **chỉ trong vùng có ground-truth dày** (kernel-weighted), thuần vật lý ở vùng thưa — kết hợp ưu điểm hai cách.

---

**Tài liệu tham chiếu:**
- `apps/web-app/public/coverage/rssi/manifest.json` — manifest rebuild
- `scripts/precompute_rssi_heatmap.py` — pipeline rebuild
- `docs/KET_QUA_DAT_DUOC.md` — kết quả tổng thể dự án
- `docs/MO_TA_DU_AN.md` §5.2 — số liệu định lượng chính thức
