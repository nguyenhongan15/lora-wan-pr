import { useMemo, useState, useEffect } from "react";
import { Source, Layer, useMap } from "react-map-gl";
import { RSSI_WEAK, INTENSITY_AT_WEAK, INTENSITY_AT_MEDIUM, INTENSITY_AT_STRONG } from "../utils/rssiThresholds";
 
const M_PER_DEG_LAT = 111320;
const M_PER_DEG_LNG = 111320 * Math.cos(16 * Math.PI / 180);
 
// Điểm dưới RSSI_WEAK (−120 dBm) bị loại — CVT reliability floor
const RSSI_MIN_RELIABLE = RSSI_WEAK;
 
// Kích thước ô theo LoRa Alliance Coverage Verification
function getCellSize(zoom) {
  if (zoom < 11) return 500;   // nông thôn
  if (zoom < 12) return 200;   // ngoại ô xa
  if (zoom < 13) return 100;   // ngoại ô (LoRa Alliance: 100m)
  if (zoom < 14) return 50;    // đô thị (LoRa Alliance: 50m) ← chuẩn chính
  if (zoom < 15) return 25;    // đô thị dày đặc
  return 10;                   // chi tiết cao
}
 
function buildGrid(points, cellSizeM) {
  if (!points.length) return [];
 
  const cellLat = cellSizeM / M_PER_DEG_LAT;
  const cellLng = cellSizeM / M_PER_DEG_LNG;
 
  let minLat = Infinity, minLng = Infinity;
  for (const [lat, lng] of points) {
    if (lat < minLat) minLat = lat;
    if (lng < minLng) minLng = lng;
  }
  minLat -= cellLat;
  minLng -= cellLng;
 
  const cells = new Map();
  for (const [lat, lng, intensity, rssi] of points) {
    // Lọc điểm dưới ngưỡng LoRa Alliance (−120 dBm)
    if (rssi != null && rssi < RSSI_MIN_RELIABLE) continue;
 
    const row = Math.floor((lat - minLat) / cellLat);
    const col = Math.floor((lng - minLng) / cellLng);
    const key = `${row}_${col}`;
    const c = cells.get(key);
    if (c) { c.sum += intensity; c.count++; }
    else cells.set(key, { row, col, sum: intensity, count: 1 });
  }
 
  return Array.from(cells.values()).map(({ row, col, sum, count }) => {
    const lat0 = minLat + row * cellLat;
    const lng0 = minLng + col * cellLng;
    return {
      type: "Feature",
      geometry: {
        type: "Polygon",
        coordinates: [[
          [lng0,           lat0],
          [lng0 + cellLng, lat0],
          [lng0 + cellLng, lat0 + cellLat],
          [lng0,           lat0 + cellLat],
          [lng0,           lat0],
        ]],
      },
      properties: {
        intensity: sum / count,
        // Độ tin cậy: ô có ≥ 3 điểm = tin cậy hoàn toàn (LoRa Alliance: ≥3 packet/điểm)
        reliability: Math.min(1, count / 3),
        count,
      },
    };
  });
}
 
export default function HeatmapLayer({ points = [] }) {
  const { main: mapRef } = useMap();
  const [zoom, setZoom] = useState(13);
 
  useEffect(() => {
    if (!mapRef) return;
    const map = mapRef.getMap();
    const onZoom = () => setZoom(Math.round(map.getZoom()));
    map.on("zoom", onZoom);
    // Sync zoom ngay khi map sẵn sàng — intentional init
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setZoom(Math.round(map.getZoom()));
    return () => map.off("zoom", onZoom);
  }, [mapRef]);
 
  const cellSizeM = getCellSize(zoom);
 
  // Thêm rssi vào points để filter
  const geojson = useMemo(() => {
    const features = buildGrid(points, cellSizeM);
    return { type: "FeatureCollection", features };
  }, [points, cellSizeM]);
 
  if (!points.length) return null;
 
  return (
    <Source id="heatmap-source" type="geojson" data={geojson}>
      {/* Fill ô theo RSSI trung bình — thang màu LoRa Alliance */}
      <Layer
        id="heatmap-fill"
        type="fill"
        paint={{
          "fill-color": ["interpolate", ["linear"], ["get", "intensity"],
            // Intensity tại các ngưỡng CVT = (rssi + 135) / 80:
            //   INTENSITY_AT_WEAK   = 0.1875 → −120 dBm (floor)
            //   INTENSITY_AT_MEDIUM = 0.375  → −105 dBm (Weak/Medium)
            //   INTENSITY_AT_STRONG = 0.5625 → − 90 dBm (Medium/Strong)
            0,                    "#313695",  // floor
            INTENSITY_AT_WEAK,    "#74add1",  // −120 dBm
            INTENSITY_AT_MEDIUM,  "#ffffbf",  // −105 dBm
            INTENSITY_AT_STRONG,  "#fdae61",  //  −90 dBm
            1,                    "#a50026",  //  −55 dBm
          ],
          // Ô ít điểm đo → mờ hơn (kém tin cậy hơn)
          "fill-opacity": ["*",
            0.8,
            ["get", "reliability"],
          ],
        }}
      />
 
      {/* Viền ô — hiện khi zoom gần */}
      <Layer
        id="heatmap-outline"
        type="line"
        paint={{
          "line-color": "rgba(255,255,255,0.25)",
          "line-width": 0.4,
          "line-opacity": ["interpolate", ["linear"], ["zoom"],
            13, 0,
            15, 0.6,
          ],
        }}
      />
    </Source>
  );
}