/**
 * AoiLayer.jsx — AOI boundary overlay (full + optional urban).
 * Fill mờ + outline đậm; full = tím, urban = vàng.
 */

import { Source, Layer } from "react-map-gl";

export default function AoiLayer({ fullAoi, urbanAoi }) {
  return (
    <>
      {fullAoi?.boundary && (
        <Source
          id="aoi-full"
          type="geojson"
          data={{ type: "Feature", geometry: fullAoi.boundary, properties: {} }}
        >
          <Layer
            id="aoi-full-fill"
            type="fill"
            paint={{
              "fill-color":   "#7c3aed",
              "fill-opacity": 0.06,
            }}
          />
          <Layer
            id="aoi-full-line"
            type="line"
            paint={{
              "line-color":   "#a78bfa",
              "line-width":   2,
              "line-opacity": 0.85,
              "line-dasharray": [2, 1],
            }}
          />
        </Source>
      )}

      {urbanAoi?.boundary && (
        <Source
          id="aoi-urban"
          type="geojson"
          data={{ type: "Feature", geometry: urbanAoi.boundary, properties: {} }}
        >
          <Layer
            id="aoi-urban-fill"
            type="fill"
            paint={{
              "fill-color":   "#fbbf24",
              "fill-opacity": 0.08,
            }}
          />
          <Layer
            id="aoi-urban-line"
            type="line"
            paint={{
              "line-color":   "#fbbf24",
              "line-width":   1.5,
              "line-opacity": 0.7,
            }}
          />
        </Source>
      )}
    </>
  );
}