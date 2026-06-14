// @ts-check
// Nguồn chân lý (single source of truth) cho palette legend dùng chung
// trong dự án. Đổi màu / ngưỡng / label ở đây sẽ thay đổi đồng bộ:
//   - paint expression của Survey Points map (CoverageMap.config.js)
//   - chip màu hiển thị trên MapLegend.jsx
//
// Các map khác (composite RSSI heatmap, min-SF, admin batch_points)
// hiện vẫn dùng palette riêng — sẽ chuyển sang đây khi BIGBOSS quyết định
// thống nhất.

/**
 * @typedef {Object} RssiBin
 * @property {string} color  hex color
 * @property {number|null} low   ngưỡng dBm dưới (inclusive); null = không giới hạn dưới
 * @property {number|null} high  ngưỡng dBm trên (exclusive); null = không giới hạn trên
 * @property {string} label  nhãn tiếng Việt hiển thị trên legend
 */

// Bản đồ điểm đo — palette 6-bin theo convention heatmap (mạnh = đỏ ấm,
// yếu = xanh lạnh). Sắp xếp WEAK → STRONG (low tăng dần) để khớp contract
// maplibre `step` (stops phải tăng dần).
/** @type {RssiBin[]} */
export const SURVEY_RSSI_BINS = [
  { color: "#0000FF", low: null, high: -120, label: "< -120 dBm" },
  { color: "#00FFFF", low: -120, high: -115, label: "-115 đến -120 dBm" },
  { color: "#00FF00", low: -115, high: -110, label: "-110 đến -115 dBm" },
  { color: "#FFFF00", low: -110, high: -105, label: "-105 đến -110 dBm" },
  { color: "#FF8000", low: -105, high: -100, label: "-100 đến -105 dBm" },
  { color: "#FF0000", low: -100, high: null, label: "> -100 dBm" },
];

// Bản đồ ước lượng RSSI tổng hợp — DÙNG CHUNG palette với SURVEY_RSSI_BINS.
// Order đảo (bin 1 = STRONG = đỏ ấm) để khớp convention RSSI_BINS Python trong
// scripts/precompute_rssi_heatmap.py (bin_id 1=mạnh, 6=yếu). Cell < -130 dBm
// → transparent (notCovered). Đổi màu/ngưỡng ở SURVEY_RSSI_BINS sẽ sync cả 2.
/** @type {Record<number, { color: string, low: number|null, high: number|null, label: string }>} */
export const ESTIMATE_RSSI_BINS = {
  1: { color: "#FF0000", low: -100, high: null, label: "> −100 dBm" },
  2: { color: "#FF8000", low: -105, high: -100, label: "−105 đến −100 dBm" },
  3: { color: "#FFFF00", low: -110, high: -105, label: "−110 đến −105 dBm" },
  4: { color: "#00FF00", low: -115, high: -110, label: "−115 đến −110 dBm" },
  5: { color: "#00FFFF", low: -120, high: -115, label: "−120 đến −115 dBm" },
  6: { color: "#0000FF", low: null, high: -120, label: "< −120 dBm" },
};

/**
 * Derived map bin_id → color cho `match` expression maplibre + chip legend.
 * Khớp shape cũ `RSSI_BAND_COLORS` trong CoverageMap.config.js đã được rút.
 * @type {Record<number, string>}
 */
export const ESTIMATE_RSSI_BAND_COLORS = Object.fromEntries(
  Object.entries(ESTIMATE_RSSI_BINS).map(([k, v]) => [Number(k), v.color]),
);

/**
 * Match RSSI (dBm) → color từ SURVEY_RSSI_BINS (legend dùng chung).
 * Convention bin: `low <= rssi < high`; `low=null` = không giới hạn dưới,
 * `high=null` = không giới hạn trên. Fallback bin 0 (xanh lạnh nhất) nếu
 * không match — chỉ xảy ra khi BINS bị tách thiếu khoảng.
 *
 * @param {number} rssi
 * @returns {string} hex color
 */
export function colorForRssi(rssi) {
  for (const bin of SURVEY_RSSI_BINS) {
    const lowOk = bin.low === null || rssi >= bin.low;
    const highOk = bin.high === null || rssi < bin.high;
    if (lowOk && highOk) return bin.color;
  }
  return SURVEY_RSSI_BINS[0].color;
}

/**
 * Build maplibre `step` expression cho circle-color từ SURVEY_RSSI_BINS.
 * Contract maplibre: `["step", input, base, stop1, color1, stop2, color2, ...]`
 * — `base` là color khi input < stop1; sau đó với mỗi (stop_i, color_i) thì
 * value >= stop_i sẽ dùng color_i (cho tới khi gặp stop_{i+1}).
 *
 * @returns {any[]}
 */
export function surveyRssiColorExpression() {
  /** @type {any[]} */
  const expr = ["step", ["get", "rssi_dbm"], SURVEY_RSSI_BINS[0].color];
  for (let i = 1; i < SURVEY_RSSI_BINS.length; i++) {
    expr.push(SURVEY_RSSI_BINS[i].low, SURVEY_RSSI_BINS[i].color);
  }
  return expr;
}
