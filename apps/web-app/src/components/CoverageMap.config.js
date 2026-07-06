// @ts-check
// Config tách khỏi CoverageMap.jsx để chỉnh sửa "data" mà không chạm vào
// logic component: hình học mặc định, basemap tile, ngưỡng màu RSSI,
// kiểu marker, defaults SF/freq. Khi muốn đổi basemap, ngưỡng phủ
// sóng, hay màu trạng thái — chỉ sửa file này.

import { surveyRssiColorExpression } from "./legend.js";

/* ─────────────────────────────────────────────────────────────────────────
 * Geometry & camera
 * ─────────────────────────────────────────────────────────────────────── */

// Bbox vùng Đà Nẵng — query backend chỉ load điểm/gateway trong khung này.
export const DANANG_BBOX = {
  min_lon: 107.95,
  min_lat: 15.9,
  max_lon: 108.4,
  max_lat: 16.2,
};

// Centroid của 11 gateway DNIIT thực tế (tính từ
// r-dt/response_1777987688423.json).
export const INITIAL_CENTER = /** @type {[number, number]} */ ([
  108.188, 16.069,
]);
export const INITIAL_ZOOM = 11;

/* ─────────────────────────────────────────────────────────────────────────
 * Defaults LoRa
 * ─────────────────────────────────────────────────────────────────────── */

export const SF_OPTIONS = /** @type {const} */ ([7, 8, 9, 10, 11, 12]);
export const DEFAULT_SF = 12;

// VN AS923-2 cap — Max EIRP 14 dBm (TXPower index 0).
export const DEFAULT_TX_POWER_DBM = 14;

// VN AS923-2 — DNIIT seed cũng dùng 923 (xem migrations/seeds/seed_gateways.sql).
export const DEFAULT_FREQ_MHZ = 923;

/* ─────────────────────────────────────────────────────────────────────────
 * Color tokens (dùng chung popup badge + search marker + survey circle)
 * ─────────────────────────────────────────────────────────────────────── */

/** @type {Record<string, string>} */
export const STATUS_COLOR = {
  strong: "#16a34a",
  marginal: "#eab308",
  weak: "#f97316",
  no_coverage: "#dc2626",
};

// Fallback khi backend trả status mới chưa map (defensive default).
export const STATUS_COLOR_FALLBACK = "#7c3aed";

// Khoảng dB dùng để scale visual bar trong popup UL/DL block.
// −10 dB = sát chết; +20 dB = decode dư margin. Bar 100% rộng nếu margin ≥ max,
// 0% nếu ≤ min. Đổi 2 số này để bar nhạy hơn / tổng quát hơn.
export const MARGIN_BAR_RANGE = { min: -10, max: 20 };

/* ─────────────────────────────────────────────────────────────────────────
 * Basemap — hướng VECTOR (CARTO Voyager GL style).
 *
 * Dùng vector style (style.json, kèm glyphs/sprite/sources) thay cho raster tile
 * để XẾP LỚP được: lớp phủ RSSI (GeoJSON) được chèn DƯỚI các lớp đường + nhãn
 * của basemap (xem firstRoadOrLabelLayerId trong CoverageMap.jsx) → CẢ đường
 * lẫn chữ nằm TRÊN màu phủ mà màu vẫn hiện rõ (raster không làm được vì tile
 * nền là ảnh đặc, đặt lên trên sẽ che hết màu).
 *
 * Public, không cần API key. Biến thể: positron-gl-style / dark-matter-gl-style.
 * Revert về cách B (raster nhãn-trên-cùng): CoverageMap.config.js.bak-before-vector.
 * ─────────────────────────────────────────────────────────────────────── */

export const BASEMAP_STYLE =
  "https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json";

/* ─────────────────────────────────────────────────────────────────────────
 * Survey circle paint — palette + step expression lấy từ ./legend.js
 * (single source of truth). Đổi màu / ngưỡng ở legend.js sẽ tự động sync
 * cả paint expression này lẫn chip màu trong MapLegend.jsx.
 * ─────────────────────────────────────────────────────────────────────── */

export const SURVEY_CIRCLE_PAINT = {
  "circle-radius": 6,
  "circle-color": surveyRssiColorExpression(),
  "circle-stroke-color": "#ffffff",
  "circle-stroke-width": 1,
};

/* ─────────────────────────────────────────────────────────────────────────
 * DOM marker styling
 * ─────────────────────────────────────────────────────────────────────── */

// Search/Predict marker — drop pin (border-radius 50% 50% 50% 0 + xoay -45°).
// Color set runtime theo coverage_status (xem STATUS_COLOR).
export const PREDICT_MARKER_STYLE = {
  size: "22px",
  border: "3px solid white",
  boxShadow: "0 0 6px rgba(0,0,0,0.5)",
};

/* ─────────────────────────────────────────────────────────────────────────
 * Composite RSSI heatmap palette (mode='estimate').
 * Palette + ngưỡng tách sang ./legend.js (single source of truth, song song
 * SURVEY_RSSI_BINS). Khớp RSSI_BINS Python trong precompute_rssi_heatmap.py.
 * Đổi màu / ngưỡng / label ở legend.js sẽ sync cả paint expression lẫn chip
 * trong EstimatePanel.jsx.
 * ─────────────────────────────────────────────────────────────────────── */

// Độ đậm lớp phủ RSSI trên bản đồ. Trước đây 0.55 → màu bị pha nhiều với nền,
// lệch rõ với chip legend (vẽ màu đặc). Nâng lên 0.85 để màu bản đồ sát legend
// (đỏ ra đỏ) mà vẫn còn thấy lờ mờ đường phố nền. 1.0 = đặc hẳn (che nền);
// hạ về ~0.7 nếu muốn thấy nền rõ hơn.
export const RSSI_FILL_OPACITY = 0.65;
