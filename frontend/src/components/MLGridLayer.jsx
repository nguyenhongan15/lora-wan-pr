/**
 * MLGridLayer.jsx — ML prediction heatmap
 * Pattern: Mapbox official earthquake heatmap, adapted cho LoRa RSSI grid.
 * - Zoom thấp: heatmap layer
 * - Zoom cao (> zoom 13): chuyển sang circle layer từng điểm
 */
import { useMemo } from "react";
import { Source, Layer } from "react-map-gl";

export default function MLGridLayer({ points = [] }) {
  const geojson = useMemo(() => ({
    type: "FeatureCollection",
    features: points.map(([lat, lng, intensity]) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [lng, lat] },
      properties: {
        // intensity: 0 = RSSI rất yếu, 1 = RSSI mạnh
        intensity: Math.max(0, Math.min(1, intensity ?? 0.5)),
      },
    })),
  }), [points]);

  if (points.length === 0) return null;

  return (
    <Source id="mlgrid-source" type="geojson" data={geojson} tolerance={0.375}>

      {/* ── HEATMAP LAYER (zoom 0 → 14) ── */}
      <Layer
        id="mlgrid-heat"
        type="heatmap"
        maxzoom={14}
        slot="top"
        paint={{
          // Trọng số từng điểm theo intensity (RSSI)
          "heatmap-weight": [
            "interpolate", ["linear"], ["get", "intensity"],
            0, 0,
            1, 1,
          ],

          // Nhân thêm intensity theo zoom — giữ thấp để không bão hòa
          "heatmap-intensity": [
            "interpolate", ["linear"], ["zoom"],
            0,  0.4,
            10, 1.2,
            14, 2,
          ],

          // Màu: trong suốt → xanh dương → trắng xanh → cam nhạt → cam → đỏ
          "heatmap-color": [
            "interpolate", ["linear"], ["heatmap-density"],
            0,    "rgba(33,102,172,0)",
            0.15, "rgb(103,169,207)",
            0.35, "rgb(209,229,240)",
            0.55, "rgb(253,219,199)",
            0.75, "rgb(239,138,98)",
            1,    "rgb(178,24,43)",
          ],

          // Bán kính nhỏ ở zoom xa, lớn khi zoom gần
          "heatmap-radius": [
            "interpolate", ["linear"], ["zoom"],
            0,  2,
            8,  12,
            10, 20,
            14, 40,
          ],

          // Fade out khi zoom gần — circle layer thay thế
          "heatmap-opacity": [
            "interpolate", ["linear"], ["zoom"],
            12, 1,
            14, 0,
          ],
        }}
      />

      {/* ── CIRCLE LAYER (zoom 12+) ── */}
      <Layer
        id="mlgrid-point"
        type="circle"
        minzoom={12}
        slot="top"
        paint={{
          "circle-radius": [
            "interpolate", ["linear"], ["zoom"],
            12, 3,
            14, 6,
            16, 12,
            18, 22,
          ],

          // Xanh dương đậm = mạnh, đỏ = yếu
          "circle-color": [
            "interpolate", ["linear"], ["get", "intensity"],
            0,    "rgb(178,24,43)",
            0.25, "rgb(239,138,98)",
            0.5,  "rgb(253,219,199)",
            0.75, "rgb(103,169,207)",
            1,    "rgb(33,102,172)",
          ],

          "circle-emissive-strength": 0.65,
          "circle-stroke-color": "rgba(255,255,255,0.25)",
          "circle-stroke-width": 0.5,

          // Fade in khi zoom vào
          "circle-opacity": [
            "interpolate", ["linear"], ["zoom"],
            12, 0,
            13, 0.85,
          ],
        }}
      />
    </Source>
  );
}