/**
 * UncertaintyLayer.jsx
 * Hiển thị bản đồ độ không chắc chắn của ML prediction.
 * Màu xanh = chắc chắn, đỏ/tím = ít tin cậy (ít điểm đo xung quanh).
 *
 * Input: points = [[lat, lng, uncertainty_db], ...]
 */
import { useMemo } from "react";
import { Source, Layer } from "react-map-gl";

export default function UncertaintyLayer({ points = [], radius = 30 }) {
  const geojson = useMemo(() => ({
    type: "FeatureCollection",
    features: points.map(([lat, lng, uncertainty]) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [lng, lat] },
      // intensity 0 = chắc chắn, 1 = rất không chắc
      properties: { intensity: Math.max(0, Math.min(1, (uncertainty ?? 0) / 15)) },
    })),
  }), [points]);

  if (points.length === 0) return null;

  return (
    <Source id="uncertainty-source" type="geojson" data={geojson}>
      {/* Heatmap uncertainty — xanh (chắc) → vàng → đỏ → tím (không chắc) */}
      <Layer
        id="uncertainty-heat"
        type="heatmap"
        maxzoom={16}
        paint={{
          "heatmap-weight": ["interpolate", ["linear"], ["get", "intensity"], 0, 0, 1, 1],
          "heatmap-intensity": ["interpolate", ["linear"], ["zoom"], 0, 0.5, 16, 2],
          "heatmap-color": [
            "interpolate", ["linear"], ["heatmap-density"],
            0,    "rgba(29,158,117,0)",    // chắc — xanh lá trong suốt
            0.2,  "rgba(29,158,117,0.85)", // chắc
            0.45, "rgba(239,159,39,0.9)",  // trung bình — vàng
            0.7,  "rgba(226,75,74,0.95)",  // không chắc — đỏ
            1,    "rgba(123,33,232,1)",    // rất không chắc — tím
          ],
          "heatmap-radius": ["interpolate", ["linear"], ["zoom"],
            10, radius * 0.4,
            14, radius,
            18, radius * 2.5,
          ],
          "heatmap-opacity": 0.82,
        }}
      />
      {/* Điểm chi tiết khi zoom gần */}
      <Layer
        id="uncertainty-point"
        type="circle"
        minzoom={14}
        paint={{
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 14, 3, 18, 8],
          "circle-color": ["interpolate", ["linear"], ["get", "intensity"],
            0,   "#1D9E75",
            0.4, "#EF9F27",
            0.7, "#E24B4A",
            1,   "#7B21E8",
          ],
          "circle-opacity": ["interpolate", ["linear"], ["zoom"], 14, 0, 15, 0.75],
          "circle-stroke-width": 0.5,
          "circle-stroke-color": "rgba(255,255,255,0.25)",
        }}
      />
    </Source>
  );
}