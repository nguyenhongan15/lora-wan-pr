// @ts-check
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useQuery } from "@tanstack/react-query";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

import {
  listGateways,
  listSurveyTraining,
  predictCoverage,
} from "../api/client.js";
import { getUser, subscribe as subscribeAuth } from "../auth/store.js";
import {
  formatBitrate,
  formatTimeOnAir,
  maxPayloadBytes,
} from "../lora/datarate.js";
import { strings } from "../strings.js";
import { MapLegend } from "./MapLegend.jsx";
import { MapViewModeToggle } from "./MapViewModeToggle.jsx";
import { PointsFilterPanel } from "./filters/PointsFilterPanel.jsx";
import {
  BASEMAP_STYLE,
  DEFAULT_FREQ_MHZ,
  DEFAULT_SF,
  DEFAULT_SORT_BY,
  DEFAULT_SORT_ORDER,
  GATEWAY_MARKER_STYLE,
  INITIAL_CENTER,
  INITIAL_ZOOM,
  MARGIN_BAR_RANGE,
  PREDICT_MARKER_STYLE,
  SF_OPTIONS,
  STATUS_COLOR,
  STATUS_COLOR_FALLBACK,
  SURVEY_CIRCLE_PAINT,
} from "./CoverageMap.config.js";
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
      },
    })),
  };
}

/** @typedef {number | "auto"} SfValue */

/**
 * @returns {{ lat: number, lng: number, sf: SfValue | null } | null}
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
  const sfRaw = p.get("sf");
  /** @type {SfValue | null} */
  let sf = null;
  if (sfRaw === "auto") {
    sf = "auto";
  } else if (sfRaw != null) {
    const n = Number(sfRaw);
    if (Number.isInteger(n) && n >= 7 && n <= 12) sf = n;
  }
  return { lat, lng, sf };
}

/**
 * @param {number} lat
 * @param {number} lng
 * @param {SfValue} sf
 */
function writeUrlState(lat, lng, sf) {
  if (typeof window === "undefined") return;
  const p = new URLSearchParams(window.location.search);
  p.set("lat", lat.toFixed(6));
  p.set("lng", lng.toFixed(6));
  p.set("sf", String(sf));
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
 *   sortConfig: {
 *     sortBy: import("../api/client.js").SortBy,
 *     sortOrder: import("../api/client.js").SortOrder,
 *   },
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
    sortConfig: {
      sortBy: DEFAULT_SORT_BY,
      sortOrder: DEFAULT_SORT_ORDER,
    },
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

  const sb = p.get("sort_by");
  if (sb === "rssi" || sb === "snr" || sb === "timestamp") {
    def.sortConfig.sortBy = sb;
  }
  const so = p.get("sort_order");
  if (so === "asc" || so === "desc") def.sortConfig.sortOrder = so;

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

  if (state.sortConfig.sortBy !== DEFAULT_SORT_BY) {
    p.set("sort_by", state.sortConfig.sortBy);
  } else {
    p.delete("sort_by");
  }
  if (state.sortConfig.sortOrder !== DEFAULT_SORT_ORDER) {
    p.set("sort_order", state.sortConfig.sortOrder);
  } else {
    p.delete("sort_order");
  }
  // rank_from / rank_to không còn quản lý từ UI — clean URL legacy keys khi
  // user vào lại trang sau khi đã có cửa sổ rank cũ.
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

/** @typedef {import("./MapViewModeToggle.jsx").ViewMode} ViewMode */

// Predict-line GeoJSON source — line layer nối điểm dự đoán → serving gateway.
// 1 source duy nhất cho cả tab "Dự đoán điểm": mỗi lần predict push 1 feature,
// `clearAllSearchMarkers` reset features = []. Màu line đọc từ feature property
// `color` (set runtime từ STATUS_COLOR theo coverage_status).
const PREDICT_LINES_SOURCE_ID = "predict-lines-src";
const PREDICT_LINES_LAYER_ID = "predict-lines";

/* ─────────────────────────────────────────────────────────────────────────
 * Popup vanilla-DOM helpers (predict marker)
 *
 * Maplibre popup nhận DOM node thuần — không phải React tree — nên các block
 * UI bidirectional viết trực tiếp bằng `document.createElement`. Tách ra
 * module-level để buildPopupNode đọc được, đồng thời tránh re-create function
 * mỗi render.
 * ─────────────────────────────────────────────────────────────────────── */

/**
 * Pill nút thắt 2 chiều cạnh status badge ở Layer 1.
 * No-op nếu BE trả response cũ (bottleneck === undefined).
 * @param {HTMLElement} parent
 * @param {("uplink" | "downlink" | "both_ok") | undefined} bn
 */
function appendBottleneckPill(parent, bn) {
  if (!bn) return;
  /** @type {Record<string, string>} */
  const labels = t.popup.bottleneckShort;
  const label = labels[bn];
  if (!label) return;
  const balanced = bn === "both_ok";
  const bg = balanced ? "#ecfdf5" : "#fffbeb";
  const fg = balanced ? "#047857" : "#b45309";
  const border = balanced ? "#a7f3d0" : "#fde68a";
  const pill = document.createElement("span");
  pill.style.cssText = `display:inline-block;background:${bg};color:${fg};border:1px solid ${border};padding:1px 6px;border-radius:9999px;font-weight:500;font-size:10px`;
  pill.textContent = label;
  parent.appendChild(pill);
}

/**
 * Margin bar: width tỉ lệ với margin trong khoảng MARGIN_BAR_RANGE,
 * màu nền theo STATUS_COLOR[status]. Numeric label nằm cạnh thanh bar.
 * @param {number} marginDb
 * @param {string} status
 * @returns {HTMLDivElement}
 */
function buildMarginCell(marginDb, status) {
  const { min, max } = MARGIN_BAR_RANGE;
  const pct = Math.max(0, Math.min(100, ((marginDb - min) / (max - min)) * 100));
  const color = STATUS_COLOR[status] ?? STATUS_COLOR_FALLBACK;

  const wrap = document.createElement("div");
  wrap.style.cssText = "display:flex;align-items:center;gap:4px;min-width:96px";

  const num = document.createElement("span");
  num.style.cssText =
    "font-variant-numeric:tabular-nums;color:#334155;min-width:48px";
  num.textContent = t.popup.bidir.marginValue(marginDb);
  wrap.appendChild(num);

  const track = document.createElement("div");
  track.style.cssText =
    "flex:1;height:6px;background:#f1f5f9;border-radius:3px;overflow:hidden";
  const fill = document.createElement("div");
  fill.style.cssText = `width:${pct.toFixed(1)}%;height:100%;background:${color}`;
  track.appendChild(fill);
  wrap.appendChild(track);

  return wrap;
}

/**
 * @param {string} label
 * @param {import("../api/client.js").LinkBudgetT} lb
 * @returns {HTMLTableRowElement}
 */
function buildBidirRow(label, lb) {
  const tr = document.createElement("tr");

  const tdLabel = document.createElement("td");
  tdLabel.style.cssText = "padding:3px 4px;color:#334155;white-space:nowrap";
  tdLabel.textContent = label;
  tr.appendChild(tdLabel);

  const tdRssi = document.createElement("td");
  tdRssi.style.cssText =
    "padding:3px 4px;font-variant-numeric:tabular-nums;white-space:nowrap";
  tdRssi.textContent = `${lb.rssi_dbm.toFixed(1)} dBm`;
  tr.appendChild(tdRssi);

  const tdSnr = document.createElement("td");
  tdSnr.style.cssText =
    "padding:3px 4px;font-variant-numeric:tabular-nums;white-space:nowrap";
  tdSnr.textContent = `${lb.snr_db.toFixed(1)} dB`;
  tr.appendChild(tdSnr);

  const tdMargin = document.createElement("td");
  tdMargin.style.cssText = "padding:3px 4px";
  tdMargin.appendChild(buildMarginCell(lb.margin_db, lb.status));
  tr.appendChild(tdMargin);

  return tr;
}

/**
 * Section UL/DL trong Layer 2 — bảng 2×4 (UL/DL × label/RSSI/SNR/Margin)
 * với margin bar visual. Chỉ append khi BE trả đủ uplink + downlink.
 * @param {HTMLElement} parent
 * @param {import("../api/client.js").LinkBudgetT} ul
 * @param {import("../api/client.js").LinkBudgetT} dl
 */
function appendBidirectionalSection(parent, ul, dl) {
  const wrap = document.createElement("div");
  wrap.style.cssText =
    "margin-top:8px;padding-top:6px;border-top:1px dashed #e2e8f0";

  const head = document.createElement("div");
  head.style.cssText =
    "font-weight:600;color:#0f172a;margin-bottom:4px;font-size:11px";
  head.textContent = t.popup.bidir.sectionTitle;
  wrap.appendChild(head);

  const table = document.createElement("table");
  table.style.cssText = "width:100%;border-collapse:collapse;font-size:11px";

  const thead = document.createElement("thead");
  thead.innerHTML =
    `<tr style="color:#64748b;text-align:left">
       <th style="padding:2px 4px;font-weight:500"></th>
       <th style="padding:2px 4px;font-weight:500">${t.popup.bidir.colRssi}</th>
       <th style="padding:2px 4px;font-weight:500">${t.popup.bidir.colSnr}</th>
       <th style="padding:2px 4px;font-weight:500">${t.popup.bidir.colMargin}</th>
     </tr>`;
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  tbody.appendChild(buildBidirRow(t.popup.bidir.ul, ul));
  tbody.appendChild(buildBidirRow(t.popup.bidir.dl, dl));
  table.appendChild(tbody);

  wrap.appendChild(table);
  parent.appendChild(wrap);
}

/**
 * Block thông số đường truyền dữ liệu LoRaWAN — bitrate, time-on-air (23 B),
 * max payload bytes. Pure function của SF (BW=125 kHz, CR=4/5, AS923-2 DT=0).
 * Tách section vì khác bản chất với phủ sóng — đây là "truyền data nhanh hay
 * chậm khi đã có sóng".
 * @param {HTMLElement} parent
 * @param {number} sf
 */
function appendDataLinkSection(parent, sf) {
  const wrap = document.createElement("div");
  wrap.style.cssText =
    "margin-top:8px;padding-top:6px;border-top:1px dashed #e2e8f0;font-size:11px";
  wrap.innerHTML =
    `<div style="font-weight:600;color:#0f172a;margin-bottom:4px">${t.popup.dataLink.sectionTitle}</div>` +
    `<div>${t.popup.dataLink.bitrate}: <strong>${formatBitrate(sf)}</strong></div>` +
    `<div>${t.popup.dataLink.timeOnAir}: <strong>${formatTimeOnAir(sf)}</strong></div>` +
    `<div>${t.popup.dataLink.maxPayload}: <strong>${t.popup.dataLink.maxPayloadValue(maxPayloadBytes(sf))}</strong></div>`;
  parent.appendChild(wrap);
}

/**
 * Nút copy permalink (`?lat=&lng=&sf=`) — feedback "Đã copy!" 2s rồi reset.
 * Clipboard API không có ở SSR → guard `window` tồn tại.
 * @param {HTMLElement} parent
 * @param {number} lat
 * @param {number} lng
 * @param {SfValue} sf
 */
function appendCopyLinkButton(parent, lat, lng, sf) {
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
    url.searchParams.set("sf", String(sf));
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


/**
 * @param {{ mode?: "points" | "heatmap" | "predict" }} props
 *   mode === "points": render survey points (mặc định, tab "Bản đồ điểm đo").
 *     Click bản đồ → auto-predict 1 điểm + vẽ marker.
 *   mode === "heatmap": survey layer tắt — placeholder cho heatmap raster
 *     (Phase 2 sẽ thêm raster source khi tile endpoint sẵn sàng).
 *   mode === "predict": survey layer tắt — chỉ hiển thị gateway. Click bản đồ
 *     lấy toạ độ vào panel; user bấm "Dự đoán" để chạy prediction + vẽ marker.
 */
export function CoverageMap({ mode = "points" }) {
  const containerRef = useRef(/** @type {HTMLDivElement | null} */ (null));
  const mapRef = useRef(/** @type {maplibregl.Map | null} */ (null));
  const [mapLoaded, setMapLoaded] = useState(false);
  const gatewayMarkersRef = useRef(/** @type {maplibregl.Marker[]} */ ([]));
  // Mảng marker dự đoán — predict mỗi điểm append 1 marker, không xoá cũ.
  // Re-render qua bumpMarkerCount() để nút "Xoá tất cả" disable đúng lúc.
  const searchMarkersRef = useRef(/** @type {maplibregl.Marker[]} */ ([]));
  // Line features song song với searchMarkersRef — index N có thể không 1-1 vì
  // marker mà serving_gateway_id == null sẽ không có line. clearAll reset cả 2.
  const searchLineFeaturesRef = useRef(
    /** @type {GeoJSON.Feature<GeoJSON.LineString>[]} */ ([]),
  );
  const [predictMarkerCount, setPredictMarkerCount] = useState(0);
  const gatewaysRef = useRef(
    /** @type {import("../api/client.js").GatewayT[]} */ ([]),
  );
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
  const [sf, setSf] = useState(
    /** @returns {SfValue} */
    () => initialUrlRef.current?.sf ?? DEFAULT_SF,
  );
  // Default 14 dBm = AS923-2 cap; user có thể giảm để mô phỏng device pin yếu.
  const [txPowerDbm, setTxPowerDbm] = useState(/** @type {number} */ (14));
  // Default outdoor — thay đổi sẽ apply ITU-R P.2109 building entry loss BE-side.
  const [environment, setEnvironment] = useState(
    /** @type {"outdoor" | "indoor" | "indoor_deep"} */ ("outdoor"),
  );
  // Visualization mode cho tab "points": circle (RSSI) ↔ heatmap (mật độ).
  // Mặc định circle để không đổi behavior hiện tại. State chỉ ý nghĩa khi
  // mode === "points"; các tab khác không render toggle nên giá trị bị bỏ qua.
  const [viewMode, setViewMode] = useState(
    /** @type {ViewMode} */ ("points"),
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
  const [sortConfig, setSortConfig] = useState(
    () => initialPointsFilterRef.current.sortConfig,
  );

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
      sortConfig,
    });
  }, [mode, sfList, deviceId, rssiRange, snrRange, timeRange, sortConfig]);

  // Filter pipeline: backend nhận contributor/linked_source/source +
  // (sf_list, device_id, rssi/snr/time range, sort + rank window) và AND
  // tất cả. Window rank thay thế `limit` cũ — RankFilter clamp ≤ 5000.
  const linkedSourceForQuery = contributor === "me" ? linkedSourceId : null;
  const deviceIdForQuery = contributor === "me" ? deviceId : null;

  // Gateway list cũng đi qua resolver contributor — "Bản đồ của tôi" chỉ
  // hiện gateway từng phục vụ survey của user. Predict/heatmap luôn dùng
  // community (gateway là hạ tầng tham chiếu, không phụ thuộc user).
  const gatewayContributor = mode === "points" ? contributor : "community";
  const gatewayLinkedSource =
    mode === "points" ? linkedSourceForQuery : null;

  // Bbox=undefined → backend trả gateway/điểm đo toàn cầu. Initial map view
  // vẫn anchor ở Đà Nẵng (INITIAL_CENTER + INITIAL_ZOOM), user pan/zoom-out
  // để xem dữ liệu ngoài vùng.
  const gatewaysQ = useQuery({
    queryKey: ["gateways", gatewayContributor, gatewayLinkedSource],
    queryFn: () =>
      listGateways(undefined, {
        contributor: gatewayContributor,
        linkedSourceId: gatewayLinkedSource ?? undefined,
      }),
    retry: gatewayContributor === "community" ? 3 : false,
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
      sortConfig,
    ],
    queryFn: () =>
      listSurveyTraining(undefined, {
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
        sortBy: sortConfig.sortBy,
        sortOrder: sortConfig.sortOrder,
      }),
    enabled: mode === "points",
    // contributor !== community gặp 401/403 không nên retry tự động —
    // user thấy panel error 1 lần đỡ spam request.
    retry: contributor === "community" ? 3 : false,
  });

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
      setPickedCoords({ lat, lng });
      setPredictError(null);
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
      map.addLayer({
        id: SURVEYS_LAYER_ID,
        type: "circle",
        source: SURVEYS_SOURCE_ID,
        paint: /** @type {any} */ (SURVEY_CIRCLE_PAINT),
      });

      // Lazy popup — chỉ tạo khi click 1 circle, không pre-render 4k popup.
      map.on("click", SURVEYS_LAYER_ID, (e) => {
        const f = e.features?.[0];
        if (!f) return;
        const p = /** @type {{ rssi_dbm: number, snr_db: number, spreading_factor: number }} */ (
          f.properties
        );
        const geom = /** @type {GeoJSON.Point} */ (f.geometry);
        new maplibregl.Popup({ offset: 8 })
          .setLngLat(/** @type {[number, number]} */ (geom.coordinates))
          .setHTML(
            `<div style="font:12px/1.4 system-ui">
               <div><strong>${t.popup.surveyTitle}</strong></div>
               <div>${t.popup.rssiLabel}: ${Number(p.rssi_dbm).toFixed(1)} dBm</div>
               <div>${t.popup.snrLabel}: ${Number(p.snr_db).toFixed(1)} dB</div>
               <div>${t.popup.sfLabel(Number(p.spreading_factor))}</div>
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
      if (surveysQ.data) {
        const src = map.getSource(SURVEYS_SOURCE_ID);
        if (src && "setData" in src) {
          /** @type {maplibregl.GeoJSONSource} */ (src).setData(
            buildSurveyGeoJson(surveysQ.data.items),
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
  useEffect(() => {
    if (mode !== "points") return;
    const map = mapRef.current;
    if (!map || !surveysQ.data) return;
    if (!mapLoaded || !map.getSource(SURVEYS_SOURCE_ID)) return;
    /** @type {maplibregl.GeoJSONSource} */ (
      map.getSource(SURVEYS_SOURCE_ID)
    ).setData(buildSurveyGeoJson(surveysQ.data.items));
  }, [surveysQ.data, mode, mapLoaded]);

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

  // Gateway markers — HTML marker đơn giản 1 marker / gateway, popup
  // TX/gain/antenna/freq khi click. Clear & recreate khi data đổi.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !gatewaysQ.data || !mapLoaded) return;
    gatewaysRef.current = gatewaysQ.data.items;

    for (const m of gatewayMarkersRef.current) m.remove();
    gatewayMarkersRef.current = [];

    for (const g of gatewaysQ.data.items) {
      const el = document.createElement("div");
      el.style.cursor = "pointer";
      el.style.filter = "drop-shadow(0 1px 2px rgba(0,0,0,0.5))";
      // SVG teardrop pin: viewBox 24x32, tip ở (12, 32) = giữa-đáy SVG.
      // Path: nửa trên là vòm tròn r=12, nửa dưới thót dần xuống tip.
      // Icon tower-cell đặt trong vòm trên (scale 0.5 từ 24×24 → 12×12).
      el.innerHTML = `<svg width="${GATEWAY_MARKER_STYLE.width}" height="${GATEWAY_MARKER_STYLE.height}" viewBox="0 0 24 32" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
        <path d="M12 0 C 5.4 0 0 5.4 0 12 C 0 21 12 32 12 32 C 12 32 24 21 24 12 C 24 5.4 18.6 0 12 0 Z" fill="${GATEWAY_MARKER_STYLE.fill}" stroke="${GATEWAY_MARKER_STYLE.stroke}" stroke-width="1.5"/>
        <g transform="translate(6 5) scale(0.5)" fill="none" stroke="${GATEWAY_MARKER_STYLE.iconColor}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M5 8a7 7 0 0 1 14 0"/>
          <path d="M9 8a3 3 0 0 1 6 0"/>
          <line x1="12" y1="8" x2="12" y2="21"/>
          <line x1="9" y1="21" x2="15" y2="21"/>
          <line x1="9" y1="14" x2="15" y2="14"/>
        </g>
      </svg>`;
      const popup = new maplibregl.Popup({ offset: 12 }).setHTML(
        `<div style="font:12px/1.4 system-ui">
           <div><strong>${g.code}</strong> — ${g.name}</div>
           <div>${t.popup.gatewayTx}: ${g.tx_power_dbm} dBm, ${t.popup.gatewayGain} ${g.antenna_gain_dbi} dBi</div>
           <div>${t.popup.gatewayAntenna}: ${g.antenna_height_m} m AGL</div>
           <div>${t.popup.gatewayFreq}: ${g.frequency_mhz} MHz</div>
         </div>`,
      );
      // anchor='bottom' → đáy SVG (tip teardrop) đặt đúng tại tọa độ gateway,
      // giống folium.Marker (Leaflet default behavior).
      const marker = new maplibregl.Marker({ element: el, anchor: "bottom" })
        .setLngLat([g.longitude, g.latitude])
        .setPopup(popup)
        .addTo(map);
      gatewayMarkersRef.current.push(marker);
    }

    return () => {
      for (const m of gatewayMarkersRef.current) m.remove();
      gatewayMarkersRef.current = [];
    };
  }, [gatewaysQ.data, mapLoaded]);

  /**
   * Build popup DOM 2 layer cho marker dự đoán (chỉ tab "Dự đoán điểm").
   *  - Header: tiêu đề "Điểm dự đoán" + dòng toạ độ.
   *  - Layer 1 (default): badge trạng thái + 1 câu giải thích tiếng Việt.
   *  - Layer 2 (toggle): SF dùng vs SF khuyến nghị (highlight nếu lệch),
   *    RSSI / SNR / Confidence + link gateway phục vụ.
   * Theo business-logic.md §4.2 — dual-layer rule cho 1 feature phục vụ
   * cả end-user (Layer 1) lẫn kỹ sư P1/P2 (Layer 2).
   * @type {(lat: number, lng: number, prediction: import("../api/client.js").PredictionT, sfUsed: number, isAuto: boolean, txPowerUsed: number, environmentUsed: "outdoor" | "indoor" | "indoor_deep") => HTMLDivElement}
   */
  const buildPopupNode = useCallback((lat, lng, prediction, sfUsed, isAuto, txPowerUsed, environmentUsed) => {
    const root = document.createElement("div");
    root.style.cssText = "font:12px/1.4 system-ui;max-width:360px;min-width:320px";

    const status = prediction.coverage_status;
    const color = STATUS_COLOR[status] ?? STATUS_COLOR_FALLBACK;

    const title = document.createElement("div");
    title.style.cssText = "font-weight:600;color:#0f172a";
    title.textContent = t.popup.predictTitle;
    root.appendChild(title);

    const subtitle = document.createElement("div");
    subtitle.style.cssText =
      "font:11px/1.3 ui-monospace,SFMono-Regular,Menlo,monospace;color:#64748b;margin-bottom:6px";
    subtitle.textContent = t.popup.coords(lat, lng);
    root.appendChild(subtitle);

    // Layer 1: status badge + bottleneck pill (cùng hàng).
    const badgeRow = document.createElement("div");
    badgeRow.style.cssText = "display:flex;flex-wrap:wrap;gap:6px;align-items:center";
    const badge = document.createElement("span");
    badge.style.cssText = `display:inline-block;background:${color};color:white;padding:2px 8px;border-radius:9999px;font-weight:600;font-size:11px`;
    badge.textContent = STATUS_LABEL[status] ?? status;
    badgeRow.appendChild(badge);
    appendBottleneckPill(badgeRow, prediction.bottleneck);
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

    const rec = prediction.recommended_sf;
    // Khi user chọn "Tự động": ẩn dòng "SF dùng" và bỏ mismatch hint vì
    // không có SF input để so sánh.
    const sfMismatch = !isAuto && rec !== sfUsed;
    const recCellHtml = sfMismatch
      ? `<strong>${t.popup.recommendedSf.value(rec)}</strong> <span style="color:#b45309">${t.popup.sfMismatchHint}</span>`
      : `<strong>${t.popup.recommendedSf.value(rec)}</strong>`;
    const techRows = document.createElement("div");
    // RSSI/SNR tổng đã hiện chi tiết per-direction trong mini-table UL/DL
    // bên dưới — không lặp lại ở đây để tránh trùng abstraction (philosophy
    // ch.7: "each layer provides a different abstraction").
    const usedSfRow = isAuto
      ? ""
      : `<div>${t.popup.usedSf.label}: <strong>${t.popup.usedSf.value(sfUsed)}</strong></div>`;
    const envOption = t.environmentPicker.options.find(
      (o) => o.value === environmentUsed,
    );
    const envLabel = envOption?.short ?? environmentUsed;
    const usedTxPowerRow = `<div>${t.popup.usedTxPower.label}: <strong>${t.popup.usedTxPower.value(txPowerUsed)}</strong></div>`;
    const usedEnvRow = `<div>${t.popup.usedEnvironment.label}: <strong>${envLabel}</strong></div>`;
    // path_loss_db = 0 khi BE chưa rebuild hoặc no_coverage — ẩn row để khỏi
    // hiển thị "0 dB" lẫn lộn.
    const pathLossRow =
      prediction.path_loss_db > 0
        ? `<div>${t.popup.pathLoss.label}: <strong>${t.popup.pathLoss.value(prediction.path_loss_db)}</strong></div>`
        : "";
    // σ_total = √(epi + ale) — Stage 1 epi=0, ale=σ_shadow² theo env_profile.
    const sigmaDb = Math.sqrt(
      prediction.confidence.epistemic_variance_db2 +
        prediction.confidence.aleatoric_variance_db2,
    );
    techRows.innerHTML =
      usedSfRow +
      `<div>${t.popup.recommendedSf.label}: ${recCellHtml}</div>` +
      usedTxPowerRow +
      usedEnvRow +
      pathLossRow +
      `<div>${t.popup.errorMargin.label}: <strong>${t.popup.errorMargin.value(sigmaDb)}</strong></div>` +
      `<div>${t.popup.accuracy.label}: <strong>${t.popup.accuracy.value(sigmaDb)}</strong></div>`;
    layer2.appendChild(techRows);

    // Data-link metrics (bitrate, ToA, max payload) — pure function của SF,
    // tách section vì là "khả năng truyền dữ liệu" khác bản chất với "phủ sóng".
    appendDataLinkSection(layer2, sfUsed);

    // UL/DL table — chỉ render khi BE có trả 2 chiều (backward-compat).
    if (prediction.uplink && prediction.downlink) {
      appendBidirectionalSection(layer2, prediction.uplink, prediction.downlink);
    }

    const gwRow = document.createElement("div");
    gwRow.style.cssText = "margin-top:6px";
    // Khi no_coverage: BE vẫn trả serving_gateway_id = candidate ít tệ nhất
    // (debug field), nhưng UX-wise treat như "không có gateway phục vụ".
    const gw =
      prediction.serving_gateway_id && prediction.coverage_status !== "no_coverage"
        ? gatewaysRef.current.find((x) => x.id === prediction.serving_gateway_id)
        : null;
    if (gw) {
      gwRow.appendChild(
        document.createTextNode(`${t.popup.nearestGateway.label}: `),
      );
      const link = document.createElement("a");
      link.href = "#";
      link.style.cssText = "color:#0369a1;text-decoration:underline";
      link.textContent = `${gw.code} — ${gw.name}`;
      link.addEventListener("click", (e) => {
        e.preventDefault();
        mapRef.current?.flyTo({
          center: [gw.longitude, gw.latitude],
          zoom: 14,
        });
      });
      gwRow.appendChild(link);
    } else {
      gwRow.textContent = `${t.popup.nearestGateway.label}: ${t.popup.nearestGateway.none}`;
    }
    layer2.appendChild(gwRow);

    // Khoảng cách đến serving gateway — chỉ hiển thị khi BE có wire (>0).
    // Serving gateway = gateway có min(UL_margin, DL_margin) = "tín hiệu mạnh
    // nhất", không phải nearest geographic.
    if (gw && prediction.distance_to_serving_gateway_km > 0) {
      const distRow = document.createElement("div");
      distRow.style.cssText = "margin-top:2px;color:#475569;font-size:11px";
      distRow.textContent = `${t.popup.distanceToGateway.label}: ${t.popup.distanceToGateway.value(prediction.distance_to_serving_gateway_km)}`;
      layer2.appendChild(distRow);
    }

    appendCopyLinkButton(layer2, lat, lng, isAuto ? "auto" : sfUsed);

    root.appendChild(layer2);

    toggleBtn.addEventListener("click", () => {
      const visible = layer2.style.display !== "none";
      layer2.style.display = visible ? "none" : "block";
      toggleBtn.textContent = visible
        ? t.popup.toggleLayer2.show
        : t.popup.toggleLayer2.hide;
    });

    return root;
  }, []);
  // Deps rỗng: hàm chỉ đọc refs (gatewaysRef, mapRef) và module-level
  // constants (STATUS_COLOR, STATUS_LABEL, t) — không có reactive state.

  /**
   * Pure marker-drawing helper — không phụ thuộc state, chỉ dùng refs.
   * Cho phép gọi từ effect mà không gây stale closure.
   * @type {(lat: number, lng: number, prediction: import("../api/client.js").PredictionT, sfUsed: number, isAuto: boolean, txPowerUsed: number, environmentUsed: "outdoor" | "indoor" | "indoor_deep") => void}
   */
  const drawSearchMarker = useCallback((lat, lng, prediction, sfUsed, isAuto, txPowerUsed, environmentUsed) => {
    const map = mapRef.current;
    if (!map) return;

    const color =
      STATUS_COLOR[prediction.coverage_status] ?? STATUS_COLOR_FALLBACK;
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
      buildPopupNode(lat, lng, prediction, sfUsed, isAuto, txPowerUsed, environmentUsed),
    );

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
  }, []);

  // Initial URL deep-link: predict 1 lần sau khi map mount.
  // Chỉ tab "Dự đoán điểm" mới tiêu thụ URL state — tab "Bản đồ điểm đo" và
  // "Bản đồ phủ sóng" không hiển thị popup "Vị trí từ URL" kể cả khi URL có
  // ?lat=&lng= (do tab predict ghi sẵn từ lần dự đoán trước).
  useEffect(() => {
    if (mode !== "predict") return;
    const url = initialUrlRef.current;
    if (!url) return;
    let cancelled = false;
    const isAuto = url.sf === "auto";
    /** @type {number} */
    const sfForUrl = typeof url.sf === "number" ? url.sf : DEFAULT_SF;
    predictCoverage({
      latitude: url.lat,
      longitude: url.lng,
      spreading_factor: sfForUrl,
      frequency_mhz: DEFAULT_FREQ_MHZ,
    })
      .then((prediction) => {
        if (cancelled) return;
        // Deep-link không serialize tx_power/environment → fallback defaults
        // (14 dBm outdoor) khớp BE behavior khi field None trong PredictRequest.
        drawSearchMarker(url.lat, url.lng, prediction, sfForUrl, isAuto, 14, "outdoor");
      })
      .catch((e) => {
        console.error("Deep-link predict failed:", e);
      });
    return () => {
      cancelled = true;
    };
  }, [mode, drawSearchMarker]);

  /**
   * Predict mode: chạy prediction từ pickedCoords + SF hiện tại, vẽ marker
   * + popup dual-layer.
   */
  async function onPredictSubmit() {
    if (!pickedCoords || predictBusy) return;
    const { lat, lng } = pickedCoords;
    setPredictBusy(true);
    setPredictError(null);
    // "Tự động": gửi DEFAULT_SF (max sensitivity) cho BE — recommended_sf
    // trong response sẽ là SF nên dùng. Popup ẩn dòng "SF dùng".
    const isAuto = sf === "auto";
    const sfForApi = isAuto ? DEFAULT_SF : sf;
    try {
      const prediction = await predictCoverage({
        latitude: lat,
        longitude: lng,
        spreading_factor: sfForApi,
        frequency_mhz: DEFAULT_FREQ_MHZ,
        tx_power_dbm: txPowerDbm,
        environment,
      });
      drawSearchMarker(
        lat,
        lng,
        prediction,
        sfForApi,
        isAuto,
        txPowerDbm,
        environment,
      );
      writeUrlState(lat, lng, sf);
    } catch (e) {
      console.error("Predict submit failed:", e);
      setPredictError(t.predictPanel.error);
    } finally {
      setPredictBusy(false);
    }
  }

  // SF dropdown = input cho lần predict tiếp theo. Không auto re-predict
  // marker đã có (multi-marker thì semantic ambiguous: re-predict cái nào?).

  return (
    <div className="h-full w-full">
      {/* Pad maplibre top-right control container (pt-10 = 40px) khi tab
          points để chừa chỗ cho icon view-mode toggle ngồi trên zoom. Tab
          khác (predict/heatmap) không có toggle nên giữ control sát mép. */}
      <div
        className={
          mode === "points"
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
            onChange={setViewMode}
            options={[
              { value: "points", label: t.viewModePicker.modes.points },
              { value: "heatmap", label: t.viewModePicker.modes.heatmap },
            ]}
          />
        )}

        {/* Container anchor cả trên + dưới: `bottom-44` (=11rem) chừa zone
            cho legend ở góc dưới-trái. `pointer-events-none` để vùng trống
            (khi panel collapsed) không chặn map click; children tự bật lại. */}
        <div className="pointer-events-none absolute top-3 bottom-52 left-3 z-10 flex flex-col gap-2 [&>*]:pointer-events-auto">
          {mode === "predict" ? (
            <div className="w-64 rounded-md border border-slate-200 bg-white px-3 py-2.5 text-xs text-slate-700 shadow-sm">
              <div className="text-sm font-semibold text-slate-900">
                {t.predictPanel.title}
              </div>

              <div className="mt-2 grid grid-cols-2 gap-x-2 gap-y-1 text-[11px]">
                <div className="text-slate-500">{t.predictPanel.latLabel}</div>
                <div className="text-right font-mono text-slate-900">
                  {pickedCoords
                    ? pickedCoords.lat.toFixed(5)
                    : t.predictPanel.empty}
                </div>
                <div className="text-slate-500">{t.predictPanel.lngLabel}</div>
                <div className="text-right font-mono text-slate-900">
                  {pickedCoords
                    ? pickedCoords.lng.toFixed(5)
                    : t.predictPanel.empty}
                </div>
              </div>

              <div className="mt-2 flex items-center gap-2">
                <label
                  className="text-xs font-medium text-slate-700"
                  htmlFor="sf-picker"
                >
                  {t.sfPicker.label}
                </label>
                <select
                  id="sf-picker"
                  value={sf}
                  onChange={(e) => {
                    const v = e.target.value;
                    setSf(v === "auto" ? "auto" : Number(v));
                  }}
                  className="flex-1 rounded-md border border-slate-300 px-2 py-1 text-xs shadow-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
                >
                  <option value="auto">{t.sfPicker.auto}</option>
                  {SF_OPTIONS.map((v) => (
                    <option key={v} value={v}>
                      {t.sfPicker.option(v)}
                    </option>
                  ))}
                </select>
              </div>

              <div className="mt-2 flex items-center gap-2">
                <label
                  className="text-xs font-medium text-slate-700"
                  htmlFor="tx-power-picker"
                >
                  {t.txPowerPicker.label}
                </label>
                <select
                  id="tx-power-picker"
                  value={txPowerDbm}
                  onChange={(e) => setTxPowerDbm(Number(e.target.value))}
                  className="flex-1 rounded-md border border-slate-300 px-2 py-1 text-xs shadow-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
                  title={t.txPowerPicker.hint}
                >
                  {t.txPowerPicker.options.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>

              <fieldset className="mt-2">
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
                            /** @type {"outdoor" | "indoor" | "indoor_deep"} */ (
                              opt.value
                            ),
                          )
                        }
                      />
                      {opt.label}
                    </label>
                  ))}
                </div>
              </fieldset>

              {!pickedCoords && (
                <div className="mt-2 text-[11px] leading-snug text-slate-500">
                  {t.predictPanel.hint}
                </div>
              )}

              <button
                type="button"
                onClick={onPredictSubmit}
                disabled={!pickedCoords || predictBusy}
                className="mt-2 w-full rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white shadow-sm transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300"
              >
                {predictBusy
                  ? t.predictPanel.submitting
                  : t.predictPanel.submit}
              </button>

              <button
                type="button"
                onClick={clearAllSearchMarkers}
                disabled={predictMarkerCount === 0}
                className="mt-1.5 w-full rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 shadow-sm transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:border-slate-200 disabled:text-slate-400"
              >
                {t.predictPanel.clearAll}
                {predictMarkerCount > 0 ? ` (${predictMarkerCount})` : ""}
              </button>

              {predictError && (
                <div className="mt-2 text-[11px] text-red-600">
                  {predictError}
                </div>
              )}
            </div>
          ) : mode === "points" ? (
            <PointsFilterPanel
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
              sortConfig={sortConfig}
              onSortConfigChange={setSortConfig}
            />
          ) : (
            // Heatmap mode: chỉ SF dropdown đơn để chọn SF input cho model.
            <div className="w-64 rounded-md border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700 shadow-sm">
              <div className="flex items-center gap-2">
                <label
                  className="text-xs font-medium text-slate-700"
                  htmlFor="sf-picker"
                >
                  {t.sfPicker.label}
                </label>
                <select
                  id="sf-picker"
                  value={sf === "auto" ? DEFAULT_SF : sf}
                  onChange={(e) => setSf(Number(e.target.value))}
                  className="flex-1 rounded-md border border-slate-300 px-2 py-1 text-xs shadow-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
                >
                  {SF_OPTIONS.map((v) => (
                    <option key={v} value={v}>
                      {t.sfPicker.option(v)}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          )}

        </div>

        {/* Legend cố định ở góc dưới trái — chừa chỗ cho ScaleControl của
            maplibre (mounted ở "bottom-left", cao ~24px). */}
        <div className="absolute bottom-10 left-2 z-10">
          <MapLegend
            gatewayCount={gatewaysQ.data?.total}
            surveyCount={mode === "points" ? surveysQ.data?.total : null}
          />
        </div>

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
      </div>
    </div>
  );
}