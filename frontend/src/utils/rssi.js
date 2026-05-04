import { RSSI_SCALE_MIN, RSSI_SCALE_RANGE, RSSI_STRONG, RSSI_MEDIUM, RSSI_WEAK } from "./rssiThresholds";

// Chuẩn hoá RSSI → intensity [0, 1]
export function rssiToIntensity(rssi) {
  return Math.max(0, Math.min(1, (rssi - RSSI_SCALE_MIN) / RSSI_SCALE_RANGE));
}

// Tạo normalizer động theo min/max thực tế của chiến dịch
export function makeRssiNormalizer(minRssi, maxRssi) {
  const range = maxRssi - minRssi;
  return (rssi) => Math.max(0, Math.min(1, (rssi - minRssi) / range));
}

// RSSI → hex màu (UI, không phải Mapbox) — theo LoRa Alliance CVT
export function rssiToColor(rssi) {
  if (rssi >= RSSI_STRONG) return "#a50026";  // ≥ −90
  if (rssi >= RSSI_MEDIUM) return "#fdae61";  // −90 ~ −105
  if (rssi >= RSSI_WEAK)   return "#74add1";  // −105 ~ −120
  return "#313695";                           // < −120
}

// RSSI → nhãn chữ
export function rssiLabel(rssi) {
  if (rssi >= RSSI_STRONG) return "Mạnh";
  if (rssi >= RSSI_MEDIUM) return "Trung bình";
  if (rssi >= RSSI_WEAK)   return "Yếu";
  return "Rất yếu";
}

/**
 * Tính exponential base tối ưu cho heatmap-weight.
 * Nhận stats object theo chuẩn API Contract (camelCase):
 *   { total, avgRssi, minRssi, maxRssi, avgSnr, [p75] }
 */
export function calcHeatmapBase(stats, targetWeight = 0.02) {
  if (!stats) return 3;
  const { minRssi, maxRssi, p75, avgRssi } = stats;
  if (minRssi == null || maxRssi == null) return 3;

  // Backend chưa có p75 → fallback dùng avgRssi
  const pivot = p75 ?? avgRssi ?? -100;
  const range = maxRssi - minRssi;
  if (range <= 0) return 3;

  const intensityPivot = Math.max(0.001, Math.min(0.999, (pivot - minRssi) / range));
  const base = Math.log(targetWeight) / Math.log(intensityPivot);
  return Math.round(Math.max(1.0, Math.min(8.0, base)) * 100) / 100;
}

// ── SNR Threshold theo SF (Semtech SX1276 datasheet) ─────────────────────────
export const SNR_THRESHOLD = {
  7:  -7.5,
  8:  -10.0,
  9:  -12.5,
  10: -15.0,
  11: -17.5,
  12: -20.0,
};

export function snrMargin(snr, sf) {
  const threshold = SNR_THRESHOLD[sf];
  if (snr == null || threshold == null) return null;
  return parseFloat((snr - threshold).toFixed(2));
}

export function snrMarginLabel(margin) {
  if (margin == null) return "—";
  if (margin > 6)  return "Tốt";
  if (margin > 2)  return "Ổn";
  if (margin > 0)  return "Ranh giới";
  return "Unreliable";
}
