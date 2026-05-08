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

// Gateway marker — chấm tròn xanh.
export const GATEWAY_MARKER_STYLE = {
  size: "20px",
  background: "#1d4ed8",
  border: "2px solid white",
  boxShadow: "0 0 4px rgba(0,0,0,0.5)",
  borderRadius: "50%",
};

// Search/Predict marker — drop pin (border-radius 50% 50% 50% 0 + xoay -45°).
// Color set runtime theo coverage_status (xem STATUS_COLOR).
export const PREDICT_MARKER_STYLE = {
  size: "22px",
  border: "3px solid white",
  boxShadow: "0 0 6px rgba(0,0,0,0.5)",
};
