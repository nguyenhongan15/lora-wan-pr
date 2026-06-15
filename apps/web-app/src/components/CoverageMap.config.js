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
 * Basemap raster tiles.
 *  - BASEMAP_STYLE (CARTO Voyager): basemap mặc định mọi tab.
 *  - SATELLITE_BASEMAP_STYLE (ESRI World Imagery): overlay raster chỉ
 *    hiện khi coverageViewMode === "minsf" (đối chiếu band SF với
 *    toà nhà/đường thực tế). Tab "Bản đồ ước lượng" không bật overlay.
 * ─────────────────────────────────────────────────────────────────────── */

export const BASEMAP_STYLE = {
  version: 8,
  sources: {
    basemap: {
      type: "raster",
      tiles: [
        "https://a.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png",
        "https://b.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png",
        "https://c.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png",
      ],
      tileSize: 256,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
      maxzoom: 19,
    },
  },
  layers: [{ id: "basemap", type: "raster", source: "basemap" }],
};

export const SATELLITE_BASEMAP_STYLE = {
  version: 8,
  sources: {
    basemap: {
      type: "raster",
      tiles: [
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      ],
      tileSize: 256,
      attribution:
        'Tiles &copy; Esri &mdash; Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community',
      maxzoom: 19,
    },
  },
  layers: [{ id: "basemap", type: "raster", source: "basemap" }],
};

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
 * Min-SF coverage map palette (paper Fig 11 style).
 * SF7 (inner, gw gần) = đỏ ấm; SF12 (outer, xa) = xanh dương lạnh.
 * Convention: SF nhỏ = signal mạnh, đỡ cần spread; SF lớn = xa, cần
 * sensitivity cao. Sequential cool→warm reversed cho "vùng dễ phục vụ ⇄ rìa".
 * ─────────────────────────────────────────────────────────────────────── */

/** @type {Record<number, string>} */
export const MINSF_BAND_COLORS = {
  7: "#d7191c",
  8: "#fdae61",
  9: "#ffffbf",
  10: "#abd9e9",
  11: "#2c7bb6",
  12: "#08306b",
};

// Opacity nền fill — đủ rõ band, vẫn thấy địa hình dưới.
export const MINSF_FILL_OPACITY = 0.55;

/* ─────────────────────────────────────────────────────────────────────────
 * Composite RSSI heatmap palette (mode='estimate').
 * Palette + ngưỡng tách sang ./legend.js (single source of truth, song song
 * SURVEY_RSSI_BINS). Khớp RSSI_BINS Python trong precompute_rssi_heatmap.py.
 * Đổi màu / ngưỡng / label ở legend.js sẽ sync cả paint expression lẫn chip
 * trong EstimatePanel.jsx.
 * ─────────────────────────────────────────────────────────────────────── */

export const RSSI_FILL_OPACITY = 0.55;
