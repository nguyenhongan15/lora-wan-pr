// @ts-check
// Config tách khỏi CoverageMap.jsx để chỉnh sửa "data" mà không chạm vào
// logic component: hình học mặc định, basemap tile, ngưỡng màu RSSI,
// kiểu marker, defaults SF/freq/sort. Khi muốn đổi basemap, ngưỡng phủ
// sóng, hay màu trạng thái — chỉ sửa file này.

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

// VN AS923-2 — DNIIT seed cũng dùng 923 (xem migrations/seeds/seed_gateways.sql).
export const DEFAULT_FREQ_MHZ = 923;

/** @type {import("../api/client.js").SortBy} */
export const DEFAULT_SORT_BY = "timestamp";
/** @type {import("../api/client.js").SortOrder} */
export const DEFAULT_SORT_ORDER = "desc";

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
 * Basemap raster tiles (CARTO Voyager — free for OSM-attributed use)
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

/* ─────────────────────────────────────────────────────────────────────────
 * Survey circle paint — maplibre `step` expression theo RSSI dBm.
 *  ≥ -100 : strong  (green)
 *  [-115, -100) : good (yellow)
 *  [-120, -115) : marginal (orange)
 *  < -120 : weak (red)
 * Đổi ngưỡng / màu ở đây sẽ thay đổi cách hiển thị toàn bộ map.
 * ─────────────────────────────────────────────────────────────────────── */

export const SURVEY_CIRCLE_PAINT = {
  "circle-radius": 4,
  "circle-color": [
    "step",
    ["get", "rssi_dbm"],
    "#dc2626", // < -120
    -120,
    "#f97316", // [-120, -115)
    -115,
    "#eab308", // [-115, -100)
    -100,
    "#16a34a", // ≥ -100
  ],
  "circle-stroke-color": "#ffffff",
  "circle-stroke-width": 1,
};

/* ─────────────────────────────────────────────────────────────────────────
 * DOM marker styling
 * ─────────────────────────────────────────────────────────────────────── */

// Gateway marker — folium-style drop pin: SVG teardrop (đáy nhọn ở dưới)
// fill đen, viền trắng, icon tower-cell trắng trong vòng tròn trên cùng.
// Render bằng SVG path để tip luôn ở giữa-đáy → kết hợp anchor='bottom'
// đặt tip đúng tọa độ gateway. Width/height tỷ lệ 28:37 giống Leaflet default.
export const GATEWAY_MARKER_STYLE = {
  width: 20,
  height: 26,
  fill: "#ffffff",
  stroke: "#000000",
  iconColor: "#0284c7",
};

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
