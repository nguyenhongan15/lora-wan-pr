// @ts-check
import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

import {
  listGateways,
  listSurveyTraining,
  predictCoverage,
} from "../api/client.js";
import { strings } from "../strings.js";
import { MapLegend } from "./MapLegend.jsx";

const t = strings.coverageMap;
/** @type {Record<string, string>} */
const STATUS_LABEL = strings.coverageStatus;

/** @type {Record<string, string>} */
const STATUS_COLOR = {
  strong: "#16a34a",
  marginal: "#eab308",
  weak: "#f97316",
  no_coverage: "#dc2626",
};

const SF_OPTIONS = /** @type {const} */ ([7, 8, 9, 10, 11, 12]);
const DEFAULT_SF = 12;
// VN AS923-2 — DNIIT seed cũng dùng 923 (xem migrations/seeds/seed_gateways.sql).
const DEFAULT_FREQ_MHZ = 923;

const DANANG_BBOX = {
  min_lon: 107.95,
  min_lat: 15.9,
  max_lon: 108.4,
  max_lat: 16.2,
};

// Centroid của 11 gateway DNIIT thực tế (tính từ r-dt/response_1777987688423.json).
const INITIAL_CENTER = /** @type {[number, number]} */ ([108.188, 16.069]);
const INITIAL_ZOOM = 11;

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

const OSM_RASTER_STYLE = {
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

/**
 * @returns {{ lat: number, lng: number, sf: number | null } | null}
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
  const sfRaw = Number(p.get("sf"));
  const sf =
    Number.isInteger(sfRaw) && sfRaw >= 7 && sfRaw <= 12 ? sfRaw : null;
  return { lat, lng, sf };
}

/**
 * @param {number} lat
 * @param {number} lng
 * @param {number} sf
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

// Survey GeoJSON source/layer ID — dùng circle layer (WebGL) thay vì HTML
// marker để render mượt với 4k+ điểm.
const SURVEYS_SOURCE_ID = "surveys-src";
const SURVEYS_LAYER_ID = "surveys-circle";

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
  const mapLoadedRef = useRef(false);
  const gatewayMarkersRef = useRef(/** @type {maplibregl.Marker[]} */ ([]));
  const searchMarkerRef = useRef(/** @type {maplibregl.Marker | null} */ (null));
  const gatewaysRef = useRef(
    /** @type {import("../api/client.js").GatewayT[]} */ ([]),
  );
  const lastSearchRef = useRef(
    /** @type {{ lat: number, lng: number } | null} */ (null),
  );
  const skipFirstSfEffect = useRef(true);
  const initialUrlRef = useRef(readUrlState());

  const [tileError, setTileError] = useState(/** @type {string | null} */ (null));
  const [pickedCoords, setPickedCoords] = useState(
    /** @type {{ lat: number, lng: number } | null} */ (null),
  );
  const [predictBusy, setPredictBusy] = useState(false);
  const [predictError, setPredictError] = useState(
    /** @type {string | null} */ (null),
  );
  const [sf, setSf] = useState(
    () => initialUrlRef.current?.sf ?? DEFAULT_SF,
  );

  const gatewaysQ = useQuery({
    queryKey: ["gateways", DANANG_BBOX],
    queryFn: () => listGateways(DANANG_BBOX),
  });

  // Tạm thời chỉ hiển thị toàn bộ điểm đo của board01 (~4897 rec) — node01
  // có 14 GPS outliers ngoài VN, node3 chỉ phủ 1 vùng nhỏ. Bỏ filter device
  // bằng cách set SURVEY_DEVICE_ID = null + giảm limit.
  const SURVEY_DEVICE_ID = "board01";
  const SURVEY_LIMIT = 5000;
  const surveysQ = useQuery({
    queryKey: ["surveys", DANANG_BBOX, SURVEY_DEVICE_ID, SURVEY_LIMIT],
    queryFn: () =>
      listSurveyTraining(DANANG_BBOX, {
        deviceId: SURVEY_DEVICE_ID,
        limit: SURVEY_LIMIT,
      }),
    enabled: mode === "points",
  });

  useEffect(() => {
    const container = containerRef.current;
    if (!container || mapRef.current) return;

    let map;
    try {
      map = new maplibregl.Map({
        container,
        style: /** @type {any} */ (OSM_RASTER_STYLE),
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
      mapLoadedRef.current = true;
      // Chỉ "points" mode add survey layer. "heatmap" sẽ add raster source
      // ở Phase 2; "predict" không cần điểm đo nền — user chỉ pick toạ độ.
      if (mode !== "points") return;

      // Source GeoJSON rỗng — sẽ setData khi survey query xong.
      map.addSource(SURVEYS_SOURCE_ID, {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      // Circle layer — color theo rssi_dbm bằng step expression. Ngưỡng:
      // ≥-100 strong, [-115,-100) good, [-120,-115) marginal, <-120 weak.
      map.addLayer({
        id: SURVEYS_LAYER_ID,
        type: "circle",
        source: SURVEYS_SOURCE_ID,
        paint: {
          "circle-radius": 4,
          "circle-color": [
            "step",
            ["get", "rssi_dbm"],
            "#dc2626", // < -120
            -120, "#f97316", // [-120, -115)
            -115, "#eab308", // [-115, -100)
            -100, "#16a34a", // ≥ -100
          ],
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 1,
        },
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
      mapLoadedRef.current = false;
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
    if (!mapLoadedRef.current || !map.getSource(SURVEYS_SOURCE_ID)) return;
    /** @type {maplibregl.GeoJSONSource} */ (
      map.getSource(SURVEYS_SOURCE_ID)
    ).setData(buildSurveyGeoJson(surveysQ.data.items));
  }, [surveysQ.data, mode]);

  // Gateway: chỉ 11 điểm → giữ HTML marker (cần rotate 45° tạo hình diamond,
  // dễ hơn dùng circle layer với icon).
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !gatewaysQ.data) return;

    for (const m of gatewayMarkersRef.current) m.remove();
    gatewayMarkersRef.current = [];
    gatewaysRef.current = gatewaysQ.data.items;

    for (const g of gatewaysQ.data.items) {
      const el = document.createElement("div");
      el.style.width = "16px";
      el.style.height = "16px";
      el.style.background = "#1d4ed8";
      el.style.border = "2px solid white";
      el.style.boxShadow = "0 0 4px rgba(0,0,0,0.5)";
      el.style.transform = "rotate(45deg)";
      const popup = new maplibregl.Popup({ offset: 12 }).setHTML(
        `<div style="font:12px/1.4 system-ui">
           <div><strong>${g.code}</strong> — ${g.name}</div>
           <div>${t.popup.gatewayTx}: ${g.tx_power_dbm} dBm, ${t.popup.gatewayGain} ${g.antenna_gain_dbi} dBi</div>
           <div>${t.popup.gatewayAntenna}: ${g.antenna_height_m} m AGL</div>
           <div>${t.popup.gatewayFreq}: ${g.frequency_mhz} MHz</div>
         </div>`,
      );
      const marker = new maplibregl.Marker({ element: el })
        .setLngLat([g.longitude, g.latitude])
        .setPopup(popup)
        .addTo(map);
      gatewayMarkersRef.current.push(marker);
    }
  }, [gatewaysQ.data]);

  /**
   * Build popup DOM 2 layer cho marker dự đoán (chỉ tab "Dự đoán điểm").
   *  - Header: tiêu đề "Điểm dự đoán" + dòng toạ độ.
   *  - Layer 1 (default): badge trạng thái + 1 câu giải thích tiếng Việt.
   *  - Layer 2 (toggle): SF dùng vs SF khuyến nghị (highlight nếu lệch),
   *    RSSI / SNR / Confidence + link gateway phục vụ.
   * Theo business-logic.md §4.2 — dual-layer rule cho 1 feature phục vụ
   * cả end-user (Layer 1) lẫn kỹ sư P1/P2 (Layer 2).
   * @type {(lat: number, lng: number, prediction: import("../api/client.js").PredictionT, sfUsed: number) => HTMLDivElement}
   */
  const buildPopupNode = useCallback((lat, lng, prediction, sfUsed) => {
    const root = document.createElement("div");
    root.style.cssText = "font:12px/1.4 system-ui;max-width:280px";

    const status = prediction.coverage_status;
    const color = STATUS_COLOR[status] ?? "#7c3aed";

    const title = document.createElement("div");
    title.style.cssText = "font-weight:600;color:#0f172a";
    title.textContent = t.popup.predictTitle;
    root.appendChild(title);

    const subtitle = document.createElement("div");
    subtitle.style.cssText =
      "font:11px/1.3 ui-monospace,SFMono-Regular,Menlo,monospace;color:#64748b;margin-bottom:6px";
    subtitle.textContent = t.popup.coords(lat, lng);
    root.appendChild(subtitle);

    const badge = document.createElement("span");
    badge.style.cssText = `display:inline-block;background:${color};color:white;padding:2px 8px;border-radius:9999px;font-weight:600;font-size:11px`;
    badge.textContent = STATUS_LABEL[status] ?? status;
    root.appendChild(badge);

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
      "display:none;margin-top:6px;padding-top:6px;border-top:1px solid #e2e8f0;color:#334155";

    const rec = prediction.recommended_sf;
    const sfMismatch = rec !== sfUsed;
    const recCellHtml = sfMismatch
      ? `<strong>${t.popup.recommendedSf.value(rec)}</strong> <span style="color:#b45309">${t.popup.sfMismatchHint}</span>`
      : `<strong>${t.popup.recommendedSf.value(rec)}</strong>`;
    const techRows = document.createElement("div");
    techRows.innerHTML =
      `<div>${t.popup.usedSf.label}: <strong>${t.popup.usedSf.value(sfUsed)}</strong></div>` +
      `<div>${t.popup.recommendedSf.label}: ${recCellHtml}</div>` +
      `<div>${t.popup.rssiLabel}: <strong>${prediction.rssi_dbm.toFixed(1)} dBm</strong></div>` +
      `<div>${t.popup.snrLabel}: <strong>${prediction.snr_db.toFixed(1)} dB</strong></div>` +
      `<div>${t.popup.searchConfidence}: <strong>${(prediction.confidence.score * 100).toFixed(0)}%</strong> <span style="color:#94a3b8">(${prediction.confidence.method})</span></div>`;
    layer2.appendChild(techRows);

    const gwRow = document.createElement("div");
    gwRow.style.cssText = "margin-top:4px";
    const gw = prediction.serving_gateway_id
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
   * @type {(lat: number, lng: number, prediction: import("../api/client.js").PredictionT, sfUsed: number) => void}
   */
  const drawSearchMarker = useCallback((lat, lng, prediction, sfUsed) => {
    const map = mapRef.current;
    if (!map) return;

    if (searchMarkerRef.current) {
      searchMarkerRef.current.remove();
      searchMarkerRef.current = null;
    }

    const color = STATUS_COLOR[prediction.coverage_status] ?? "#7c3aed";
    const el = document.createElement("div");
    el.style.width = "22px";
    el.style.height = "22px";
    el.style.borderRadius = "50% 50% 50% 0";
    el.style.transform = "rotate(-45deg)";
    el.style.background = color;
    el.style.border = "3px solid white";
    el.style.boxShadow = "0 0 6px rgba(0,0,0,0.5)";

    const popup = new maplibregl.Popup({ offset: 16 }).setDOMContent(
      buildPopupNode(lat, lng, prediction, sfUsed),
    );

    const marker = new maplibregl.Marker({ element: el, anchor: "bottom" })
      .setLngLat([lng, lat])
      .setPopup(popup)
      .addTo(map);
    marker.togglePopup();
    searchMarkerRef.current = marker;

    map.flyTo({ center: [lng, lat], zoom: 14 });
  }, [buildPopupNode]);
  // Phụ thuộc buildPopupNode (đã stable nhờ useCallback ở trên).

  // Initial URL deep-link: predict 1 lần sau khi map mount.
  // Chỉ tab "Dự đoán điểm" mới tiêu thụ URL state — tab "Bản đồ điểm đo" và
  // "Bản đồ phủ sóng" không hiển thị popup "Vị trí từ URL" kể cả khi URL có
  // ?lat=&lng= (do tab predict ghi sẵn từ lần dự đoán trước).
  useEffect(() => {
    if (mode !== "predict") return;
    const url = initialUrlRef.current;
    if (!url) return;
    let cancelled = false;
    const sfForUrl = url.sf ?? DEFAULT_SF;
    predictCoverage({
      latitude: url.lat,
      longitude: url.lng,
      spreading_factor: sfForUrl,
      frequency_mhz: DEFAULT_FREQ_MHZ,
    })
      .then((prediction) => {
        if (cancelled) return;
        lastSearchRef.current = { lat: url.lat, lng: url.lng };
        drawSearchMarker(url.lat, url.lng, prediction, sfForUrl);
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
    try {
      const prediction = await predictCoverage({
        latitude: lat,
        longitude: lng,
        spreading_factor: sf,
        frequency_mhz: DEFAULT_FREQ_MHZ,
      });
      lastSearchRef.current = { lat, lng };
      drawSearchMarker(lat, lng, prediction, sf);
      writeUrlState(lat, lng, sf);
    } catch (e) {
      console.error("Predict submit failed:", e);
      setPredictError(t.predictPanel.error);
    } finally {
      setPredictBusy(false);
    }
  }

  // Khi user đổi SF: re-predict ở vị trí search gần nhất + cập nhật URL.
  useEffect(() => {
    if (skipFirstSfEffect.current) {
      skipFirstSfEffect.current = false;
      return;
    }
    const last = lastSearchRef.current;
    if (!last) return;
    let cancelled = false;
    predictCoverage({
      latitude: last.lat,
      longitude: last.lng,
      spreading_factor: sf,
      frequency_mhz: DEFAULT_FREQ_MHZ,
    })
      .then((prediction) => {
        if (cancelled) return;
        drawSearchMarker(last.lat, last.lng, prediction, sf);
        writeUrlState(last.lat, last.lng, sf);
      })
      .catch((e) => {
        console.error("SF re-predict failed:", e);
      });
    return () => {
      cancelled = true;
    };
  }, [sf, drawSearchMarker]);

  return (
    <div className="h-full w-full">
      <div className="relative h-full w-full overflow-hidden">
        <div ref={containerRef} className="h-full w-full" />

        <div className="absolute top-3 left-3 z-10 flex flex-col gap-2">
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

              {predictError && (
                <div className="mt-2 text-[11px] text-red-600">
                  {predictError}
                </div>
              )}
            </div>
          ) : (
            <div className="w-32 rounded-md border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700 shadow-sm">
              <div className="flex items-center gap-2">
                <label
                  className="text-xs font-medium text-slate-700"
                  htmlFor="sf-picker"
                >
                  {t.sfPicker.label}
                </label>
                <select
                  id="sf-picker"
                  value={sf}
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