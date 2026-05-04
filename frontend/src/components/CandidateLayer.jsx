/**
 * CandidateLayer.jsx — Render candidate gateway positions.
 *
 * Source = grid (gray) | infra (orange).
 * Hover/click do parent xử lý qua interactiveLayerIds=[CANDIDATE_LAYER_ID].
 */

import { useMemo } from "react";
import { Source, Layer } from "react-map-gl";

export const CANDIDATE_LAYER_ID = "candidates-circle";

export default function CandidateLayer({ candidates = [] }) {
  const geojson = useMemo(() => ({
    type: "FeatureCollection",
    features: candidates.map(c => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [c.lng, c.lat] },
      properties: {
        id:       c.id,
        source:   c.source,
        cost:     c.cost,
        h3Index:  c.h3Index,
      },
    })),
  }), [candidates]);

  if (!candidates.length) return null;

  return (
    <Source id="candidates" type="geojson" data={geojson}>
      <Layer
        id={CANDIDATE_LAYER_ID}
        type="circle"
        paint={{
          // Infra to hơn grid để dễ thấy
          "circle-radius": [
            "interpolate", ["linear"], ["zoom"],
            10, ["match", ["get", "source"], "infra", 4, 1.5],
            14, ["match", ["get", "source"], "infra", 7, 3],
            18, ["match", ["get", "source"], "infra", 11, 5],
          ],
          "circle-color": [
            "match", ["get", "source"],
            "infra", "#f97316",   // cam — vị trí infra thật từ OSM
            "grid",  "#94a3b8",   // xám — vị trí giả định H3 grid
            "#94a3b8",
          ],
          "circle-stroke-width": [
            "match", ["get", "source"],
            "infra", 1.5,
            0.4,
          ],
          "circle-stroke-color": "#fff",
          "circle-opacity": [
            "match", ["get", "source"],
            "infra", 0.9,
            0.55,
          ],
        }}
      />
    </Source>
  );
}