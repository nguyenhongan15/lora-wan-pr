
/** @typedef {import("maplibre-gl").Map} MaplibreMap */

const LAYER_ID = "surveys-heatmap";

const PAINT = {
  "heatmap-weight": 0.2,
  // Intensity = "độ đậm tổng" — zoom cao tăng nhẹ để hotspot sắc hơn.
  "heatmap-intensity": ["interpolate", ["linear"], ["zoom"], 0, 0.1, 14, 0.8],
  // Radius nhỏ hơn = mỗi điểm "loang" ít → vùng thưa giữ blue/cyan thay vì
  // gộp thành mảng đỏ. z10 ~10px, z16 ~24px.
  "heatmap-radius": ["interpolate", ["linear"], ["zoom"], 10, 10, 16, 24],
  // Palette "classic heatmap" (leaflet.heat / folium HeatMap):
  // trong suốt → blue → cyan → lime → yllow → red.
  // Stops dịch lên cao: cyan/lime/yellow chiếm dải rộng hơn, đỏ chỉ ở hotspot
  // thực sự dày — fix tình trạng "toàn đỏ" khi dataset có nhiều điểm overlap.
  "heatmap-color": [
    "interpolate",
    ["linear"],
    ["heatmap-density"],
    0, "rgba(0,0,255,0)",
    0.15, "rgba(0,0,255,0.5)",
    0.44, "rgba(0,255,255,0.75)",
    0.66, "rgba(0,255,0,0.85)",
    0.86, "rgba(255,255,0,0.9)",
    1, "rgba(255,0,0,1)",
  ],
  "heatmap-opacity": 0.6,
};

/**
 * Đăng ký heatmap layer vào map, dùng chung GeoJSON source với circle layer.
 * Mặc định invisible — caller toggle sau qua `setSurveyHeatmapVisible`.
 *
 * Idempotent: nếu layer đã tồn tại (vd hot-reload), no-op để tránh maplibre
 * throw "layer already exists".
 *
 * @param {MaplibreMap} map
 * @param {string} sourceId — GeoJSON source ID đã `addSource` từ trước.
 */
export function addSurveyHeatmapLayer(map, sourceId) {
  if (map.getLayer(LAYER_ID)) return;
  map.addLayer({
    id: LAYER_ID,
    type: "heatmap",
    source: sourceId,
    paint: /** @type {any} */ (PAINT),
    layout: { visibility: "none" },
  });
}

/**
 * Toggle visibility heatmap layer. No-op nếu layer chưa registered (caller
 * không cần guard).
 *
 * @param {MaplibreMap} map
 * @param {boolean} visible
 */
export function setSurveyHeatmapVisible(map, visible) {
  if (!map.getLayer(LAYER_ID)) return;
  map.setLayoutProperty(LAYER_ID, "visibility", visible ? "visible" : "none");
}
