// @ts-check
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { useQuery } from "@tanstack/react-query";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

import {
  listGateways,
  listSurveyTraining,
  predictCoverage,
} from "../api/client.js";
import {
  deleteUploadBatch,
  startLiveSession,
  syncLiveSession,
} from "../sources/client.js";
import { getUser, subscribe as subscribeAuth } from "../auth/store.js";
import { strings } from "../strings.js";
import { AlertModal } from "./Modal.jsx";
import { MapLegend } from "./MapLegend.jsx";
import { MapViewModeToggle } from "./MapViewModeToggle.jsx";
import { EstimatePanel } from "./EstimatePanel.jsx";
// MinSFPanel: tạm ẩn UI minsf, import lại khi bật lại toggle.
// import { MinSFPanel } from "./MinSFPanel.jsx";
import {
  PointsFilterToggleBtn,
  PointsFilterBody,
} from "./filters/PointsFilterPanel.jsx";
import {
  RealtimeToggleBtn,
  RealtimeBody,
} from "./filters/RealtimePanel.jsx";
import { AddressLookupPanel } from "./address/AddressLookupPanel.jsx";
import {
  BASEMAP_STYLE,
  SATELLITE_BASEMAP_STYLE,
  DEFAULT_FREQ_MHZ,
  DEFAULT_SF,
  DEFAULT_TX_POWER_DBM,
  INITIAL_CENTER,
  INITIAL_ZOOM,
  MINSF_BAND_COLORS,
  MINSF_FILL_OPACITY,
  RSSI_FILL_OPACITY,
  PREDICT_MARKER_STYLE,
  STATUS_COLOR,
  STATUS_COLOR_FALLBACK,
  SURVEY_CIRCLE_PAINT,
} from "./CoverageMap.config.js";
import { ESTIMATE_RSSI_BAND_COLORS, colorForRssi } from "./legend.js";
import {
  addSurveyHeatmapLayer,
  setSurveyHeatmapVisible,
} from "./SurveyHeatmapLayer.js";

const t = strings.coverageMap;
/** @type {Record<string, string>} */
const STATUS_LABEL = strings.coverageStatus;

/**
 * Convert survey items → GeoJSON FeatureCollection cho circle layer.
 * Properties giữ tối thiểu cần cho popup; geometry là Point [lng, lat].
 *
 * @param {ReadonlyArray<import("../api/client.js").SurveyTrainingPointT>} items
 * @returns {GeoJSON.FeatureCollection<GeoJSON.Point>}
 */
function buildSurveyGeoJson(items) {
  return {
    type: "FeatureCollection",
    features: items.map((p) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [p.longitude ?? 0, p.latitude ?? 0] },
      properties: {
        rssi_dbm: p.rssi_dbm,
        snr_db: p.snr_db,
        spreading_factor: p.spreading_factor,
        device_id: p.device_id ?? "",
        frequency_mhz: p.frequency_mhz,
        timestamp: p.timestamp,
        code_rate: p.code_rate ?? "",
      },
    })),
  };
}

/**
 * Build FeatureCollection<LineString> nối mỗi điểm đo → gateway serving.
 * Bỏ qua point không có serving_gateway_id, hoặc gateway chưa load
 * (race khi gateways query chưa xong).
 *
 * @param {ReadonlyArray<import("../api/client.js").SurveyTrainingPointT>} items
 * @param {ReadonlyArray<import("../api/client.js").GatewayT>} gateways
 * @returns {GeoJSON.FeatureCollection<GeoJSON.LineString>}
 */
function buildSurveyConnectionLinesGeoJson(items, gateways) {
  const gwById = new Map(gateways.map((g) => [g.id, g]));
  /** @type {GeoJSON.Feature<GeoJSON.LineString>[]} */
  const features = [];
  for (const p of items) {
    if (!p.serving_gateway_id) continue;
    const gw = gwById.get(p.serving_gateway_id);
    if (!gw) continue;
    features.push({
      type: "Feature",
      geometry: {
        type: "LineString",
        coordinates: [
          [p.longitude, p.latitude],
          [gw.longitude, gw.latitude],
        ],
      },
      properties: {},
    });
  }
  return { type: "FeatureCollection", features };
}

/**
 * Format ISO timestamp → "HH:mm:ss dd/mm/yy" theo local time. Trả "" nếu parse fail.
 * @param {string} iso
 * @returns {string}
 */
function formatSurveyTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n) => String(n).padStart(2, "0");
  const hh = pad(d.getHours());
  const mm = pad(d.getMinutes());
  const ss = pad(d.getSeconds());
  const dd = pad(d.getDate());
  const mo = pad(d.getMonth() + 1);
  const yy = pad(d.getFullYear() % 100);
  return `${hh}:${mm}:${ss} ${dd}/${mo}/${yy}`;
}

/**
 * Khoảng cách haversine (mét) giữa 2 toạ độ WGS84. Đủ chính xác cho khoảng
 * vài km — sai số <0.5% vs ellipsoidal.
 * @param {number} lat1 @param {number} lon1 @param {number} lat2 @param {number} lon2
 */
function haversineMeters(lat1, lon1, lat2, lon2) {
  const R = 6371000;
  const toRad = (d) => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

/**
 * Escape HTML để inject vào popup an toàn (device_id là user-input).
 * @param {string} s
 */
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => {
    switch (c) {
      case "&":
        return "&amp;";
      case "<":
        return "&lt;";
      case ">":
        return "&gt;";
      case '"':
        return "&quot;";
      default:
        return "&#39;";
    }
  });
}

/**
 * @returns {{ lat: number, lng: number } | null}
 */
function readUrlState() {
  if (typeof window === "undefined") return null;
  const p = new URLSearchParams(window.location.search);
  const latStr = p.get("lat");
  const lngStr = p.get("lng");
  if (latStr == null || lngStr == null) return null;
  const lat = Number(latStr);
  const lng = Number(lngStr);
  if (!Number.isFinite(lat) || lat < -90 || lat > 90) return null;
  if (!Number.isFinite(lng) || lng < -180 || lng > 180) return null;
  return { lat, lng };
}

/**
 * @param {number} lat
 * @param {number} lng
 */
function writeUrlState(lat, lng) {
  if (typeof window === "undefined") return;
  const p = new URLSearchParams(window.location.search);
  p.set("lat", lat.toFixed(6));
  p.set("lng", lng.toFixed(6));
  p.delete("sf");
  const next = `${window.location.pathname}?${p.toString()}${window.location.hash}`;
  window.history.replaceState(null, "", next);
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * @typedef {{
 *   sfList: number[],
 *   deviceId: string | null,
 *   rssiRange: { min: number | null, max: number | null },
 *   snrRange: { min: number | null, max: number | null },
 *   timeRange: { from: string | null, to: string | null },
 * }} PointsFilterState
 */

/** @returns {PointsFilterState} */
function readPointsFilterUrlState() {
  /** @type {PointsFilterState} */
  const def = {
    sfList: [],
    deviceId: null,
    rssiRange: { min: null, max: null },
    snrRange: { min: null, max: null },
    timeRange: { from: null, to: null },
  };
  if (typeof window === "undefined") return def;
  const p = new URLSearchParams(window.location.search);

  const sfRaw = p.get("sf_list");
  if (sfRaw) {
    const parsed = sfRaw
      .split(",")
      .map((x) => Number(x.trim()))
      .filter((n) => Number.isInteger(n) && n >= 7 && n <= 12);
    def.sfList = [...new Set(parsed)].sort((a, b) => a - b);
  }

  const dev = p.get("device_id");
  if (dev) def.deviceId = dev.slice(0, 64);

  /** @param {string} key @returns {number | null} */
  const numOrNull = (key) => {
    const v = p.get(key);
    if (v == null || v === "") return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  };
  def.rssiRange = { min: numOrNull("rssi_min"), max: numOrNull("rssi_max") };
  def.snrRange = { min: numOrNull("snr_min"), max: numOrNull("snr_max") };

  const tf = p.get("time_from");
  const tt = p.get("time_to");
  def.timeRange = { from: tf, to: tt };

  return def;
}

/** @param {PointsFilterState} state */
function writePointsFilterUrlState(state) {
  if (typeof window === "undefined") return;
  const p = new URLSearchParams(window.location.search);

  if (state.sfList.length > 0) p.set("sf_list", state.sfList.join(","));
  else p.delete("sf_list");

  if (state.deviceId) p.set("device_id", state.deviceId);
  else p.delete("device_id");

  /** @param {string} key @param {number | null} v */
  const setNum = (key, v) => {
    if (v == null) p.delete(key);
    else p.set(key, String(v));
  };
  setNum("rssi_min", state.rssiRange.min);
  setNum("rssi_max", state.rssiRange.max);
  setNum("snr_min", state.snrRange.min);
  setNum("snr_max", state.snrRange.max);

  if (state.timeRange.from) p.set("time_from", state.timeRange.from);
  else p.delete("time_from");
  if (state.timeRange.to) p.set("time_to", state.timeRange.to);
  else p.delete("time_to");

  // Clean URL legacy keys (sort + rank window đã gỡ khỏi UI).
  p.delete("sort_by");
  p.delete("sort_order");
  p.delete("rank_from");
  p.delete("rank_to");

  const qs = p.toString();
  const next = `${window.location.pathname}${qs ? "?" + qs : ""}${window.location.hash}`;
  window.history.replaceState(null, "", next);
}

/**
 * @returns {{
 *   contributor: import("../api/client.js").ContributorMode,
 *   linkedSourceId: string | null,
 *   source: string | null,
 * }}
 */
function readFilterUrlState() {
  /** @type {import("../api/client.js").ContributorMode} */
  let contributor = "community";
  /** @type {string | null} */
  let linkedSourceId = null;
  /** @type {string | null} */
  let source = null;
  if (typeof window === "undefined") return { contributor, linkedSourceId, source };

  const p = new URLSearchParams(window.location.search);
  const c = p.get("contributor");
  if (c === "me" || c === "community") {
    contributor = c;
  } else if (c?.startsWith("user/")) {
    const uuid = c.slice(5);
    if (UUID_RE.test(uuid)) contributor = /** @type {const} */ (`user/${uuid}`);
  }

  const ls = p.get("linked_source");
  if (ls && UUID_RE.test(ls)) linkedSourceId = ls;

  const s = p.get("source");
  if (s) source = s;

  return { contributor, linkedSourceId, source };
}

/**
 * @param {{
 *   contributor: import("../api/client.js").ContributorMode,
 *   linkedSourceId: string | null,
 *   source: string | null,
 * }} state
 */
function writeFilterUrlState(state) {
  if (typeof window === "undefined") return;
  const p = new URLSearchParams(window.location.search);
  // contributor=community là default → bỏ param cho URL gọn.
  if (state.contributor === "community") p.delete("contributor");
  else p.set("contributor", state.contributor);

  if (state.linkedSourceId) p.set("linked_source", state.linkedSourceId);
  else p.delete("linked_source");

  if (state.source) p.set("source", state.source);
  else p.delete("source");

  const qs = p.toString();
  const next = `${window.location.pathname}${qs ? "?" + qs : ""}${window.location.hash}`;
  window.history.replaceState(null, "", next);
}

// Survey GeoJSON source — chia sẻ giữa 2 layer (circle + heatmap), không
// cluster. Toggle visibility ở runtime thay vì add/remove → cùng filter, cùng
// pipeline cập nhật setData.
//
// Heatmap layer + paint encapsulated trong `./SurveyHeatmapLayer.js`. Caller
// chỉ thấy 2 hàm `addSurveyHeatmapLayer` / `setSurveyHeatmapVisible`.
const SURVEYS_SOURCE_ID = "surveys-src";
const SURVEYS_LAYER_ID = "surveys-circle";

// Đường nét đứt nối điểm đo → serving gateway (toggle "Hiện kết nối điểm
// đo-gateway" trong filter panel). 1 source + 1 line layer, setData khi
// displayedItems hoặc gateways đổi. Chỉ vẽ feature cho point có
// serving_gateway_id match với gateway đã load.
const SURVEY_CONNECTION_LINES_SOURCE_ID = "survey-connection-lines-src";
const SURVEY_CONNECTION_LINES_LAYER_ID = "survey-connection-lines";

// ViewMode cho tab "Bản đồ điểm đo" — toggle circle/heatmap mật độ. Định
// nghĩa local vì MapViewModeToggle hiện nhận `string` chung (xài cho cả
// tab "Bản đồ phủ sóng" với value khác: minsf/estimate).
/** @typedef {"points" | "heatmap"} ViewMode */

// Predict-line GeoJSON source — line layer nối điểm dự đoán → serving gateway.
// 1 source duy nhất cho cả tab "Dự đoán điểm": mỗi lần predict push 1 feature,
// `clearAllSearchMarkers` reset features = []. Màu line đọc từ feature property
// `color` (set runtime từ STATUS_COLOR theo coverage_status).
const PREDICT_LINES_SOURCE_ID = "predict-lines-src";
const PREDICT_LINES_LAYER_ID = "predict-lines";

// Min-SF coverage layer (tab "Bản đồ phủ sóng" + viewMode "minsf"). 1 source
// + 1 fill layer; setData khi user đổi gateway. Polygon nested SF12⊃...⊃SF7
// đã sort outermost-first ở precompute script → render đúng order tự nhiên.
const MINSF_SOURCE_ID = "minsf-src";
const MINSF_FILL_LAYER_ID = "minsf-fill";
const MINSF_OUTLINE_LAYER_ID = "minsf-outline";

// Composite RSSI heatmap (viewMode "estimate"). Fetch 1 lần khi switch sang
// estimate; cached trong source data cho lần switch sau.
const RSSI_COMPOSITE_SOURCE_ID = "rssi-composite-src";
const RSSI_COMPOSITE_FILL_LAYER_ID = "rssi-composite-fill";

// Satellite overlay — chỉ visible khi coverageViewMode === "minsf" (đối
// chiếu band SF với buildings/đường). Estimate view dùng basemap CARTO
// sạch (composite RSSI cell trông rõ hơn).
const SATELLITE_OVERLAY_SOURCE_ID = "satellite-overlay-src";
const SATELLITE_OVERLAY_LAYER_ID = "satellite-overlay";

/* ─────────────────────────────────────────────────────────────────────────
 * Popup vanilla-DOM helpers (predict marker)
 *
 * Maplibre popup nhận DOM node thuần — không phải React tree — nên các block
 * UI bidirectional viết trực tiếp bằng `document.createElement`. Tách ra
 * module-level để buildPopupNode đọc được, đồng thời tránh re-create function
 * mỗi render.
 * ─────────────────────────────────────────────────────────────────────── */

/**
 * BER scientific format: 1e-X → "≈ 10⁻ˣ"
 * @param {number} ber
 */
function formatBer(ber) {
  if (ber <= 0) return "≈ 0";
  const exp = Math.round(Math.log10(ber));
  return `≈ 10${toSuperscript(exp)}`;
}

/** @type {Record<string, string>} */
const SUPERSCRIPT_MAP = {
  "-": "⁻", "0": "⁰", "1": "¹", "2": "²", "3": "³",
  "4": "⁴", "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹",
};

/** @param {number} n */
function toSuperscript(n) {
  return String(n).split("").map((c) => SUPERSCRIPT_MAP[c] ?? c).join("");
}

/**
 * Ô field trong grid 11 mục: label nhỏ-xám, value bold, sub-text tùy chọn.
 * @param {string} label
 * @param {string} value
 * @param {string} [sub]
 * @returns {HTMLDivElement}
 */
function buildFieldCell(label, value, sub) {
  const cell = document.createElement("div");
  cell.style.cssText = "min-width:0";
  const dt = document.createElement("div");
  dt.style.cssText = "color:#64748b;font-size:10px;line-height:1.3";
  dt.textContent = label;
  cell.appendChild(dt);
  const dd = document.createElement("div");
  dd.style.cssText =
    "color:#0f172a;font-weight:600;font-size:11px;margin-top:1px;word-break:break-word;font-variant-numeric:tabular-nums";
  dd.textContent = value;
  cell.appendChild(dd);
  if (sub) {
    const subEl = document.createElement("div");
    subEl.style.cssText = "color:#94a3b8;font-size:10px;line-height:1.25;margin-top:1px";
    subEl.textContent = sub;
    cell.appendChild(subEl);
  }
  return cell;
}

/**
 * Nút copy permalink (`?lat=&lng=`) — feedback "Đã copy!" 2s rồi reset.
 * Clipboard API không có ở SSR → guard `window` tồn tại.
 * @param {HTMLElement} parent
 * @param {number} lat
 * @param {number} lng
 */
function appendCopyLinkButton(parent, lat, lng) {
  if (typeof window === "undefined") return;
  const btn = document.createElement("button");
  btn.type = "button";
  btn.style.cssText =
    "margin-top:8px;font-size:11px;color:#0369a1;background:#f0f9ff;border:1px solid #bae6fd;border-radius:4px;padding:3px 8px;cursor:pointer";
  btn.textContent = t.popup.copyLink.label;

  let resetTimer = /** @type {number | null} */ (null);
  btn.addEventListener("click", () => {
    const url = new URL(window.location.href);
    url.searchParams.set("lat", lat.toFixed(6));
    url.searchParams.set("lng", lng.toFixed(6));
    url.searchParams.delete("sf");
    void navigator.clipboard.writeText(url.toString()).then(() => {
      btn.textContent = t.popup.copyLink.done;
      if (resetTimer != null) window.clearTimeout(resetTimer);
      resetTimer = window.setTimeout(() => {
        btn.textContent = t.popup.copyLink.label;
        resetTimer = null;
      }, 2000);
    });
  });

  parent.appendChild(btn);
}

// Realtime "Theo dõi trực tiếp" — chu kỳ polling backend khi bật mode.
// Tham chiếu duy nhất trong file để tránh magic number rải rác.
const REALTIME_POLL_MS = 3000;
// Sau khoảng này không thấy gói tin mới → tự tắt toggle (user quên tắt khi
// rời site đo). Reset timer mỗi lần lastSeenAt advance.
const REALTIME_IDLE_AUTO_OFF_MS = 15 * 60 * 1000;
// Tick re-render badge "Mới nhất: Ns trước" — counter chạy độc lập với
// polling interval (poll 3s nhưng UI tick 5s là vừa mắt, đỡ jitter).
const REALTIME_BADGE_TICK_MS = 5000;
// Khi auto-pan tới điểm mới, zoom tối thiểu để user thấy chi tiết đường đi.
// Giữ zoom cao hơn nếu user đang zoom xa hơn (max → preserve user intent).
const REALTIME_AUTO_FOLLOW_MIN_ZOOM = 15;
// Chu kỳ pull external source vào DB cho live session (mig 0031). Chậm hơn
// REALTIME_POLL_MS — sync ChirpStack/LPWANMapper tốn round-trip, không cần
// fan-out 1s/lần; 20s đủ "gần realtime" cho UX khảo sát mà không nghẽn upstream.
const LIVE_SESSION_SYNC_MS = 20000;
// Reference ổn định cho displayedItems khi chưa có data — tránh `?? []` tạo
// array mới mỗi render gây useEffect deps re-fire.
const EMPTY_TRAINING_ITEMS = Object.freeze(/** @type {never[]} */ ([]));

/**
 * @param {number | null} lastSeenAt epoch ms
 * @param {number} now epoch ms
 * @param {typeof strings.coverageMap.filters.realtime} t
 * @returns {string}
 */
function formatLastSeenLabel(lastSeenAt, now, t) {
  if (lastSeenAt === null) return t.lastSeenNever;
  const diffSec = Math.max(0, Math.floor((now - lastSeenAt) / 1000));
  if (diffSec < 60) return t.lastSeenSecondsAgo(diffSec);
  return t.lastSeenMinutesAgo(Math.floor(diffSec / 60));
}


/**
 * @param {{
 *   mode?: "points" | "heatmap" | "predict",
 * }} props
 *   mode === "points": render survey points (mặc định, tab "Bản đồ điểm đo").
 *     Click bản đồ → auto-predict 1 điểm + vẽ marker.
 *   mode === "heatmap": survey layer tắt — placeholder cho heatmap raster
 *     (Phase 2 sẽ thêm raster source khi tile endpoint sẵn sàng).
 *   mode === "predict": survey layer tắt — chỉ hiển thị gateway. Sub-tab
 *     "1 điểm": click bản đồ chọn toạ độ + Dự đoán. Sub-tab "Hàng loạt":
 *     upload CSV/JSON, submit → vẽ markers tự động + mở drawer kết quả.
 */
/**
 * @param {{
 *   mode?: "points" | "heatmap" | "predict",
 *   onRequestLogin?: (afterLogin?: () => void) => void,
 * }} props
 */
export function CoverageMap({ mode = "points", onRequestLogin }) {
  const containerRef = useRef(/** @type {HTMLDivElement | null} */ (null));
  const mapRef = useRef(/** @type {maplibregl.Map | null} */ (null));
  const [mapLoaded, setMapLoaded] = useState(false);
  const gatewayMarkersRef = useRef(/** @type {maplibregl.Marker[]} */ ([]));
  // Mảng marker dự đoán — predict mỗi điểm append 1 marker, không xoá cũ.
  // Re-render qua bumpMarkerCount() để nút "Xoá tất cả" disable đúng lúc.
  const searchMarkersRef = useRef(/** @type {maplibregl.Marker[]} */ ([]));
  // Pin tạm (1 dot xám) — đánh dấu vị trí user vừa pick (map click hoặc address
  // resolve) TRƯỚC khi bấm "Dự đoán". Hidden sau khi predict thành công (marker
  // kết quả màu thay vào) hoặc khi user "Xoá tất cả".
  const pickMarkerRef = useRef(/** @type {maplibregl.Marker | null} */ (null));
  // Line features song song với searchMarkersRef — index N có thể không 1-1 vì
  // marker mà serving_gateway_id == null sẽ không có line. clearAll reset cả 2.
  const searchLineFeaturesRef = useRef(
    /** @type {GeoJSON.Feature<GeoJSON.LineString>[]} */ ([]),
  );
  const [predictMarkerCount, setPredictMarkerCount] = useState(0);
  const gatewaysRef = useRef(
    /** @type {import("../api/client.js").GatewayT[]} */ ([]),
  );
  // Snapshot displayedItems để click-handler (đăng ký 1 lần lúc map-load)
  // đọc được sibling rows: 1 packet → N row trong survey_training (1/gateway),
  // group lại để popup show "Gateway kết nối" list.
  const displayedItemsRef = useRef(
    /** @type {ReadonlyArray<import("../api/client.js").SurveyTrainingPointT>} */ ([]),
  );
  // Cache reverse-geocode kết quả theo gateway code để tránh gọi lại Nominatim
  // mỗi lần user mở lại popup. Giá trị "" = đang tải, null = lỗi (đã fetch).
  const gatewayAddressCacheRef = useRef(
    /** @type {Map<string, string | null>} */ (new Map()),
  );
  // Đảm bảo URL deep-link predict chỉ chạy 1 lần / mount.
  const deepLinkConsumedRef = useRef(false);
  const initialUrlRef = useRef(readUrlState());
  const initialFilterRef = useRef(readFilterUrlState());
  const initialPointsFilterRef = useRef(readPointsFilterUrlState());

  const user = useSyncExternalStore(subscribeAuth, getUser);

  const [tileError, setTileError] = useState(/** @type {string | null} */ (null));
  const [pickedCoords, setPickedCoords] = useState(
    /** @type {{ lat: number, lng: number } | null} */ (null),
  );
  const [predictBusy, setPredictBusy] = useState(false);
  const [predictError, setPredictError] = useState(
    /** @type {string | null} */ (null),
  );
  // Geolocation API: nút "Dùng vị trí của tôi" trong sub-tab single.
  // getCurrentPosition async ~vài giây với enableHighAccuracy → spinner.
  const [gpsBusy, setGpsBusy] = useState(false);
  const [gpsError, setGpsError] = useState(
    /** @type {string | null} */ (null),
  );
  // Collapse pattern khớp với PointsFilterPanel / MinSFPanel / EstimatePanel:
  // default closed (1 icon button) để không che map. Reset về closed khi user
  // rời tab predict — tránh ghost-state hiện ra ở lần re-enter sau.
  const [predictPanelOpen, setPredictPanelOpen] = useState(false);
  // Tab "Bản đồ điểm đo": 2 panel độc lập (filter + theo dõi trực tiếp). State
  // lift lên đây để icon column ở left luôn cố định — mở 1 panel không push
  // icon của panel còn lại xuống dưới.
  const [pointsFilterOpen, setPointsFilterOpen] = useState(false);
  const [realtimePanelOpen, setRealtimePanelOpen] = useState(false);
  // Sub-tab trong Predict panel: "single" (click 1 điểm) hoặc "address" (nhập địa chỉ → geocode).
  // Cả 2 sub-tab cho mọi user (kể cả admin) — chỉ khác cách lấy lat/lng,
  // cùng vẽ marker qua drawSearchMarker.
  const [predictSubTab, setPredictSubTab] = useState(
    /** @type {"single" | "address"} */ ("single"),
  );
  // Default outdoor — thay đổi sẽ apply ITU-R P.2109 building entry loss BE-side.
  const [environment, setEnvironment] = useState(
    /** @type {"outdoor" | "indoor"} */ ("outdoor"),
  );
  // Visualization mode cho tab "points": circle (RSSI) ↔ heatmap (mật độ).
  // Mặc định circle để không đổi behavior hiện tại. State chỉ ý nghĩa khi
  // mode === "points"; các tab khác không render toggle nên giá trị bị bỏ qua.
  const [viewMode, setViewMode] = useState(
    /** @type {ViewMode} */ ("points"),
  );
  // Toggle "Hiện kết nối điểm đo-gateway" — vẽ đường nét đứt từ mỗi điểm
  // đo đến gateway đã thu được. Chỉ ý nghĩa khi mode === "points".
  const [showConnectionLines, setShowConnectionLines] = useState(false);

  // Tab "Bản đồ phủ sóng" (mode === "heatmap") có 2 layer toggle độc lập với
  // viewMode points/heatmap. "estimate" là composite RSSI heatmap (default —
  // hiển thị toàn cảnh phủ sóng cộng dồn 13 gateway); "minsf" cần user chọn
  // gateway nên kém trực quan cho lần đầu vào tab.
  const [coverageViewMode] = useState(
    /** @type {"minsf" | "estimate"} */ ("estimate"),
  );
  // Code gateway đang được chọn để hiển thị min-SF overlay (null = không chọn).
  // Dùng `code` thay `id` vì precompute script ghi GeoJSON theo code (`{code}.geojson`).
  // Tạm ẩn UI minsf → setter không reachable; giữ value để các useEffect layer
  // visibility vẫn type-safe (always null, layer luôn hidden).
  const [minsfGatewayCode] = useState(/** @type {string | null} */ (null));
  const [, setMinsfLoadError] = useState(/** @type {string | null} */ (null));
  // Composite RSSI heatmap (viewMode "estimate"): load error state. Fetch
  // GeoJSON khi vào estimate mode lần đầu hoặc khi gateway picker đổi giá trị.
  // estimateLoadedRef cache theo "key": "composite" cho all-gw, code cho per-gw
  // — switch lại key đã load thì skip re-fetch.
  const [estimateLoadError, setEstimateLoadError] = useState(
    /** @type {string | null} */ (null),
  );
  const estimateLoadedRef = useRef(/** @type {string | null} */ (null));
  // null = "Tất cả gateway" (load composite.geojson). Khác null = load
  // per_gw/{code}.geojson.
  const [estimateGatewayCode, setEstimateGatewayCode] = useState(
    /** @type {string | null} */ (null),
  );

  const [contributor, setContributor] = useState(
    () => initialFilterRef.current.contributor,
  );
  const [linkedSourceId, setLinkedSourceId] = useState(
    () => initialFilterRef.current.linkedSourceId,
  );
  const [sourceType, setSourceType] = useState(
    () => initialFilterRef.current.source,
  );

  // Points-tab filters — chỉ active khi mode === "points". State giữ ngay cả
  // khi tab khác (component instance riêng per-mode nên thực tế reset, nhưng
  // logic an toàn nếu sau này share instance).
  const [sfList, setSfList] = useState(
    () => initialPointsFilterRef.current.sfList,
  );
  const [deviceId, setDeviceId] = useState(
    () => initialPointsFilterRef.current.deviceId,
  );
  const [rssiRange, setRssiRange] = useState(
    () => initialPointsFilterRef.current.rssiRange,
  );
  const [snrRange, setSnrRange] = useState(
    () => initialPointsFilterRef.current.snrRange,
  );
  const [timeRange, setTimeRange] = useState(
    () => initialPointsFilterRef.current.timeRange,
  );

  // Realtime "Theo dõi trực tiếp" — chỉ active khi contributor === "me".
  // `lastPointTimestampRef` = cursor cho param `since`; advance = max(timestamp)
  // sau mỗi response. `sessionCounterRef` ref vì cập nhật tần suất cao nhưng
  // chỉ cần render qua badge (lastSeenAt state đã trigger re-render).
  // `realtimeFeatures` accumulator: snapshot lần đầu + append incremental.
  const [realtimeEnabled, setRealtimeEnabled] = useState(false);
  const [autoFollowEnabled, setAutoFollowEnabled] = useState(true);
  // Khi bật, displayedItems chỉ giữ điểm có timestamp >= sessionStartedAtRef
  // (mốc lúc tick toggle realtime) — ẩn snapshot lịch sử khỏi map.
  const [liveOnlyEnabled, setLiveOnlyEnabled] = useState(false);
  const lastPointTimestampRef = useRef(/** @type {string | null} */ (null));
  const sessionCounterRef = useRef(0);
  // Mốc client time (epoch ms) khi user tick toggle realtime. Dùng cho
  // liveOnly filter — so với p.timestamp parse ISO. Reset cùng cursor.
  const sessionStartedAtRef = useRef(/** @type {number | null} */ (null));
  const [lastSeenAt, setLastSeenAt] = useState(
    /** @type {number | null} */ (null),
  );
  const [realtimeFeatures, setRealtimeFeatures] = useState(
    /** @type {import("../api/client.js").SurveyTrainingPointT[]} */ ([]),
  );
  // Tick để badge "Mới nhất: Ns trước" tự re-render dù không có điểm mới.
  const [nowTick, setNowTick] = useState(() => Date.now());
  // Nút Kết thúc → final sync + summary modal. State busy + modal result.
  const [endingBusy, setEndingBusy] = useState(false);
  const [endModal, setEndModal] = useState(
    /** @type {{ title: string, body: string } | null} */ (null),
  );
  // Live session (mig 0031): 1 chuyến = 1 batch. Ref vì sync interval đọc
  // trong closure ổn định; cumulative counter cho tổng kết Kết thúc.
  // `liveSessionSourceId` là source RIÊNG cho live session (nơi GHI data),
  // không liên quan tới `linkedSourceId` filter (chỉ điều khiển XEM data).
  // Tách hẳn 2 state để user có thể đang lọc "Tất cả nguồn" mà vẫn ghi
  // chuyến vào 1 source cụ thể, hoặc đang xem 1 source này nhưng ghi vào
  // source khác.
  const [liveSessionSourceId, setLiveSessionSourceId] = useState(
    /** @type {string | null} */ (null),
  );
  // Tách "bật realtime" (xem điểm mới) khỏi "chuyến khảo sát" (1 batch).
  // Batch chỉ tạo khi user nhấn "Bắt đầu" → đảm bảo batch = data từ Start
  // tới End, không gồm điểm trước khi user explicit start.
  const [liveSessionRunning, setLiveSessionRunning] = useState(false);
  const liveSessionBatchIdRef = useRef(/** @type {string | null} */ (null));
  const liveSessionInsertedRef = useRef(0);

  // Logout / token expire khi đang ở mode "me" hoặc "user/..." → fallback
  // về "community" (backend sẽ trả 401 nếu giữ "me" mà không có token, gây
  // toàn bộ map empty + error toast).
  useEffect(() => {
    if (!user) {
      if (contributor !== "community") {
        setContributor("community");
        setLinkedSourceId(null);
        setDeviceId(null);
      }
      // SourceTypeFilter ẩn khi logged-out → reset state để không apply filter
      // ngầm không thấy được trên UI.
      if (sourceType !== null) setSourceType(null);
    }
  }, [user, contributor, sourceType]);

  // Sync URL mỗi khi filter đổi.
  useEffect(() => {
    writeFilterUrlState({
      contributor,
      linkedSourceId: contributor === "me" ? linkedSourceId : null,
      source: sourceType,
    });
  }, [contributor, linkedSourceId, sourceType]);

  // Points-tab filter URL sync — tách riêng để không đụng URL keys khi user
  // ở tab khác (mode !== "points" thì state vẫn là default → write no-op).
  useEffect(() => {
    if (mode !== "points") return;
    writePointsFilterUrlState({
      sfList,
      deviceId,
      rssiRange,
      snrRange,
      timeRange,
    });
  }, [mode, sfList, deviceId, rssiRange, snrRange, timeRange]);

  // Filter pipeline: backend nhận contributor/linked_source/source +
  // (sf_list, device_id, rssi/snr/time range, sort + rank window) và AND
  // tất cả. Window rank thay thế `limit` cũ — RankFilter clamp ≤ 5000.
  const linkedSourceForQuery = contributor === "me" ? linkedSourceId : null;
  const deviceIdForQuery = contributor === "me" ? deviceId : null;

  // Gateway là hạ tầng chung — luôn dùng community bất kể filter. Trước đây
  // "Bản đồ của tôi" filter gateway theo survey của user nhưng CSV upload
  // chưa đóng góp nằm ở quarantine → query gateway INNER JOIN training trượt
  // → không hiện gateway nào. Gateway list không phụ thuộc data ownership.
  const gatewaysQ = useQuery({
    queryKey: ["gateways", "community"],
    queryFn: () => listGateways(undefined, { contributor: "community" }),
    retry: 3,
  });

  const surveysQ = useQuery({
    queryKey: [
      "surveys",
      contributor,
      linkedSourceForQuery,
      deviceIdForQuery,
      sourceType,
      sfList,
      rssiRange,
      snrRange,
      timeRange,
      // Tách cache realtime ↔ static — query realtime gửi kèm `since` cursor
      // không nên pollute snapshot mà tab khác / lần switch off đọc lại.
      realtimeEnabled,
    ],
    queryFn: () => {
      // Realtime: cursor null lần đầu (snapshot toàn bộ) → set từ effect
      // merge bên dưới. Static (realtimeEnabled = false): không gửi since.
      const since = realtimeEnabled
        ? lastPointTimestampRef.current ?? undefined
        : undefined;
      return listSurveyTraining(undefined, {
        contributor,
        linkedSourceId: linkedSourceForQuery ?? undefined,
        deviceId: deviceIdForQuery ?? undefined,
        source: sourceType ?? undefined,
        sfList: sfList.length > 0 ? sfList : undefined,
        rssiMin: rssiRange.min ?? undefined,
        rssiMax: rssiRange.max ?? undefined,
        snrMin: snrRange.min ?? undefined,
        snrMax: snrRange.max ?? undefined,
        timeFrom: timeRange.from ?? undefined,
        timeTo: timeRange.to ?? undefined,
        since,
      });
    },
    enabled: mode === "points",
    // contributor !== community gặp 401/403 không nên retry tự động —
    // user thấy panel error 1 lần đỡ spam request.
    retry: contributor === "community" ? 3 : false,
    // refetchIntervalInBackground mặc định false → tab ẩn tự pause polling.
    refetchInterval:
      realtimeEnabled && contributor === "me" ? REALTIME_POLL_MS : false,
  });

  // Reset realtime khi rời khỏi mode "me" hoặc logout — toggle realtime chỉ
  // có ý nghĩa với data của chính chủ. Cleanup cursor + counter + features
  // để lần bật lại snapshot từ đầu.
  useEffect(() => {
    if (contributor === "me" && user) return;
    setRealtimeEnabled(false);
    setRealtimeFeatures([]);
    setLastSeenAt(null);
    setLiveSessionSourceId(null);
    lastPointTimestampRef.current = null;
    sessionCounterRef.current = 0;
  }, [contributor, user]);

  // Reset cursor + accumulator khi filter đổi giữa chừng realtime — kết quả
  // mới khác hẳn, không thể incremental từ cursor cũ. Cũng fire khi bật/tắt
  // realtime để lần snapshot mới luôn full-fetch. sessionStartedAt = mốc
  // cho liveOnly filter; advance mỗi lần "session" reset.
  useEffect(() => {
    if (!realtimeEnabled) return;
    lastPointTimestampRef.current = null;
    sessionCounterRef.current = 0;
    sessionStartedAtRef.current = Date.now();
    liveSessionInsertedRef.current = 0;
    setRealtimeFeatures([]);
  }, [
    realtimeEnabled,
    contributor,
    linkedSourceForQuery,
    deviceIdForQuery,
    sourceType,
    sfList,
    rssiRange,
    snrRange,
    timeRange,
  ]);

  // Live session lifecycle (mig 0031): khi user tick "Theo dõi trực tiếp" +
  // chọn nguồn ghi (liveSessionSourceId) → tạo batch kind='live_session' để
  // gom mọi sync trong chuyến vào 1 row "Lịch sử upload". Mỗi chu kỳ
  // LIVE_SESSION_SYNC_MS pull upstream → batch.points_count cộng dồn. Cleanup
  // khi tắt realtime / đổi source / unmount: clear interval; batch row còn
  // lại để handleEndSession xử lý (success → giữ, empty → DELETE).
  //
  // liveSessionSourceId TÁCH HẲN khỏi linkedSourceId filter: filter điều
  // khiển XEM data nào trên map, picker này điều khiển GHI vào source nào.
  useEffect(() => {
    if (!realtimeEnabled) return;
    if (contributor !== "me") return;
    if (liveSessionSourceId === null) return;
    if (!liveSessionRunning) return;

    let cancelled = false;
    let intervalId = /** @type {ReturnType<typeof setInterval> | null} */ (null);

    (async () => {
      try {
        const res = await startLiveSession(liveSessionSourceId);
        if (cancelled) return;
        liveSessionBatchIdRef.current = res.batch_id;
        intervalId = setInterval(async () => {
          const batchId = liveSessionBatchIdRef.current;
          if (batchId === null) return;
          try {
            const r = await syncLiveSession(batchId);
            if (!r.error) {
              liveSessionInsertedRef.current += r.measurements_inserted;
            }
          } catch {
            // Bỏ qua lỗi interval — handleEndSession sẽ surface qua final sync.
          }
        }, LIVE_SESSION_SYNC_MS);
      } catch {
        // Start fail (404 source không tồn tại / mất mạng) → user vẫn xem
        // map; bấm Kết thúc sẽ báo NeedSource modal.
        liveSessionBatchIdRef.current = null;
      }
    })();

    return () => {
      cancelled = true;
      if (intervalId !== null) clearInterval(intervalId);
    };
  }, [realtimeEnabled, contributor, liveSessionSourceId, liveSessionRunning]);

  // Merge incremental result: snapshot lần đầu (cursor null) hoặc append
  // điểm mới với dedup theo (timestamp + device_id + serving_gateway_id).
  // Advance cursor = max(timestamp) — server-time, không đụng clock skew.
  useEffect(() => {
    if (!realtimeEnabled) return;
    if (!surveysQ.data) return;
    const items = surveysQ.data.items;
    if (lastPointTimestampRef.current === null) {
      setRealtimeFeatures(items);
      sessionCounterRef.current = 0;
    } else if (items.length > 0) {
      setRealtimeFeatures((prev) => {
        const seen = new Set(
          prev.map(
            (p) =>
              `${p.timestamp}|${p.device_id ?? ""}|${p.serving_gateway_id ?? ""}`,
          ),
        );
        const fresh = items.filter(
          (p) =>
            !seen.has(
              `${p.timestamp}|${p.device_id ?? ""}|${p.serving_gateway_id ?? ""}`,
            ),
        );
        sessionCounterRef.current += fresh.length;
        return fresh.length > 0 ? [...prev, ...fresh] : prev;
      });
    }
    if (items.length > 0) {
      const maxTs = items.reduce(
        (m, p) => (p.timestamp > m ? p.timestamp : m),
        items[0].timestamp,
      );
      lastPointTimestampRef.current = maxTs;
      setLastSeenAt(Date.now());
    }
  }, [surveysQ.data, realtimeEnabled]);

  // Idle timer — sau 15 phút không có điểm mới → tự tắt toggle. Reset mỗi
  // khi lastSeenAt advance (dep đổi → effect re-run → setTimeout mới).
  useEffect(() => {
    if (!realtimeEnabled) return;
    const timer = setTimeout(() => {
      setRealtimeEnabled(false);
    }, REALTIME_IDLE_AUTO_OFF_MS);
    return () => clearTimeout(timer);
  }, [realtimeEnabled, lastSeenAt]);

  // Realtime OFF → reset live session picker. Batch row đã tạo (nếu có) còn
  // trong "Lịch sử upload" với count hiện tại — user tự xoá nếu rỗng. Auto-
  // off idle 15 phút và end button thành công cũng đi qua đây.
  useEffect(() => {
    if (realtimeEnabled) return;
    setLiveSessionSourceId(null);
  }, [realtimeEnabled]);

  // Tick re-render badge "Mới nhất: Ns trước" — dù không có điểm mới counter
  // vẫn cần update.
  useEffect(() => {
    if (!realtimeEnabled) return;
    const interval = setInterval(
      () => setNowTick(Date.now()),
      REALTIME_BADGE_TICK_MS,
    );
    return () => clearInterval(interval);
  }, [realtimeEnabled]);

  // Auto-pan tới điểm mới nhất khi user bật "Tự theo dõi vị trí". Lấy điểm
  // cuối array — merge logic append fresh vào cuối nên đây là điểm mới nhất
  // về cả thời gian lẫn thứ tự nhận.
  useEffect(() => {
    if (!realtimeEnabled || !autoFollowEnabled) return;
    if (realtimeFeatures.length === 0) return;
    const newest = realtimeFeatures[realtimeFeatures.length - 1];
    const map = mapRef.current;
    if (!map) return;
    map.flyTo({
      center: [newest.longitude, newest.latitude],
      zoom: Math.max(map.getZoom(), REALTIME_AUTO_FOLLOW_MIN_ZOOM),
      duration: 800,
    });
  }, [realtimeFeatures, realtimeEnabled, autoFollowEnabled]);

  // Nút "Bắt đầu": reset counter + cursor cho chuyến mới, set running=true →
  // effect lifecycle phía trên fire startLiveSession để tạo batch. Realtime
  // poll vẫn chạy độc lập (xem điểm mới trên map dù chưa Start).
  const tRealtime = strings.coverageMap.filters.realtime;
  const handleStartSession = useCallback(() => {
    if (liveSessionSourceId === null) return;
    liveSessionInsertedRef.current = 0;
    sessionCounterRef.current = 0;
    lastPointTimestampRef.current = null;
    sessionStartedAtRef.current = Date.now();
    setRealtimeFeatures([]);
    setLastSeenAt(null);
    setLiveSessionRunning(true);
  }, [liveSessionSourceId]);

  // Nút "Kết thúc": final sync chuyến khảo sát + tổng kết. Cần batch_id
  // (effect lifecycle đã tạo khi nhấn Bắt đầu). Total = cumulative interval
  // inserts + final sync delta. Total > 0 → success modal, tắt running để
  // queryKey đổi → snapshot mới. = 0 → DELETE batch (xoá row rỗng khỏi
  // "Lịch sử upload") + empty modal. Giữ realtimeEnabled để user có thể
  // bắt đầu chuyến mới mà không cần tick lại toggle.
  const handleEndSession = useCallback(async () => {
    const batchId = liveSessionBatchIdRef.current;
    if (batchId === null) {
      setEndModal({
        title: tRealtime.endNeedSourceTitle,
        body: tRealtime.endNeedSourceBody,
      });
      return;
    }
    setEndingBusy(true);
    try {
      const result = await syncLiveSession(batchId);
      if (result.error) {
        setEndModal({
          title: tRealtime.endErrorTitle,
          body: tRealtime.endErrorBody(result.error),
        });
        return;
      }
      const total =
        liveSessionInsertedRef.current + result.measurements_inserted;
      if (total > 0) {
        setEndModal({
          title: tRealtime.endSuccessTitle,
          body: tRealtime.endSuccessBody(total),
        });
        liveSessionBatchIdRef.current = null;
        liveSessionInsertedRef.current = 0;
        setLiveSessionRunning(false);
      } else {
        try {
          await deleteUploadBatch(batchId);
        } catch {
          // Cleanup best-effort — batch rỗng còn lại user có thể tự xoá.
        }
        liveSessionBatchIdRef.current = null;
        liveSessionInsertedRef.current = 0;
        setEndModal({
          title: tRealtime.endEmptyTitle,
          body: tRealtime.endEmptyBody,
        });
        setLiveSessionRunning(false);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setEndModal({
        title: tRealtime.endErrorTitle,
        body: tRealtime.endErrorBody(msg),
      });
    } finally {
      setEndingBusy(false);
    }
  }, [tRealtime]);

  // Render source: realtime → accumulated features; static → snapshot từ
  // useQuery. EMPTY_TRAINING_ITEMS giữ ref ổn định khi data chưa có (tránh
  // `?? []` tạo array mới mỗi render gây setData effect re-fire).
  // liveOnly: filter điểm có timestamp >= mốc session (client time vs server
  // ISO; sai số vài giây chấp nhận được cho UX khảo sát).
  const displayedItems = useMemo(() => {
    if (realtimeEnabled) {
      if (liveOnlyEnabled && sessionStartedAtRef.current !== null) {
        const start = sessionStartedAtRef.current;
        return realtimeFeatures.filter(
          (p) => Date.parse(p.timestamp) >= start,
        );
      }
      return realtimeFeatures;
    }
    return surveysQ.data?.items ?? EMPTY_TRAINING_ITEMS;
  }, [realtimeEnabled, liveOnlyEnabled, realtimeFeatures, surveysQ.data]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || mapRef.current) return;

    let map;
    try {
      map = new maplibregl.Map({
        container,
        style: /** @type {any} */ (BASEMAP_STYLE),
        center: INITIAL_CENTER,
        zoom: INITIAL_ZOOM,
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setTileError(`Map init failed: ${msg}`);
      return;
    }

    map.addControl(new maplibregl.NavigationControl({}), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");

    map.on("error", (e) => {
      const msg = e?.error?.message ?? String(e);
      setTileError(msg);
    });

    // Direct map tap behaviour:
    //   predict          → capture toạ độ vào panel, user bấm "Dự đoán"
    //   points / heatmap → no-op (popup chỉ thuộc về tab Dự đoán điểm)
    map.on("click", (e) => {
      if (mode !== "predict") return;
      const { lat, lng } = e.lngLat;
      // Hit-test: tap trong bán kính 40px của predict marker đã có → reopen
      // popup thay vì tạo gray pick. Radius rộng vì marker là drop-pin
      // anchor="bottom" (lngLat ở mũi tip, bulb cao hơn ~22px) + offset popup.
      // Defer qua rAF: addTo() đăng ký closeOnClick listener; trong cùng tick
      // có thể race với map click event hiện tại.
      const HIT_RADIUS_PX = 40;
      const HIT_R2 = HIT_RADIUS_PX * HIT_RADIUS_PX;
      for (const marker of searchMarkersRef.current) {
        const ll = marker.getLngLat();
        const mp = map.project([ll.lng, ll.lat]);
        const dx = mp.x - e.point.x;
        const dy = mp.y - e.point.y;
        if (dx * dx + dy * dy <= HIT_R2) {
          const popup = marker.getPopup();
          if (popup && !popup.isOpen()) {
            requestAnimationFrame(() => {
              if (!popup.isOpen()) {
                popup.setLngLat(marker.getLngLat()).addTo(map);
              }
            });
          }
          return;
        }
      }
      setPickedCoords({ lat, lng });
      setPredictError(null);
      showPickMarker(lat, lng);
    });

    map.on("load", () => {
      setMapLoaded(true);

      // Predict-line source + layer — add 1 lần khi map load, drawSearchMarker
      // chỉ setData. Line render dưới DOM marker tự nhiên (DOM luôn trên WebGL).
      if (mode === "predict") {
        map.addSource(PREDICT_LINES_SOURCE_ID, {
          type: "geojson",
          data: { type: "FeatureCollection", features: [] },
        });
        map.addLayer({
          id: PREDICT_LINES_LAYER_ID,
          type: "line",
          source: PREDICT_LINES_SOURCE_ID,
          paint: /** @type {any} */ ({
            "line-color": ["get", "color"],
            "line-width": 2,
            "line-opacity": 0.85,
          }),
          layout: { "line-cap": "round", "line-join": "round" },
        });
      }

      // Tab "Bản đồ phủ sóng" (mode "heatmap"): add min-SF source + fill layer
      // ngay khi map load để khi user chọn gateway chỉ cần setData. Layer ẩn
      // mặc định (visibility="none") — bật khi viewMode==="minsf" và có data.
      if (mode === "heatmap") {
        // Satellite ESRI overlay — add TRƯỚC các fill layer để nó nằm dưới
        // (maplibre stack: add sau = trên). Default hidden; toggle visible
        // khi coverageViewMode === "minsf".
        map.addSource(SATELLITE_OVERLAY_SOURCE_ID, {
          type: "raster",
          tiles: SATELLITE_BASEMAP_STYLE.sources.basemap.tiles,
          tileSize: SATELLITE_BASEMAP_STYLE.sources.basemap.tileSize,
          attribution: SATELLITE_BASEMAP_STYLE.sources.basemap.attribution,
          maxzoom: SATELLITE_BASEMAP_STYLE.sources.basemap.maxzoom,
        });
        map.addLayer({
          id: SATELLITE_OVERLAY_LAYER_ID,
          type: "raster",
          source: SATELLITE_OVERLAY_SOURCE_ID,
          layout: /** @type {any} */ ({ visibility: "none" }),
        });

        map.addSource(MINSF_SOURCE_ID, {
          type: "geojson",
          data: { type: "FeatureCollection", features: [] },
        });
        map.addLayer({
          id: MINSF_FILL_LAYER_ID,
          type: "fill",
          source: MINSF_SOURCE_ID,
          // fill-sort-key: SF nhỏ → key cao → render trên cùng. Polygon nested
          // SF7 ⊂ SF8 ⊂ ... ⊂ SF12; nếu để default order (SF12 last → top) sẽ
          // phủ hết SF7..SF11. Sort key = 12 - min_sf đảo lại → SF7 = 5 (top),
          // SF12 = 0 (bottom).
          layout: /** @type {any} */ ({
            visibility: "none",
            "fill-sort-key": ["-", 12, ["get", "min_sf"]],
          }),
          paint: /** @type {any} */ ({
            "fill-color": [
              "match",
              ["get", "min_sf"],
              7, MINSF_BAND_COLORS[7],
              8, MINSF_BAND_COLORS[8],
              9, MINSF_BAND_COLORS[9],
              10, MINSF_BAND_COLORS[10],
              11, MINSF_BAND_COLORS[11],
              12, MINSF_BAND_COLORS[12],
              "#888888",
            ],
            "fill-opacity": MINSF_FILL_OPACITY,
          }),
        });
        map.addLayer({
          id: MINSF_OUTLINE_LAYER_ID,
          type: "line",
          source: MINSF_SOURCE_ID,
          // Outline cùng sort-key để khớp với fill bên dưới — SF nhỏ vẽ trên
          // cùng. line-sort-key chỉ chấp nhận number expression.
          layout: /** @type {any} */ ({
            visibility: "none",
            "line-sort-key": ["-", 12, ["get", "min_sf"]],
          }),
          paint: /** @type {any} */ ({
            "line-color": "rgba(0,0,0,0.25)",
            "line-width": 0.5,
          }),
        });

        // Composite RSSI heatmap source + fill layer. Layout visibility="none"
        // mặc định — bật khi coverageViewMode === "estimate".
        map.addSource(RSSI_COMPOSITE_SOURCE_ID, {
          type: "geojson",
          data: { type: "FeatureCollection", features: [] },
        });
        map.addLayer({
          id: RSSI_COMPOSITE_FILL_LAYER_ID,
          type: "fill",
          source: RSSI_COMPOSITE_SOURCE_ID,
          // fill-sort-key: bin nhỏ (mạnh hơn, vùng nhỏ ở center) lên trên cùng.
          // Nested polygon: bin1 ⊂ bin2 ⊂ ... ⊂ bin6 → cần đảo order render.
          layout: /** @type {any} */ ({
            visibility: "none",
            "fill-sort-key": ["-", 7, ["get", "bin"]],
          }),
          paint: /** @type {any} */ ({
            "fill-color": [
              "match",
              ["get", "bin"],
              1, ESTIMATE_RSSI_BAND_COLORS[1],
              2, ESTIMATE_RSSI_BAND_COLORS[2],
              3, ESTIMATE_RSSI_BAND_COLORS[3],
              4, ESTIMATE_RSSI_BAND_COLORS[4],
              5, ESTIMATE_RSSI_BAND_COLORS[5],
              6, ESTIMATE_RSSI_BAND_COLORS[6],
              "#888888",
            ],
            "fill-opacity": RSSI_FILL_OPACITY,
          }),
        });
      }

      // Survey layer chỉ add cho "points" mode. "heatmap" sẽ add raster
      // source ở Phase 2; "predict" không cần điểm đo nền.
      if (mode !== "points") return;

      // Source GeoJSON rỗng — sẽ setData khi survey query xong.
      map.addSource(SURVEYS_SOURCE_ID, {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      // Thứ tự add quan trọng: heatmap thêm trước → nằm dưới circle trong
      // render stack. Khi đổi viewMode chỉ flip visibility, không reorder.
      addSurveyHeatmapLayer(map, SURVEYS_SOURCE_ID);

      // Connection-lines: source + layer add 1 lần, default hidden. Nằm
      // giữa heatmap và circle để line trên heatmap (visible) nhưng dưới
      // circle (giữ click hit-test).
      map.addSource(SURVEY_CONNECTION_LINES_SOURCE_ID, {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: SURVEY_CONNECTION_LINES_LAYER_ID,
        type: "line",
        source: SURVEY_CONNECTION_LINES_SOURCE_ID,
        layout: /** @type {any} */ ({
          visibility: "none",
          "line-cap": "butt",
          "line-join": "round",
        }),
        paint: /** @type {any} */ ({
          "line-color": "#475569",
          "line-width": 1.2,
          "line-opacity": 0.75,
          "line-dasharray": [2, 2],
        }),
      });

      map.addLayer({
        id: SURVEYS_LAYER_ID,
        type: "circle",
        source: SURVEYS_SOURCE_ID,
        paint: /** @type {any} */ (SURVEY_CIRCLE_PAINT),
      });

      // Lazy popup — chỉ tạo khi click 1 circle, không pre-render 4k popup.
      // 1 packet → N row (1/gateway nhận) cùng (device_id+timestamp); group
      // sibling rows từ displayedItemsRef để list "Gateway kết nối".
      map.on("click", SURVEYS_LAYER_ID, (e) => {
        const f = e.features?.[0];
        if (!f) return;
        const p = /** @type {{
         *   rssi_dbm: number,
         *   snr_db: number,
         *   spreading_factor: number,
         *   device_id: string,
         *   frequency_mhz: number,
         *   timestamp: string,
         *   code_rate: string,
         * }} */ (f.properties);
        const geom = /** @type {GeoJSON.Point} */ (f.geometry);
        const [lng, lat] = /** @type {[number, number]} */ (geom.coordinates);
        const device = p.device_id ? escapeHtml(p.device_id) : "—";
        const codeRate = p.code_rate ? escapeHtml(p.code_rate) : "—";

        const gwByUuid = new Map(gatewaysRef.current.map((g) => [g.id, g]));
        const sameKey = `${p.timestamp}|${p.device_id ?? ""}`;
        const siblings = displayedItemsRef.current.filter(
          (r) => `${r.timestamp}|${r.device_id ?? ""}` === sameKey,
        );
        // Sort gateway list theo RSSI desc — best signal first.
        const rows = [...siblings].sort((a, b) => b.rssi_dbm - a.rssi_dbm);
        const top = rows[0] ?? null;
        const headerRssi = top ? top.rssi_dbm : Number(p.rssi_dbm);
        const headerSnr = top ? top.snr_db : Number(p.snr_db);

        const gwListHtml = rows
          .map((r) => {
            const gw = r.serving_gateway_id
              ? gwByUuid.get(r.serving_gateway_id)
              : null;
            const name = gw ? escapeHtml(gw.name) : "—";
            const dist = gw
              ? `${Math.round(haversineMeters(lat, lng, gw.latitude, gw.longitude))} m`
              : "—";
            return `<div>• ${name}: ${dist}, ${t.popup.rssiLabel}: ${Number(r.rssi_dbm).toFixed(1)} dBm, ${t.popup.snrLabel}: ${Number(r.snr_db).toFixed(1)} dB</div>`;
          })
          .join("");

        new maplibregl.Popup({ offset: 8 })
          .setLngLat([lng, lat])
          .setHTML(
            `<div style="font:12px/1.4 system-ui">
               <div><strong>${t.popup.surveyTitle}</strong></div>
               <div>${t.popup.deviceLabel}: ${device}</div>
               <div>${t.popup.rssiLabel}: ${headerRssi.toFixed(1)} dBm</div>
               <div>${t.popup.snrLabel}: ${headerSnr.toFixed(1)} dB</div>
               <div>${t.popup.frequencyLabel}: ${Number(p.frequency_mhz).toFixed(2)} MHz</div>
               <div>${t.popup.sfLabel(Number(p.spreading_factor))}</div>
               <div>${t.popup.codeRateLabel}: ${codeRate}</div>
               <div>${t.popup.timeLabel}: ${formatSurveyTime(String(p.timestamp))}</div>
               ${gwListHtml ? `<div style="margin-top:6px"><strong>${t.popup.gatewayConnectedLabel}:</strong></div>${gwListHtml}` : ""}
             </div>`,
          )
          .addTo(map);
      });

      // Đổi cursor khi hover circle để user biết click được.
      map.on("mouseenter", SURVEYS_LAYER_ID, () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", SURVEYS_LAYER_ID, () => {
        map.getCanvas().style.cursor = "";
      });

      // Trigger render survey nếu data đã sẵn trước khi map load xong.
      // Dùng displayedItems để chung pipeline với realtime accumulator.
      if (displayedItems.length > 0) {
        const src = map.getSource(SURVEYS_SOURCE_ID);
        if (src && "setData" in src) {
          /** @type {maplibregl.GeoJSONSource} */ (src).setData(
            buildSurveyGeoJson(displayedItems),
          );
        }
      }
    });

    mapRef.current = map;
    return () => {
      setMapLoaded(false);
      map.remove();
      mapRef.current = null;
    };
    // Map init 1 lần duy nhất khi mount; mode được "đóng băng" qua closure
    // (mỗi tab unmount/mount component riêng nên mode constant per-mount),
    // surveysQ.data có effect riêng phía dưới handle update.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Survey: 1 lệnh setData() trên GeoJSON source thay vì 4k+ HTML markers.
  // Dep theo displayedItems → realtime append fresh ⇒ effect tự fire setData.
  useEffect(() => {
    if (mode !== "points") return;
    const map = mapRef.current;
    if (!map) return;
    if (!mapLoaded || !map.getSource(SURVEYS_SOURCE_ID)) return;
    displayedItemsRef.current = displayedItems;
    /** @type {maplibregl.GeoJSONSource} */ (
      map.getSource(SURVEYS_SOURCE_ID)
    ).setData(buildSurveyGeoJson(displayedItems));
  }, [displayedItems, mode, mapLoaded]);

  // Toggle visibility 2 layer điểm đo theo viewMode — circle ↔ heatmap. Cả 2
  // dùng chung source nên filter (sf/rssi/...) auto-apply cho cả 2 mode.
  useEffect(() => {
    if (mode !== "points") return;
    const map = mapRef.current;
    if (!map || !mapLoaded) return;
    if (!map.getLayer(SURVEYS_LAYER_ID)) return;
    const showCircle = viewMode === "points";
    map.setLayoutProperty(
      SURVEYS_LAYER_ID,
      "visibility",
      showCircle ? "visible" : "none",
    );
    setSurveyHeatmapVisible(map, !showCircle);
  }, [viewMode, mode, mapLoaded]);

  // setData line nối điểm đo → serving gateway. Fire khi displayedItems
  // hoặc gateway list đổi (race: gateway có thể load sau survey). Skip
  // build nếu toggle off để khỏi tốn CPU khi user không xem.
  useEffect(() => {
    if (mode !== "points") return;
    const map = mapRef.current;
    if (!map || !mapLoaded) return;
    if (!map.getSource(SURVEY_CONNECTION_LINES_SOURCE_ID)) return;
    const src = /** @type {maplibregl.GeoJSONSource} */ (
      map.getSource(SURVEY_CONNECTION_LINES_SOURCE_ID)
    );
    if (!showConnectionLines) {
      src.setData({ type: "FeatureCollection", features: [] });
      return;
    }
    const gateways = gatewaysQ.data?.items ?? [];
    src.setData(buildSurveyConnectionLinesGeoJson(displayedItems, gateways));
  }, [
    displayedItems,
    gatewaysQ.data,
    showConnectionLines,
    mode,
    mapLoaded,
  ]);

  // Flip visibility line layer theo toggle. Tách khỏi setData để bật/tắt
  // không trigger rebuild FeatureCollection (giữ data ngay khi tắt cũng
  // OK vì effect setData ở trên đã clear features khi toggle off).
  useEffect(() => {
    if (mode !== "points") return;
    const map = mapRef.current;
    if (!map || !mapLoaded) return;
    if (!map.getLayer(SURVEY_CONNECTION_LINES_LAYER_ID)) return;
    map.setLayoutProperty(
      SURVEY_CONNECTION_LINES_LAYER_ID,
      "visibility",
      showConnectionLines ? "visible" : "none",
    );
  }, [showConnectionLines, mode, mapLoaded]);

  // Tab "Bản đồ phủ sóng": sync visibility 2 layer min-SF với viewMode +
  // có gateway đang chọn. Khi switch sang "estimate" hoặc bỏ chọn gateway →
  // ẩn cả 2 layer. Không clear source data — giữ để switch lại nhanh.
  useEffect(() => {
    if (mode !== "heatmap") return;
    const map = mapRef.current;
    if (!map || !mapLoaded) return;
    if (!map.getLayer(MINSF_FILL_LAYER_ID)) return;
    const visible =
      coverageViewMode === "minsf" && minsfGatewayCode != null ? "visible" : "none";
    map.setLayoutProperty(MINSF_FILL_LAYER_ID, "visibility", visible);
    map.setLayoutProperty(MINSF_OUTLINE_LAYER_ID, "visibility", visible);
  }, [coverageViewMode, minsfGatewayCode, mode, mapLoaded]);

  // Satellite ESRI overlay: chỉ hiện khi đang xem min-SF (cần đối chiếu
  // với buildings/đường). Estimate view dùng basemap CARTO cho composite
  // RSSI nhìn rõ hơn.
  useEffect(() => {
    if (mode !== "heatmap") return;
    const map = mapRef.current;
    if (!map || !mapLoaded) return;
    if (!map.getLayer(SATELLITE_OVERLAY_LAYER_ID)) return;
    map.setLayoutProperty(
      SATELLITE_OVERLAY_LAYER_ID,
      "visibility",
      coverageViewMode === "minsf" ? "visible" : "none",
    );
  }, [coverageViewMode, mode, mapLoaded]);

  // Fetch GeoJSON tĩnh từ public/coverage/minsf/{code}.geojson khi user chọn
  // gateway. File precomputed offline qua `scripts/precompute_minsf.py` —
  // không qua API, không có authentication. AbortController để cancel khi
  // user đổi nhanh (race-safe).
  useEffect(() => {
    if (mode !== "heatmap") return;
    const map = mapRef.current;
    if (!map || !mapLoaded || !minsfGatewayCode) {
      // Clear source khi bỏ chọn để không tốn memory với feature cũ.
      if (map && mapLoaded && map.getSource(MINSF_SOURCE_ID)) {
        /** @type {maplibregl.GeoJSONSource} */ (
          map.getSource(MINSF_SOURCE_ID)
        ).setData({ type: "FeatureCollection", features: [] });
      }
      setMinsfLoadError(null);
      return;
    }

    setMinsfLoadError(null);
    const controller = new AbortController();
    const url = `${import.meta.env.BASE_URL ?? "/"}coverage/minsf/${encodeURIComponent(minsfGatewayCode)}.geojson`;
    fetch(url, { signal: controller.signal })
      .then(async (res) => {
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }
        const fc = await res.json();
        if (!fc || !Array.isArray(fc.features)) {
          throw new Error("invalid_geojson");
        }
        const src = map.getSource(MINSF_SOURCE_ID);
        if (src && "setData" in src) {
          /** @type {maplibregl.GeoJSONSource} */ (src).setData(fc);
        }
        // Fly tới gateway center nếu có trong properties.
        const props = /** @type {Record<string, any>} */ (fc.properties ?? {});
        if (
          typeof props.gateway_lat === "number" &&
          typeof props.gateway_lon === "number"
        ) {
          map.flyTo({
            center: [props.gateway_lon, props.gateway_lat],
            zoom: 11,
            duration: 800,
          });
        }
        if (fc.features.length === 0) {
          setMinsfLoadError(strings.coverageMap.minsf.loadEmpty);
        }
      })
      .catch((err) => {
        if (err.name === "AbortError") return;
        console.error("min-SF fetch failed:", err);
        setMinsfLoadError(strings.coverageMap.minsf.loadError);
        const src = map.getSource(MINSF_SOURCE_ID);
        if (src && "setData" in src) {
          /** @type {maplibregl.GeoJSONSource} */ (src).setData({
            type: "FeatureCollection",
            features: [],
          });
        }
      });

    return () => controller.abort();
  }, [minsfGatewayCode, mode, mapLoaded]);

  // Composite RSSI heatmap: toggle visibility theo coverageViewMode. Khác
  // min-SF (cần gateway selection) — composite hiển thị ngay khi switch
  // sang "estimate".
  useEffect(() => {
    if (mode !== "heatmap") return;
    const map = mapRef.current;
    if (!map || !mapLoaded) return;
    if (!map.getLayer(RSSI_COMPOSITE_FILL_LAYER_ID)) return;
    map.setLayoutProperty(
      RSSI_COMPOSITE_FILL_LAYER_ID,
      "visibility",
      coverageViewMode === "estimate" ? "visible" : "none",
    );
  }, [coverageViewMode, mode, mapLoaded]);

  // Fetch RSSI GeoJSON khi vào estimate mode hoặc khi gateway picker đổi.
  // Key = "composite" cho all-gw, hoặc code cho per-gw. estimateLoadedRef cache
  // key đã load để né re-fetch khi switch minsf ↔ estimate (giữ data đã load).
  useEffect(() => {
    if (mode !== "heatmap") return;
    if (coverageViewMode !== "estimate") return;
    const map = mapRef.current;
    if (!map || !mapLoaded) return;
    if (!map.getSource(RSSI_COMPOSITE_SOURCE_ID)) return;

    const key = estimateGatewayCode ?? "composite";
    if (estimateLoadedRef.current === key) return;

    const controller = new AbortController();
    const base = import.meta.env.BASE_URL ?? "/";
    const url =
      estimateGatewayCode == null
        ? `${base}coverage/rssi/composite.geojson`
        : `${base}coverage/rssi/per_gw/${encodeURIComponent(estimateGatewayCode)}.geojson`;
    setEstimateLoadError(null);

    fetch(url, { signal: controller.signal })
      .then((r) => {
        if (!r.ok) throw new Error(`RSSI HTTP ${r.status}`);
        return r.json();
      })
      .then((fc) => {
        if (!fc || !Array.isArray(fc.features)) {
          throw new Error("invalid RSSI geojson");
        }
        const src = map.getSource(RSSI_COMPOSITE_SOURCE_ID);
        if (src && "setData" in src) {
          /** @type {maplibregl.GeoJSONSource} */ (src).setData(fc);
        }
        estimateLoadedRef.current = key;
      })
      .catch((err) => {
        if (err.name === "AbortError") return;
        console.error("RSSI heatmap fetch failed:", err);
        setEstimateLoadError(strings.coverageMap.estimate.loadError);
      });

    return () => controller.abort();
  }, [coverageViewMode, mode, mapLoaded, estimateGatewayCode]);

  // Ring toả từ mỗi gateway — MapLibre circle layer, bán kính bám km theo zoom.
  // Bán kính nhỏ hơn + period chậm hơn mappreview để CoverageMap đỡ nhiễu mắt.
  // Quy đổi mét→pixel làm bằng zoom expression (interpolate exponential base 2)
  // → MapLibre tính radius ngay tại paint time với current paint zoom, không
  // lệch 1 frame so với JS getZoom() → ring mượt khi user zoom/pan.
  // Setup idempotent (skip nếu source/layer đã tồn tại); cleanup CHỈ cancel RAF.
  // Source/layer sống cùng đời map — parent destroy map sẽ wipe — tránh race
  // condition với MapLibre teardown khi HMR / dependency re-fire.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoaded) return undefined;

    const SRC_ID = "cm-gw-pulse-src";
    const LAYER_ID = "cm-gw-pulse-ring";

    if (!map.getSource(SRC_ID)) {
      map.addSource(SRC_ID, {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
    }
    if (!map.getLayer(LAYER_ID)) {
      map.addLayer({
        id: LAYER_ID,
        type: "circle",
        source: SRC_ID,
        paint: /** @type {any} */ ({
          "circle-radius": [
            "interpolate",
            ["exponential", 2],
            ["zoom"],
            0,
            0,
            22,
            0,
          ],
          "circle-color": "rgba(0,0,0,0)",
          "circle-stroke-width": 1.5,
          "circle-stroke-color": "rgba(10,61,145,0.7)",
          "circle-stroke-opacity": 0,
        }),
      });
    }

    let rafId = 0;
    let cancelled = false;
    const PERIOD_MS = 5400;
    const TARGET_M = 5000;
    const PEAK_OPACITY = 0.45;
    const FADE_IN = 0.05;
    // mPerPx_at_zoom0 = 40075016.686/256 ≈ 156543.03 (equator). Nhân cos(lat)
    // để có mPerPx thực; bake cos(16°)≈0.961 cho VN (Đà Nẵng) — sai số ~2.7%
    // tại Hải Phòng (~20.8°N), không thấy bằng mắt với pulse 5km.
    const MPP_DENOM = 156543.03 * 0.961;
    const POW2_22 = 4194304; // 2^22, biên trên zoom của expression
    const startMs = performance.now();
    const tick = (/** @type {number} */ now) => {
      if (cancelled) return;
      const m = mapRef.current;
      if (!m || !m.getLayer(LAYER_ID)) return;
      // RAF timestamp có thể < startMs (frame đã bắt đầu trước khi gọi
      // performance.now). Clamp >= 0 để phase không âm → tránh MapLibre
      // throw "circle-radius < 0".
      const elapsed = Math.max(0, now - startMs);
      const phase = (elapsed % PERIOD_MS) / PERIOD_MS;
      // Radius_px @ z=0 (a). Tại zoom z bất kỳ, exponential-base-2 interpolate
      // giữa (0,a) và (22,a*2^22) cho đúng a*2^z = TARGET_M*phase / mPerPx(z).
      const a = (TARGET_M * phase) / MPP_DENOM;
      // Opacity: fade-in 5% đầu (loại pop ở mép loop) + hold + drop hard 20%
      // cuối. min(ramp-up, drop-down).
      const fadeIn = Math.min(1, phase / FADE_IN);
      const fadeOut = 1 - Math.pow(phase, 4);
      const opacity = PEAK_OPACITY * Math.min(fadeIn, fadeOut);
      m.setPaintProperty(LAYER_ID, "circle-radius", [
        "interpolate",
        ["exponential", 2],
        ["zoom"],
        0,
        a,
        22,
        a * POW2_22,
      ]);
      m.setPaintProperty(LAYER_ID, "circle-stroke-opacity", opacity);
      rafId = requestAnimationFrame(tick);
    };
    rafId = requestAnimationFrame(tick);

    return () => {
      cancelled = true;
      if (rafId) cancelAnimationFrame(rafId);
    };
  }, [mapLoaded]);

  // Gateway markers — HTML marker đơn giản 1 marker / gateway, popup
  // TX/gain/antenna/freq khi click. Clear & recreate khi data đổi.
  // Bản đồ ước lượng (mode=heatmap + viewMode=estimate) khi chọn 1 gateway
  // cụ thể → chỉ hiện marker của gateway đó, ẩn các gateway còn lại; chọn
  // "Tất cả gateway (tổng hợp)" (estimateGatewayCode === null) → hiện toàn bộ.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !gatewaysQ.data || !mapLoaded) return;
    gatewaysRef.current = gatewaysQ.data.items;

    for (const m of gatewayMarkersRef.current) m.remove();
    gatewayMarkersRef.current = [];

    const filterEstimateGw =
      mode === "heatmap" &&
      coverageViewMode === "estimate" &&
      estimateGatewayCode != null;

    for (const g of gatewaysQ.data.items) {
      if (filterEstimateGw && g.code !== estimateGatewayCode) continue;
      const el = document.createElement("div");
      // Glow chấm trắng + ring pulse — dùng chung class .cm-gw-marker khai
      // báo ở index.css, khớp visual với landing map preview.
      el.className = "cm-gw-marker";
      el.setAttribute("aria-label", `Gateway ${g.code}`);
      // g.code + g.name từ ChirpStack do user link → có thể chứa HTML (XSS).
      // Build DOM bằng textContent, KHÔNG setHTML. Các field số (tx_power_dbm,
      // antenna_*, frequency_mhz) đã validate ở schema backend nên dùng
      // template string đặt qua textContent — không cần escape numeric.
      const popupRoot = document.createElement("div");
      popupRoot.style.cssText = "font:12px/1.4 system-ui";

      const titleRow = document.createElement("div");
      const codeStrong = document.createElement("strong");
      codeStrong.textContent = g.code;
      titleRow.appendChild(codeStrong);
      titleRow.appendChild(document.createTextNode(` — ${g.name}`));
      popupRoot.appendChild(titleRow);

      const txRow = document.createElement("div");
      txRow.textContent = `${t.popup.gatewayTx}: ${g.tx_power_dbm} dBm, ${t.popup.gatewayGain} ${g.antenna_gain_dbi} dBi`;
      popupRoot.appendChild(txRow);

      const antRow = document.createElement("div");
      antRow.textContent = `${t.popup.gatewayAntenna}: ${g.antenna_height_m} m AGL`;
      popupRoot.appendChild(antRow);

      const freqRow = document.createElement("div");
      freqRow.textContent = `${t.popup.gatewayFreq}: ${g.frequency_mhz} MHz`;
      popupRoot.appendChild(freqRow);

      // Address row — lazy fetch reverse-geocode khi popup mở lần đầu.
      // Nominatim cho phép browser usage low-frequency, không cần API key.
      // Gắn label + span riêng để chỉ update text khi fetch xong.
      const addrRow = document.createElement("div");
      addrRow.appendChild(
        document.createTextNode(`${t.popup.gatewayAddress}: `),
      );
      const addrValue = document.createElement("span");
      addrRow.appendChild(addrValue);
      popupRoot.appendChild(addrRow);

      const applyAddress = (
        /** @type {string | null | undefined} */ value,
      ) => {
        if (value === "") {
          addrValue.textContent = t.popup.gatewayAddressLoading;
          addrValue.style.color = "#666";
        } else if (value == null) {
          addrValue.textContent = t.popup.gatewayAddressError;
          addrValue.style.color = "#a00";
        } else {
          addrValue.textContent = value;
          addrValue.style.color = "";
        }
      };
      applyAddress(gatewayAddressCacheRef.current.get(g.code));

      const popup = new maplibregl.Popup({ offset: 12 }).setDOMContent(popupRoot);
      popup.on("open", () => {
        const cache = gatewayAddressCacheRef.current;
        const cached = cache.get(g.code);
        // undefined = chưa fetch bao giờ → trigger lazy fetch.
        // "" (loading) / string (hit) / null (lỗi) → đã có state, skip.
        if (cached !== undefined) return;
        cache.set(g.code, "");
        applyAddress("");
        const url =
          `https://nominatim.openstreetmap.org/reverse` +
          `?format=json&zoom=18&addressdetails=1&accept-language=vi` +
          `&lat=${encodeURIComponent(g.latitude)}` +
          `&lon=${encodeURIComponent(g.longitude)}`;
        fetch(url, { headers: { Accept: "application/json" } })
          .then((res) => (res.ok ? res.json() : Promise.reject(res.status)))
          .then((data) => {
            const name =
              data && typeof data.display_name === "string"
                ? data.display_name
                : null;
            cache.set(g.code, name);
            applyAddress(name);
          })
          .catch(() => {
            cache.set(g.code, null);
            applyAddress(null);
          });
      });
      // Marker tâm chấm tròn đặt đúng tại tọa độ gateway (anchor default
      // = center). Khác teardrop pin cũ (anchor="bottom") — circle nên
      // center mới đặt đúng tâm chấm vào toạ độ.
      const marker = new maplibregl.Marker({ element: el })
        .setLngLat([g.longitude, g.latitude])
        .setPopup(popup)
        .addTo(map);
      gatewayMarkersRef.current.push(marker);
    }

    // Sync pulse ring source — chỉ feed gateway nào đang hiện marker (cùng
    // filterEstimateGw) để ring không vẽ vào điểm bị ẩn.
    const pulseSrc = map.getSource("cm-gw-pulse-src");
    if (pulseSrc && "setData" in pulseSrc) {
      const pulseFeatures = gatewaysQ.data.items
        .filter((g) => {
          if (filterEstimateGw && g.code !== estimateGatewayCode) return false;
          return g.latitude != null && g.longitude != null;
        })
        .map((g) => ({
          type: /** @type {const} */ ("Feature"),
          properties: {},
          geometry: {
            type: /** @type {const} */ ("Point"),
            coordinates: [g.longitude, g.latitude],
          },
        }));
      /** @type {maplibregl.GeoJSONSource} */ (pulseSrc).setData({
        type: "FeatureCollection",
        features: pulseFeatures,
      });
    }

    return () => {
      for (const m of gatewayMarkersRef.current) m.remove();
      gatewayMarkersRef.current = [];
    };
  }, [gatewaysQ.data, mapLoaded, mode, coverageViewMode, estimateGatewayCode]);

  /**
   * Build popup DOM 2 layer cho marker dự đoán (chỉ tab "Dự đoán điểm").
   *  - Header: tiêu đề "Điểm dự đoán" + dòng toạ độ.
   *  - Layer 1 (default): badge trạng thái + 1 câu giải thích tiếng Việt.
   *  - Layer 2 (toggle): SF dùng vs SF khuyến nghị (highlight nếu lệch),
   *    RSSI / SNR / Confidence + link gateway phục vụ.
   * Theo business-logic.md §4.2 — dual-layer rule cho 1 feature phục vụ
   * cả end-user (Layer 1) lẫn kỹ sư P1/P2 (Layer 2).
   * @type {(lat: number, lng: number, prediction: import("../api/client.js").PredictionT, sfUsed: number, isAuto: boolean, txPowerUsed: number, environmentUsed: "outdoor" | "indoor", label?: string | null) => HTMLDivElement}
   */
  const buildPopupNode = useCallback((lat, lng, prediction, sfUsed, isAuto, txPowerUsed, environmentUsed, label) => {
    const root = document.createElement("div");
    root.style.cssText = "font:12px/1.4 system-ui;max-width:360px;min-width:320px";

    const status = prediction.coverage_status;
    const color = STATUS_COLOR[status] ?? STATUS_COLOR_FALLBACK;

    const title = document.createElement("div");
    title.style.cssText = "font-weight:600;color:#0f172a";
    title.textContent = t.popup.predictTitle;
    root.appendChild(title);

    // Nhãn user-supplied (chỉ có khi handoff từ bulk). textContent đảm bảo
    // không bị XSS từ CSV label.
    if (label) {
      const labelRow = document.createElement("div");
      labelRow.style.cssText =
        "font-weight:500;color:#1e293b;margin-top:2px;word-break:break-word";
      labelRow.textContent = label;
      root.appendChild(labelRow);
    }

    const subtitle = document.createElement("div");
    subtitle.style.cssText =
      "font:11px/1.3 ui-monospace,SFMono-Regular,Menlo,monospace;color:#64748b;margin-bottom:6px";
    subtitle.textContent = t.popup.coords(lat, lng);
    root.appendChild(subtitle);

    // Layer 1: status badge only — bottleneck direction pill đã bỏ 2026-06-14.
    const badgeRow = document.createElement("div");
    badgeRow.style.cssText = "display:flex;flex-wrap:wrap;gap:6px;align-items:center";
    const badge = document.createElement("span");
    badge.style.cssText = `display:inline-block;background:${color};color:white;padding:2px 8px;border-radius:9999px;font-weight:600;font-size:11px`;
    badge.textContent = STATUS_LABEL[status] ?? status;
    badgeRow.appendChild(badge);
    root.appendChild(badgeRow);

    const sentence = document.createElement("div");
    sentence.style.cssText = "margin-top:6px;color:#475569";
    /** @type {Record<string, string>} */
    const sentences = t.popup.layer1Sentence;
    sentence.textContent = sentences[status] ?? "";
    root.appendChild(sentence);

    const toggleBtn = document.createElement("button");
    toggleBtn.type = "button";
    toggleBtn.style.cssText =
      "margin-top:8px;font-size:11px;color:#0369a1;background:none;border:none;padding:0;cursor:pointer";
    toggleBtn.textContent = t.popup.toggleLayer2.show;
    root.appendChild(toggleBtn);

    const layer2 = document.createElement("div");
    layer2.style.cssText =
      "display:none;margin-top:6px;padding-top:6px;border-top:1px solid #e2e8f0;color:#334155;max-height:55vh;overflow-y:auto";

    // 11 mục kết quả dự đoán: RSSI, SNR, PDR, can nhiễu, SF, băng thông,
    // đa đường & che chắn, BER/FER, độ trễ, gateway, môi trường. Item 1-9
    // ở 2-cột grid, item 10 (gateway) + 11 (môi trường) full-width.
    const sq = prediction.signal_quality;
    const env = prediction.environment_params;
    const NA = t.popup.fields.unavailable;
    const rec = prediction.recommended_sf;
    const usedSf = env?.spreading_factor ?? sfUsed;

    const grid = document.createElement("div");
    grid.style.cssText = "display:grid;grid-template-columns:1fr 1fr;gap:8px 12px";

    grid.appendChild(
      buildFieldCell(t.popup.fields.rssi, `${prediction.rssi_dbm.toFixed(1)} dBm`),
    );
    grid.appendChild(
      buildFieldCell(t.popup.fields.snr, `${prediction.snr_db.toFixed(1)} dB`),
    );
    grid.appendChild(
      buildFieldCell(
        t.popup.fields.pdr,
        sq ? `${(sq.pdr * 100).toFixed(1)}%` : NA,
        sq ? t.popup.fields.pdrSub : undefined,
      ),
    );
    grid.appendChild(
      buildFieldCell(
        t.popup.fields.interference,
        sq
          ? `UL ${sq.uplink_noise_floor_dbm.toFixed(1)} · DL ${sq.downlink_noise_floor_dbm.toFixed(1)} dBm`
          : NA,
        sq ? t.popup.fields.interferenceSub : undefined,
      ),
    );
    grid.appendChild(
      buildFieldCell(
        t.popup.fields.sf,
        `SF${usedSf}`,
        usedSf === rec
          ? t.popup.fields.sfMatch
          : t.popup.fields.sfRecommended(rec),
      ),
    );
    grid.appendChild(
      buildFieldCell(
        t.popup.fields.bandwidth,
        sq ? `${(sq.bandwidth_hz / 1000).toFixed(0)} kHz` : NA,
        sq ? t.popup.fields.bandwidthSub : undefined,
      ),
    );
    grid.appendChild(
      buildFieldCell(
        t.popup.fields.shadowing,
        sq ? `σ = ${sq.shadow_fading_sigma_db.toFixed(1)} dB` : NA,
        sq ? t.popup.fields.shadowingSub : undefined,
      ),
    );
    grid.appendChild(
      buildFieldCell(
        t.popup.fields.berFer,
        sq ? `${formatBer(sq.ber)} · FER ${(sq.fer * 100).toFixed(1)}%` : NA,
        sq ? t.popup.fields.berFerSub : undefined,
      ),
    );
    grid.appendChild(
      buildFieldCell(
        t.popup.fields.latency,
        sq ? `≈ ${sq.time_on_air_ms.toFixed(0)} ms` : NA,
        sq ? t.popup.fields.latencySub(sq.jitter_ms) : undefined,
      ),
    );
    layer2.appendChild(grid);

    // Item 10: Gateway kết nối — full-width, có link click → flyTo gateway.
    // Khi no_coverage: BE vẫn trả serving_gateway_id = candidate ít tệ nhất
    // (debug field), nhưng UX-wise treat như "không có gateway phục vụ".
    const gw =
      prediction.serving_gateway_id && prediction.coverage_status !== "no_coverage"
        ? gatewaysRef.current.find((x) => x.id === prediction.serving_gateway_id)
        : null;
    const gwWrap = document.createElement("div");
    gwWrap.style.cssText = "margin-top:8px";
    const gwLabel = document.createElement("div");
    gwLabel.style.cssText = "color:#64748b;font-size:10px;line-height:1.3";
    gwLabel.textContent = t.popup.fields.gateway;
    gwWrap.appendChild(gwLabel);
    const gwValue = document.createElement("div");
    gwValue.style.cssText = "color:#0f172a;font-weight:600;font-size:11px;margin-top:1px";
    if (gw) {
      const link = document.createElement("a");
      link.href = "#";
      link.style.cssText = "color:#0369a1;text-decoration:underline";
      link.textContent = `${gw.code} — ${gw.name}`;
      link.addEventListener("click", (e) => {
        e.preventDefault();
        mapRef.current?.flyTo({ center: [gw.longitude, gw.latitude], zoom: 16 });
      });
      gwValue.appendChild(link);
    } else {
      gwValue.textContent = t.popup.nearestGatewayNone;
    }
    gwWrap.appendChild(gwValue);
    if (gw && prediction.distance_to_serving_gateway_km > 0) {
      const distSub = document.createElement("div");
      distSub.style.cssText = "color:#94a3b8;font-size:10px;line-height:1.25;margin-top:1px";
      distSub.textContent = `cách ${t.popup.distanceToGateway.value(prediction.distance_to_serving_gateway_km)}`;
      gwWrap.appendChild(distSub);
    }
    // Covering gateway count: redundancy indicator (1 = SPOF; ≥2 = diversity).
    const coveringCount = prediction.covering_gateway_count ?? 0;
    const coverSub = document.createElement("div");
    coverSub.style.cssText = "color:#94a3b8;font-size:10px;line-height:1.25;margin-top:1px";
    coverSub.textContent = `${t.popup.fields.coveringGateways}: ${coveringCount} (${t.popup.fields.coveringGatewaysSub(coveringCount)})`;
    gwWrap.appendChild(coverSub);
    layer2.appendChild(gwWrap);

    // Item 11: Thông số môi trường — freq · TX power · env. Fallback dùng
    // function args khi BE chưa wire environment_params (graceful degrade).
    /** @type {Record<string, string>} */
    const envLabelMap = t.popup.envLabel;
    const envName = env
      ? envLabelMap[env.environment] ?? env.environment
      : envLabelMap[environmentUsed] ?? environmentUsed;
    const envFreq = env?.frequency_mhz ?? DEFAULT_FREQ_MHZ;
    const envTx = env?.tx_power_dbm ?? txPowerUsed;
    const envWrap = document.createElement("div");
    envWrap.style.cssText = "margin-top:8px";
    const envLabel2 = document.createElement("div");
    envLabel2.style.cssText = "color:#64748b;font-size:10px;line-height:1.3";
    envLabel2.textContent = t.popup.fields.environment;
    envWrap.appendChild(envLabel2);
    const envValue = document.createElement("div");
    envValue.style.cssText = "color:#0f172a;font-weight:600;font-size:11px;margin-top:1px";
    envValue.textContent = `${envFreq} MHz · ${envTx} dBm · ${envName}`;
    envWrap.appendChild(envValue);
    const envSub = document.createElement("div");
    envSub.style.cssText = "color:#94a3b8;font-size:10px;line-height:1.25;margin-top:1px";
    envSub.textContent = t.popup.fields.environmentSub;
    envWrap.appendChild(envSub);
    layer2.appendChild(envWrap);

    // Bottleneck root-causes — list "Bottleneck có thể xảy ra ở..." khi BE
    // phát hiện ≥1 cause; rỗng → fallback "link healthy" (informative cho user
    // khi STRONG).
    const causes = prediction.bottleneck_causes ?? [];
    const causesWrap = document.createElement("div");
    causesWrap.style.cssText = "margin-top:8px";
    const causesLabel = document.createElement("div");
    causesLabel.style.cssText = "color:#64748b;font-size:10px;line-height:1.3";
    causesLabel.textContent = t.popup.bottleneckCauses.heading;
    causesWrap.appendChild(causesLabel);
    if (causes.length === 0) {
      const none = document.createElement("div");
      none.style.cssText =
        "color:#0f172a;font-weight:500;font-size:11px;margin-top:2px";
      none.textContent = t.popup.bottleneckCauses.none;
      causesWrap.appendChild(none);
    } else {
      const ul = document.createElement("ul");
      ul.style.cssText =
        "margin:2px 0 0 0;padding-left:16px;color:#0f172a;font-size:11px;line-height:1.4";
      for (const c of causes) {
        const li = document.createElement("li");
        li.textContent = t.popup.bottleneckCauses[c] ?? c;
        ul.appendChild(li);
      }
      causesWrap.appendChild(ul);
    }
    layer2.appendChild(causesWrap);

    appendCopyLinkButton(layer2, lat, lng);

    root.appendChild(layer2);

    toggleBtn.addEventListener("click", () => {
      const visible = layer2.style.display !== "none";
      layer2.style.display = visible ? "none" : "block";
      toggleBtn.textContent = visible
        ? t.popup.toggleLayer2.show
        : t.popup.toggleLayer2.hide;
      // Mobile (< Tailwind `md` = 768px): legend ở góc dưới-trái dễ bị popup
      // Layer 2 đè. Ẩn tạm khi expand, hiện lại khi collapse. Desktop/tablet
      // không cần vì viewport đủ rộng. visible = state TRƯỚC click (true =
      // đang mở → user vừa nhấn để đóng).
      if (window.innerWidth < 768) {
        const legendEl = /** @type {HTMLElement | null} */ (
          document.querySelector("[data-map-legend]")
        );
        if (legendEl) {
          legendEl.style.visibility = visible ? "" : "hidden";
        }
      }
      // Khi expand: popup phình to → maplibre KHÔNG tự re-evaluate anchor nên
      // popup tràn mép map nếu marker gần biên. Sau reflow (rAF), đo bbox
      // popup vs map → panBy để popup nằm gọn trong viewport (giữ pad 12px).
      // panBy([dx, dy]): positive dx → screen view dịch phải (content trái),
      // positive dy → screen view dịch xuống (content lên).
      if (visible) return;
      requestAnimationFrame(() => {
        const map = mapRef.current;
        if (!map) return;
        const popupEl = /** @type {HTMLElement | null} */ (
          root.closest(".maplibregl-popup")
        );
        if (!popupEl) return;
        const pRect = popupEl.getBoundingClientRect();
        const mRect = map.getContainer().getBoundingClientRect();
        const pad = 12;
        const overTop = Math.max(0, mRect.top + pad - pRect.top);
        const overBottom = Math.max(0, pRect.bottom - (mRect.bottom - pad));
        const overLeft = Math.max(0, mRect.left + pad - pRect.left);
        const overRight = Math.max(0, pRect.right - (mRect.right - pad));
        const dx = overRight - overLeft;
        const dy = overBottom - overTop;
        if (dx !== 0 || dy !== 0) {
          map.panBy([dx, dy], { duration: 250 });
        }
      });
    });

    return root;
  }, []);
  // Deps rỗng: hàm chỉ đọc refs (gatewaysRef, mapRef) và module-level
  // constants (STATUS_COLOR, STATUS_LABEL, t) — không có reactive state.

  /**
   * Pure marker-drawing helper — không phụ thuộc state, chỉ dùng refs.
   * Cho phép gọi từ effect mà không gây stale closure.
   * @type {(lat: number, lng: number, prediction: import("../api/client.js").PredictionT, sfUsed: number, isAuto: boolean, txPowerUsed: number, environmentUsed: "outdoor" | "indoor", label?: string | null) => void}
   */
  const drawSearchMarker = useCallback((lat, lng, prediction, sfUsed, isAuto, txPowerUsed, environmentUsed, label) => {
    const map = mapRef.current;
    if (!map) return;

    // Marker + line màu theo RSSI bin (SURVEY_RSSI_BINS) — khớp legend chip
    // ở góc dưới-trái. Popup badge bên trong vẫn dùng STATUS_COLOR vì đó là
    // semantic label "Phủ tốt/yếu", không phải RSSI value.
    const color = colorForRssi(prediction.rssi_dbm);
    const el = document.createElement("div");
    el.style.width = PREDICT_MARKER_STYLE.size;
    el.style.height = PREDICT_MARKER_STYLE.size;
    el.style.borderRadius = "50% 50% 50% 0";
    el.style.transform = "rotate(-45deg)";
    el.style.background = color;
    el.style.border = PREDICT_MARKER_STYLE.border;
    el.style.boxShadow = PREDICT_MARKER_STYLE.boxShadow;

    const popup = new maplibregl.Popup({
      offset: 16,
      maxWidth: "380px",
    }).setDOMContent(
      buildPopupNode(lat, lng, prediction, sfUsed, isAuto, txPowerUsed, environmentUsed, label),
    );
    // Toggle "Xem chi tiết kỹ thuật" trong buildPopupNode ẩn legend khi expand;
    // nếu user đóng popup lúc đang expand → restore legend ở đây.
    popup.on("close", () => {
      const legendEl = /** @type {HTMLElement | null} */ (
        document.querySelector("[data-map-legend]")
      );
      if (legendEl) legendEl.style.visibility = "";
    });

    const marker = new maplibregl.Marker({ element: el, anchor: "bottom" })
      .setLngLat([lng, lat])
      .setPopup(popup)
      .addTo(map);
    marker.togglePopup();
    searchMarkersRef.current.push(marker);
    setPredictMarkerCount(searchMarkersRef.current.length);

    // Vẽ line nối điểm dự đoán → serving gateway, cùng màu badge trạng thái.
    // Bỏ qua nếu BE không gán gateway (serving_gateway_id null) hoặc gateway
    // chưa load (gatewaysRef rỗng — race với deep-link predict khi mới mount).
    // Cũng bỏ qua khi coverage_status="no_coverage": BE vẫn trả serving GW =
    // candidate ít tệ nhất trong 30 km cho debug, nhưng UX-wise không nên vẽ
    // line "kết nối" vì gateway đó thật ra không decode được.
    const gw =
      prediction.serving_gateway_id && prediction.coverage_status !== "no_coverage"
        ? gatewaysRef.current.find((x) => x.id === prediction.serving_gateway_id)
        : null;
    if (gw) {
      searchLineFeaturesRef.current.push({
        type: "Feature",
        geometry: {
          type: "LineString",
          coordinates: [
            [lng, lat],
            [gw.longitude, gw.latitude],
          ],
        },
        properties: { color },
      });
      const src = map.getSource(PREDICT_LINES_SOURCE_ID);
      if (src && "setData" in src) {
        /** @type {maplibregl.GeoJSONSource} */ (src).setData({
          type: "FeatureCollection",
          features: searchLineFeaturesRef.current,
        });
      }
    }

    map.flyTo({ center: [lng, lat] });
  }, [buildPopupNode]);
  // Phụ thuộc buildPopupNode (đã stable nhờ useCallback ở trên).

  // Pin tạm: dot xám neutral, no rotation. Hiển thị tại vị trí user pick để xác
  // nhận trước khi predict. Zoom 16 ≈ ~500m radius view tại vĩ độ Đà Nẵng.
  const showPickMarker = useCallback(
    /** @param {number} lat @param {number} lng */
    (lat, lng) => {
      const map = mapRef.current;
      if (!map) return;
      if (pickMarkerRef.current) {
        pickMarkerRef.current.setLngLat([lng, lat]);
      } else {
        const el = document.createElement("div");
        el.style.width = "14px";
        el.style.height = "14px";
        el.style.borderRadius = "50%";
        el.style.background = "#334155";
        el.style.border = "3px solid white";
        el.style.boxShadow = "0 0 6px rgba(0,0,0,0.5)";
        pickMarkerRef.current = new maplibregl.Marker({
          element: el,
          anchor: "center",
        })
          .setLngLat([lng, lat])
          .addTo(map);
      }
      map.flyTo({ center: [lng, lat], zoom: 16 });
    },
    [],
  );

  const hidePickMarker = useCallback(() => {
    if (pickMarkerRef.current) {
      pickMarkerRef.current.remove();
      pickMarkerRef.current = null;
    }
  }, []);

  const clearAllSearchMarkers = useCallback(() => {
    for (const m of searchMarkersRef.current) m.remove();
    searchMarkersRef.current = [];
    searchLineFeaturesRef.current = [];
    const src = mapRef.current?.getSource(PREDICT_LINES_SOURCE_ID);
    if (src && "setData" in src) {
      /** @type {maplibregl.GeoJSONSource} */ (src).setData({
        type: "FeatureCollection",
        features: [],
      });
    }
    setPredictMarkerCount(0);
    hidePickMarker();
    setPickedCoords(null);
  }, [hidePickMarker]);

  // Initial URL deep-link: predict 1 lần sau khi map mount.
  // Chỉ tab "Dự đoán điểm" mới tiêu thụ URL state — tab "Bản đồ điểm đo" và
  // "Bản đồ phủ sóng" không hiển thị popup "Vị trí từ URL" kể cả khi URL có
  // ?lat=&lng= (do tab predict ghi sẵn từ lần dự đoán trước).
  useEffect(() => {
    if (mode !== "predict") return;
    // Gate by mapLoaded: drawSearchMarker dùng mapRef.current, silent-return
    // nếu map chưa load → marker bị mất khi tab-switch (URL vẫn còn ?lat=&lng=
    // nên effect fire ngay, nhưng map chưa sẵn sàng).
    if (!mapLoaded) return;
    if (deepLinkConsumedRef.current) return;
    const url = initialUrlRef.current;
    if (!url) return;
    deepLinkConsumedRef.current = true;
    let cancelled = false;
    predictCoverage({
      latitude: url.lat,
      longitude: url.lng,
      spreading_factor: DEFAULT_SF,
      frequency_mhz: DEFAULT_FREQ_MHZ,
    })
      .then((prediction) => {
        if (cancelled) return;
        // Deep-link không serialize tx_power/environment → fallback defaults
        // (14 dBm outdoor) khớp BE behavior khi field None trong PredictRequest.
        drawSearchMarker(url.lat, url.lng, prediction, DEFAULT_SF, true, DEFAULT_TX_POWER_DBM, "outdoor");
        // Flow predict thường zoom 16 qua showPickMarker; deep-link không đi
        // qua bước đó nên zoom thủ công cho khớp UX (gateway link cũng dùng 16).
        mapRef.current?.flyTo({ center: [url.lng, url.lat], zoom: 16 });
      })
      .catch((e) => {
        console.error("Deep-link predict failed:", e);
      });
    return () => {
      cancelled = true;
    };
  }, [mode, mapLoaded, drawSearchMarker]);

  /**
   * Address sub-tab callback: BE trả lat/lng + prediction nhưng FE chỉ dùng
   * lat/lng để pin tạm + zoom 500m. Prediction discard — user phải bấm
   * "Dự đoán" ở sub-tab "Click chọn" để xem kết quả (cho phép chọn lại
   * outdoor/indoor trước khi predict). Auto-switch sub-tab để show nút.
   *
   * @param {{
   *   lat: number,
   *   lng: number,
   *   displayName: string,
   *   prediction: import("../api/client.js").PredictionT,
   * }} r
   */
  const handleAddressResolved = useCallback(
    (r) => {
      setPickedCoords({ lat: r.lat, lng: r.lng });
      setPredictError(null);
      showPickMarker(r.lat, r.lng);
      setPredictSubTab("single");
    },
    [showPickMarker],
  );

  // Nút "Dùng GPS": navigator.geolocation.getCurrentPosition → setPickedCoords
  // + showPickMarker (đã flyTo zoom 16). Map error.code → string Việt:
  //   1 = PERMISSION_DENIED (user từ chối).
  //   2 = POSITION_UNAVAILABLE (GPS off / signal yếu).
  //   3 = TIMEOUT (vượt 15s).
  // enableHighAccuracy=true để ưu tiên GPS thực thay vì IP geolocation;
  // maximumAge=60000 reuse cache vị trí cũ nếu user spam click. HTTPS-only
  // API → localhost dev OK, deploy phải https (đã có tunnel/CDN).
  const tPredict = strings.coverageMap.predictPanel;
  const handleUseGps = useCallback(() => {
    if (typeof navigator === "undefined" || !navigator.geolocation) {
      setGpsError(tPredict.gpsUnsupported);
      return;
    }
    setGpsBusy(true);
    setGpsError(null);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const lat = pos.coords.latitude;
        const lng = pos.coords.longitude;
        setPickedCoords({ lat, lng });
        setPredictError(null);
        showPickMarker(lat, lng);
        setGpsBusy(false);
      },
      (err) => {
        const msg =
          err.code === 1
            ? tPredict.gpsPermissionDenied
            : err.code === 2
              ? tPredict.gpsUnavailable
              : err.code === 3
                ? tPredict.gpsTimeout
                : tPredict.gpsGenericError;
        setGpsError(msg);
        setGpsBusy(false);
      },
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 60000 },
    );
  }, [showPickMarker, tPredict]);

  /**
   * Predict mode: chạy prediction từ pickedCoords + environment, vẽ marker
   * + popup dual-layer. SF luôn auto (BE chọn recommended_sf), TX power luôn
   * 14 dBm (AS923-2 cap).
   */
  async function onPredictSubmit() {
    if (!pickedCoords || predictBusy) return;
    const { lat, lng } = pickedCoords;
    setPredictBusy(true);
    setPredictError(null);
    try {
      const prediction = await predictCoverage({
        latitude: lat,
        longitude: lng,
        spreading_factor: DEFAULT_SF,
        frequency_mhz: DEFAULT_FREQ_MHZ,
        tx_power_dbm: DEFAULT_TX_POWER_DBM,
        environment,
      });
      drawSearchMarker(
        lat,
        lng,
        prediction,
        DEFAULT_SF,
        true,
        DEFAULT_TX_POWER_DBM,
        environment,
      );
      hidePickMarker();
      writeUrlState(lat, lng);
    } catch (e) {
      console.error("Predict submit failed:", e);
      setPredictError(t.predictPanel.error);
    } finally {
      setPredictBusy(false);
    }
  }

  return (
    <div className="h-full w-full">
      {/* Pad maplibre top-right control container (pt-10 = 40px) khi tab
          points hoặc heatmap để chừa chỗ cho icon view-mode toggle ngồi trên
          zoom. Tab "predict" không có toggle nên giữ control sát mép. */}
      <div
        className={
          mode === "points" || mode === "heatmap"
            ? "relative h-full w-full overflow-hidden [&_.maplibregl-ctrl-top-right]:pt-10"
            : "relative h-full w-full overflow-hidden"
        }
      >
        <div ref={containerRef} className="h-full w-full" />

        {/* View-mode toggle — chỉ tab "points" mới có circles↔heatmap. Đặt
            top-right, anchor pixel-offset dưới NavigationControl của
            maplibre (3 nút zoom/compass ~95px + margin 10px). */}
        {mode === "points" && (
          <MapViewModeToggle
            mode={viewMode}
            onChange={(v) => setViewMode(/** @type {ViewMode} */ (v))}
            options={[
              { value: "points", label: t.viewModePicker.modes.points },
              { value: "heatmap", label: t.viewModePicker.modes.heatmap },
            ]}
          />
        )}

        {/* Tab "Bản đồ phủ sóng": tạm ẩn toggle minsf ↔ estimate — chỉ giữ
            estimate. Khi bật lại minsf: uncomment block dưới + restore conditional
            MinSFPanel ở dưới + restore import + state setters đã skip ở trên. */}
        {/*
        {mode === "heatmap" && (
          <MapViewModeToggle
            mode={coverageViewMode}
            onChange={(v) =>
              setCoverageViewMode(
                "" + v,
              )
            }
            options={[
              { value: "minsf", label: t.viewModePicker.modes.minsf },
              { value: "estimate", label: t.viewModePicker.modes.estimate },
            ]}
          />
        )}
        */}

        {/* Badge chuyến khảo sát trực tiếp: top-center khi realtime ON +
            contributor=me + mode=points. 2 trạng thái:
            - chưa Bắt đầu (running=false): nút Bắt đầu (disabled khi chưa
              chọn nguồn).
            - đang chạy (running=true): LIVE + counter + lastSeen + Kết thúc.
            Pointer-events-auto để nút click được. */}
        {realtimeEnabled && contributor === "me" && mode === "points" && (
          <div className="absolute top-3 left-1/2 z-10 -translate-x-1/2 flex items-center gap-3 rounded-md bg-white/95 px-3 py-1.5 text-xs shadow-md">
            {liveSessionRunning && (
              <div>
                <div className="flex items-center gap-1.5">
                  <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-red-500" />
                  <span className="font-semibold text-red-700">
                    {t.filters.realtime.liveBadge}
                  </span>
                </div>
                <div className="text-slate-600">
                  {t.filters.realtime.sessionCounter(sessionCounterRef.current)}
                </div>
                <div className="text-slate-500">
                  {t.filters.realtime.lastSeenLabel}:{" "}
                  {formatLastSeenLabel(
                    lastSeenAt,
                    nowTick,
                    t.filters.realtime,
                  )}
                </div>
              </div>
            )}
            {liveSessionRunning ? (
              <button
                type="button"
                onClick={handleEndSession}
                disabled={endingBusy}
                className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white shadow-sm hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
              >
                {endingBusy
                  ? t.filters.realtime.ending
                  : t.filters.realtime.endButton}
              </button>
            ) : (
              <button
                type="button"
                onClick={handleStartSession}
                disabled={liveSessionSourceId === null}
                title={
                  liveSessionSourceId === null
                    ? t.filters.realtime.startNeedSourceHint
                    : undefined
                }
                className="rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white shadow-sm hover:bg-emerald-700 disabled:cursor-not-allowed disabled:bg-slate-400"
              >
                {t.filters.realtime.startButton}
              </button>
            )}
          </div>
        )}

        {/* Container anchor cả trên + dưới. `pointer-events-none` để vùng
            trống (khi panel collapsed) không chặn map click; children tự bật
            lại. `right-14` (=56px) chừa chỗ cho NavigationControl +
            view-mode toggle ở top-right không bị panel che.
            Bottom buffer chừa zone cho MapLegend (bottom-10 = 40px + ~120px
            chip+counts) — bump lên `bottom-48` (=192px) mobile / `md:bottom-64`
            (=256px) để filter panel mở full không bị legend đè ở mép dưới. */}
        <div className="pointer-events-none absolute z-10 flex flex-col gap-2 top-1 bottom-48 left-2 right-14 [&>*]:pointer-events-auto md:top-3 md:bottom-64 md:left-3 md:right-auto">
          {mode === "predict" ? (
            !predictPanelOpen ? (
              <button
                type="button"
                onClick={() => setPredictPanelOpen(true)}
                aria-label={t.predictPanel.toggle.open}
                title={t.predictPanel.toggle.open}
                className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-slate-200 bg-white text-slate-700 shadow-sm hover:bg-slate-50 hover:text-slate-900 focus:outline-none focus:ring-1 focus:ring-slate-500"
              >
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  viewBox="0 0 20 20"
                  fill="currentColor"
                  className="h-5 w-5"
                  aria-hidden
                >
                  <path
                    fillRule="evenodd"
                    d="M9.69 18.933l.003.001C9.89 19.02 10 19 10 19s.11.02.308-.066l.002-.001.006-.003.018-.008a5.741 5.741 0 00.281-.14c.186-.096.446-.24.757-.433.62-.384 1.445-.966 2.274-1.765C15.302 14.988 17 12.493 17 9A7 7 0 103 9c0 3.492 1.698 5.988 3.355 7.584a13.731 13.731 0 002.273 1.765 11.842 11.842 0 00.976.544l.062.029.018.008.006.003zM10 11.25a2.25 2.25 0 100-4.5 2.25 2.25 0 000 4.5z"
                    clipRule="evenodd"
                  />
                </svg>
              </button>
            ) : (
              <div className="flex max-h-full min-h-0 w-full flex-col overflow-y-auto rounded-md border border-slate-200 bg-white text-xs text-slate-700 shadow-sm md:w-64">
                <div className="sticky top-0 z-10 flex items-center justify-between border-b border-slate-200 bg-white px-3 py-2">
                  <span className="text-sm font-semibold text-slate-900">
                    {t.predictPanel.title}
                  </span>
                  <button
                    type="button"
                    onClick={() => setPredictPanelOpen(false)}
                    aria-label={t.predictPanel.toggle.close}
                    className="rounded p-1 text-slate-500 hover:bg-slate-100 hover:text-slate-900 focus:outline-none focus:ring-1 focus:ring-slate-500"
                  >
                    <svg
                      xmlns="http://www.w3.org/2000/svg"
                      viewBox="0 0 20 20"
                      fill="currentColor"
                      className="h-4 w-4"
                      aria-hidden
                    >
                      <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
                    </svg>
                  </button>
                </div>
                <div className="space-y-2 px-3 py-2">
                  <div className="flex gap-1 rounded-md bg-slate-100 p-0.5">
                    <button
                      type="button"
                      onClick={() => setPredictSubTab("single")}
                      className={`flex-1 rounded px-2 py-1 text-[11px] font-medium transition ${
                        predictSubTab === "single"
                          ? "bg-white text-slate-900 shadow-sm"
                          : "text-slate-600 hover:text-slate-900"
                      }`}
                    >
                      {t.predictPanel.subTabs.single}
                    </button>
                    <button
                      type="button"
                      onClick={() => setPredictSubTab("address")}
                      className={`flex-1 rounded px-2 py-1 text-[11px] font-medium transition ${
                        predictSubTab === "address"
                          ? "bg-white text-slate-900 shadow-sm"
                          : "text-slate-600 hover:text-slate-900"
                      }`}
                    >
                      {t.predictPanel.subTabs.address}
                    </button>
                  </div>

                  {predictSubTab === "single" ? (
                    <>
                      <div className="grid grid-cols-2 gap-x-2 gap-y-1 text-[11px]">
                        <div className="text-slate-500">
                          {t.predictPanel.latLabel}
                        </div>
                        <div className="text-right font-mono text-slate-900">
                          {pickedCoords
                            ? pickedCoords.lat.toFixed(5)
                            : t.predictPanel.empty}
                        </div>
                        <div className="text-slate-500">
                          {t.predictPanel.lngLabel}
                        </div>
                        <div className="text-right font-mono text-slate-900">
                          {pickedCoords
                            ? pickedCoords.lng.toFixed(5)
                            : t.predictPanel.empty}
                        </div>
                      </div>

                      <fieldset>
                        <legend
                          className="text-xs font-medium text-slate-700"
                          title={t.environmentPicker.hint}
                        >
                          {t.environmentPicker.label}
                        </legend>
                        <div className="mt-1 flex flex-col gap-0.5">
                          {t.environmentPicker.options.map((opt) => (
                            <label
                              key={opt.value}
                              className="flex items-center gap-1.5 text-[11px] text-slate-700"
                            >
                              <input
                                type="radio"
                                name="environment-picker"
                                value={opt.value}
                                checked={environment === opt.value}
                                onChange={() =>
                                  setEnvironment(
                                    /** @type {"outdoor" | "indoor"} */ (opt.value),
                                  )
                                }
                              />
                              {opt.label}
                            </label>
                          ))}
                        </div>
                      </fieldset>

                      <button
                        type="button"
                        onClick={handleUseGps}
                        disabled={gpsBusy}
                        className="flex w-full items-center justify-center gap-1.5 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 shadow-sm transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        <svg
                          xmlns="http://www.w3.org/2000/svg"
                          viewBox="0 0 20 20"
                          fill="currentColor"
                          className="h-3.5 w-3.5"
                          aria-hidden
                        >
                          <path
                            fillRule="evenodd"
                            d="M10 2a.75.75 0 01.75.75v.764a6.5 6.5 0 015.736 5.736h.764a.75.75 0 010 1.5h-.764a6.5 6.5 0 01-5.736 5.736v.764a.75.75 0 01-1.5 0v-.764a6.5 6.5 0 01-5.736-5.736H2.75a.75.75 0 010-1.5h.764A6.5 6.5 0 019.25 3.514V2.75A.75.75 0 0110 2zM5 10a5 5 0 1010 0 5 5 0 00-10 0zm5-2a2 2 0 100 4 2 2 0 000-4z"
                            clipRule="evenodd"
                          />
                        </svg>
                        {gpsBusy
                          ? t.predictPanel.gpsLocating
                          : t.predictPanel.gpsButton}
                      </button>

                      {gpsError && (
                        <div className="text-[11px] text-red-600">
                          {gpsError}
                        </div>
                      )}

                      {!pickedCoords && (
                        <div className="text-[11px] leading-snug text-slate-500">
                          {t.predictPanel.hint}
                        </div>
                      )}

                      <button
                        type="button"
                        onClick={onPredictSubmit}
                        disabled={!pickedCoords || predictBusy}
                        className="w-full rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white shadow-sm transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300"
                      >
                        {predictBusy
                          ? t.predictPanel.submitting
                          : t.predictPanel.submit}
                      </button>

                      <button
                        type="button"
                        onClick={clearAllSearchMarkers}
                        disabled={predictMarkerCount === 0}
                        className="w-full rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 shadow-sm transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:border-slate-200 disabled:text-slate-400"
                      >
                        {t.predictPanel.clearAll}
                        {predictMarkerCount > 0 ? ` (${predictMarkerCount})` : ""}
                      </button>

                      {predictError && (
                        <div className="text-[11px] text-red-600">
                          {predictError}
                        </div>
                      )}
                    </>
                  ) : (
                    <AddressLookupPanel
                      onResolved={handleAddressResolved}
                      markerCount={predictMarkerCount}
                      onClear={clearAllSearchMarkers}
                    />
                  )}
                </div>
              </div>
            )
          ) : mode === "points" ? (
            // Layout 2 cột: icons-column (left) stacked vertical, panels-column
            // (right) render body khi tương ứng open. Tách icon ra cột riêng
            // để mở 1 panel không push icon của panel còn lại xuống — tránh
            // layout shift gây nhầm khi click qua lại.
            <div className="flex max-h-full min-h-0 items-start gap-2">
              <div className="flex flex-col gap-2 shrink-0">
                <PointsFilterToggleBtn
                  open={pointsFilterOpen}
                  onToggle={() => setPointsFilterOpen((v) => !v)}
                />
                {/* Realtime toggle luôn hiển thị (kể cả guest). Body kiểm
                    tra login trước khi cho tick "Bật theo dõi trực tiếp". */}
                <RealtimeToggleBtn
                  open={realtimePanelOpen}
                  onToggle={() => setRealtimePanelOpen((v) => !v)}
                  realtimeEnabled={realtimeEnabled}
                />
              </div>
              {(pointsFilterOpen || realtimePanelOpen) && (
                <div className="flex max-h-full min-h-0 min-w-0 flex-1 flex-col gap-2 md:w-64 md:flex-initial">
                  {pointsFilterOpen && (
                    <PointsFilterBody
                      user={user}
                      contributor={contributor}
                      onContributorChange={setContributor}
                      linkedSourceId={linkedSourceId}
                      onLinkedSourceChange={setLinkedSourceId}
                      deviceId={deviceId}
                      onDeviceIdChange={setDeviceId}
                      sourceType={sourceType}
                      onSourceTypeChange={setSourceType}
                      sfList={sfList}
                      onSfListChange={setSfList}
                      rssiRange={rssiRange}
                      onRssiRangeChange={setRssiRange}
                      snrRange={snrRange}
                      onSnrRangeChange={setSnrRange}
                      timeRange={timeRange}
                      onTimeRangeChange={setTimeRange}
                      connectionLinesEnabled={showConnectionLines}
                      onConnectionLinesEnabledChange={setShowConnectionLines}
                    />
                  )}
                  {realtimePanelOpen && (
                    <RealtimeBody
                      user={user}
                      onRequestLogin={onRequestLogin}
                      realtimeEnabled={realtimeEnabled}
                      onRealtimeEnabledChange={(v) => {
                        setRealtimeEnabled(v);
                        // Live session start effect + badge UI gate
                        // `contributor === "me"` — auto-switch khi bật để
                        // tránh silent fail nếu user đang xem community/all.
                        if (v) setContributor("me");
                        // Untick mid-session: clear running để re-tick không
                        // tạo batch mới chồng lên batch cũ chưa close (batch
                        // cũ vẫn còn DB, user xoá tay ở "Lịch sử upload").
                        else setLiveSessionRunning(false);
                      }}
                      autoFollowEnabled={autoFollowEnabled}
                      onAutoFollowEnabledChange={setAutoFollowEnabled}
                      liveOnlyEnabled={liveOnlyEnabled}
                      onLiveOnlyEnabledChange={setLiveOnlyEnabled}
                      liveSessionSourceId={liveSessionSourceId}
                      onLiveSessionSourceIdChange={setLiveSessionSourceId}
                      liveSessionActive={liveSessionRunning}
                    />
                  )}
                </div>
              )}
            </div>
          ) : mode === "heatmap" ? (
            // Tab "Bản đồ phủ sóng": tạm ẩn minsf — chỉ render EstimatePanel.
            // Khi bật lại, restore conditional `coverageViewMode === "minsf"`
            // + unwrap toggle ở trên.
            <EstimatePanel
              gateways={gatewaysQ.data?.items ?? []}
              selectedCode={estimateGatewayCode}
              onChange={setEstimateGatewayCode}
              loadingError={estimateLoadError}
            />
          ) : null}

        </div>

        {/* Legend cố định ở góc dưới trái — chừa chỗ cho ScaleControl của
            maplibre (mounted ở "bottom-left", cao ~24px). Ẩn ở tab "Bản đồ
            phủ sóng" vì RSSI band không áp dụng cho min-SF map (đã có
            legend riêng trong MinSFPanel). */}
        {mode !== "heatmap" && (
          <div className="absolute bottom-10 left-2 z-10" data-map-legend>
            <MapLegend
              gatewayCount={gatewaysQ.data?.total}
              surveyCount={mode === "points" ? surveysQ.data?.total : null}
            />
          </div>
        )}

        {(gatewaysQ.isError || surveysQ.isError) && (
          <div className="absolute right-3 top-3 z-10 max-w-sm rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800 shadow-md">
            {t.apiError}
          </div>
        )}

        {tileError && (
          <div className="absolute bottom-3 right-3 z-10 max-w-sm rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900 shadow-md">
            <div className="font-semibold">{t.tileErrorTitle}</div>
            <div className="mt-1">{tileError}</div>
          </div>
        )}

        {endModal && (
          <AlertModal
            title={endModal.title}
            body={endModal.body}
            onClose={() => setEndModal(null)}
          />
        )}
      </div>
    </div>
  );
}