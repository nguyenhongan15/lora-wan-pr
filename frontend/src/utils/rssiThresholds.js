/**
 * rssiThresholds.js — Nguồn sự thật duy nhất cho ngưỡng RSSI toàn app.
 *
 * Chuẩn: LoRa Alliance Coverage Verification Test (CVT)
 *   Strong  ≥ −90 dBm   — link chắc chắn, margin cao
 *   Medium  −90 ~ −105  — link ổn định trong điều kiện bình thường
 *   Weak    −105 ~ −120 — link mỏng manh, dễ mất gói khi fading nhẹ
 *   Floor   < −120 dBm  — dưới ngưỡng tin cậy
 *
 * Thang hiển thị:
 *   RSSI_SCALE_MIN = −135 dBm  (SF12 sensitivity floor SX1276)
 *   RSSI_SCALE_MAX = −55  dBm  (max thực tế đô thị)
 *   RSSI_SCALE_RANGE = 80 dBm
 *
 * Intensity tương ứng các ngưỡng (= (rssi − MIN) / RANGE):
 *   −120 dBm → 0.19
 *   −105 dBm → 0.38
 *    −90 dBm → 0.56
 *
 * Mọi file cần ngưỡng đều import từ đây —
 * không hardcode số magic ở ScatterLayer, coverage.js, strings.js, v.v.
 */

// ── Ngưỡng phân loại (dBm) ───────────────────────────────────────────────────
export const RSSI_STRONG = -90;   // ≥ RSSI_STRONG          → Strong
export const RSSI_MEDIUM = -105;  // RSSI_STRONG ~ RSSI_MEDIUM → Medium
export const RSSI_WEAK   = -120;  // RSSI_MEDIUM ~ RSSI_WEAK   → Weak
                                  // < RSSI_WEAK             → Very Weak / Floor

// ── Thang hiển thị (dBm) ─────────────────────────────────────────────────────
export const RSSI_SCALE_MIN   = -135;
export const RSSI_SCALE_MAX   =  -55;
export const RSSI_SCALE_RANGE = RSSI_SCALE_MAX - RSSI_SCALE_MIN; // 80

// ── Intensity tại các ngưỡng (dùng cho Mapbox paint stops) ───────────────────
// intensity(rssi) = (rssi − RSSI_SCALE_MIN) / RSSI_SCALE_RANGE
export const INTENSITY_AT_WEAK   = (RSSI_WEAK   - RSSI_SCALE_MIN) / RSSI_SCALE_RANGE; // 0.1875
export const INTENSITY_AT_MEDIUM = (RSSI_MEDIUM - RSSI_SCALE_MIN) / RSSI_SCALE_RANGE; // 0.375
export const INTENSITY_AT_STRONG = (RSSI_STRONG - RSSI_SCALE_MIN) / RSSI_SCALE_RANGE; // 0.5625