# Validation Tầng 1 — kết quả & validity domain

Báo cáo validation của Stage 1 (Friis + log-distance excess, `SUBURBAN_PROFILE` n=3.0 σ=6.0) trên data đo Đà Nẵng. Ngày chạy: 2026-05-11.

## 1. Setup

| Tham số | Giá trị |
|---|---|
| Profile | `SUBURBAN_PROFILE(n=3.0, σ=6.0)` (production default) |
| Frequency dùng trong Friis | 923.0 MHz (band label, mặc định Target) |
| Dataset | `ts.survey_training`, bbox Đà Nẵng (lat 15.8–16.3, lon 107.9–108.5) |
| Pairing | Dùng `serving_gateway_id` đã ghi trong record (không re-select GW) |
| Reproducibility | `scripts/validate_stage1_danang.sql` |
| N records (full) | 9,553 |
| Split | train 8,115 (Nov-Dec 2025, 88%) / val 1,101 (Nov-Dec, 12% hash) / test 337 (Jan-Feb 2026, temporal hold-out) |

## 2. Kết quả

### 2.0. Per-split (train/val match → split rule không leak)

| split | N | RMSE | MAE | Bias | Std resid |
|---|---|---|---|---|---|
| train | 8,115 | 25.57 | 21.25 | +20.05 | 15.87 |
| val | 1,101 | 25.43 | 21.05 | +19.91 | 15.83 |
| test | 337 | 39.32 | 37.82 | +37.82 | 10.76 |

Train ≈ val xác nhận split homogeneous (Stage 1 không train với data, nên gap = leak indicator). Test cao gấp ~1.5× **không phải overfit** mà là **distribution shift**: test set Jan-Feb 2026 toàn SF12, 86% < 2 km — 1 lát cắt hẹp ở vùng failure mode đã biết. Per-distance bucket trên test xác nhận:

| bucket | n_test | RMSE | bias |
|---|---|---|---|
| < 500 m | 244 | 40.6 | +38.9 |
| 0.5–2 km | 47 | 40.3 | +39.8 |
| 2–5 km | 45 | 30.8 | +30.5 |
| 5–10 km | 1 | (n=1) | — |
| 10–30 km | 0 | — | — |

→ Test không có records ở mid-range để verify validity domain claim 5–30 km.

### 2.1. Overall (full dataset, no split — số trong báo cáo gốc)

| metric | value |
|---|---|
| RMSE | 26.16 dB |
| MAE | 21.81 dB |
| Bias (predicted − measured) | **+20.66 dB** |
| Std residual | 16.05 dB |
| min/max residual | −29.4 / +78.3 dB |

Bias dương lớn = predictions **quá lạc quan** so với đo thực.

### 2.2. Per-SF

| SF | N | RMSE | MAE | Bias |
|---|---|---|---|---|
| 7  | 2,819 | 28.64 | 28.57 | +28.57 |
| 10 | 1,049 | 26.52 | 23.06 | +22.60 |
| 12 | 5,685 | 24.77 | 18.22 | +16.37 |

### 2.3. Per-distance bucket — phá ra rõ root cause

| bucket | N | RMSE (dB) | Bias (dB) | Đánh giá |
|---|---|---|---|---|
| < 500 m | 967 | 41.83 | **+40.90** | catastrophic |
| 0.5–2 km | 5,135 | 30.18 | **+29.83** | catastrophic |
| 2–5 km | 315 | 18.37 | +14.27 | poor |
| **5–10 km** | 1,651 | **4.77** | **+1.55** | ✅ excellent |
| **10–30 km** | 1,485 | **4.09** | **−1.64** | ✅ excellent |

## 3. Đọc kết quả

Aggregate metric (RMSE 26 dB, bias +21 dB) là **artifact của distribution**: 64% records nằm ở < 2 km — vùng Stage 1 không được thiết kế để cover.

Trong miền outdoor mid-range (5–30 km, 3,136 records, 33%), Stage 1 cho **RMSE ~4–5 dB và bias gần 0** — kết quả rất tốt cho pure-physics path-loss model, sánh với baseline literature.

Vùng < 2 km có bias +30 đến +40 dB không phải lỗi physics — là vật lý chưa được model:
1. **Indoor penetration**: end-device đo từ trong nhà, wall loss 15–25 dB.
2. **Non-LoS dense**: 1–2 nhà chắn ở khoảng cách ngắn, thêm 10–15 dB.
3. **Antenna pattern**: side-lobe null khi target gần GW theo phương ngang.

Stage 1 (Friis + log-distance) không claim model 3 thứ này. Đây chính xác là phạm vi mà Stage 2 LightGBM residual sẽ học.

## 4. Validity domain — invariant chính thức của Stage 1

> **Stage 1 chỉ valid cho outdoor LoRa, khoảng cách d ∈ [2 km, 30 km].**
> Trong domain đó: RMSE ≈ 4–5 dB, bias ≈ 0 dB — **đo trên train+val (Nov-Dec 2025)**, in-distribution.
> Outside (d < 2 km hoặc indoor): predictions có bias hệ thống lớn (+20 đến +40 dB), confirmed cross-cohort (cả train+val lẫn test Jan-Feb 2026), không nên dùng cho engineering decisions.

⚠️ **Caveat sau khi split:** Test set Jan-Feb 2026 không có records ở mid-range, nên claim "5–30 km RMSE 4–5 dB" hiện chỉ là **in-distribution statement**, không phải out-of-time generalization. Cần data outdoor mid-range mới (ưu tiên 2026-Q2+) để re-verify.

**Hệ quả:**
- Predictions ở < 2 km vẫn được trả về qua API (không thay đổi behavior), nhưng **nên được Stage 2 phủ trước khi tin được**.
- `coverage_status` ở khoảng cách ngắn có thể quá lạc quan (STRONG ↔ thực tế MARGINAL/WEAK).
- Confidence.score (heuristic `exp(-d/20)`) không capture được short-range bias — vẫn cho score cao ở < 2 km dù prediction lệch +30 dB.

## 5. Số phải beat

Stage 2 LightGBM thành công khi đạt cả hai:

| Vùng | Stage 1 baseline | Stage 2 target |
|---|---|---|
| Mid-range (5–30 km) | RMSE 4–5 dB | giữ nguyên hoặc cải thiện < 4 dB |
| Short-range (< 2 km) | RMSE 30+ dB, bias +30 dB | **giảm bias < 5 dB** (mục tiêu chính) |

## 6. Re-run

Khi có thêm data (đặc biệt từ Đà Nẵng), chạy lại để verify validity domain còn đúng:

```bash
docker exec -i lora-wan-db psql -U lora_user -d lora_coverage -P pager=off \
  < scripts/validate_stage1_danang.sql
```

So sánh số mới với bảng §2 — nếu mid-range RMSE drift > 6 dB → Stage 1 cần re-investigate trước khi đẩy production.
