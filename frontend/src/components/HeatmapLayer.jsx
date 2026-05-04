// /**
//  * HeatmapLayer.jsx — CƯỜNG ĐỘ TÍN HIỆU
//  * Thang màu Cold → Hot (RdYlBu):
//  *   Xanh đậm (yếu) → Xanh nhạt → Vàng → Cam → Đỏ đậm (mạnh)
//  *
//  * Props:
//  *   points    — [[lat, lng, intensity], ...] từ filteredHeatPoints (App.jsx)
//  *   radius    — bán kính heatmap (px)
//  *   base      — exponential base tự động từ rssiConfig.js
//  */
// import { useMemo } from "react";
// import { Source, Layer } from "react-map-gl";

// export default function HeatmapLayer({ points = [], radius = 25, base = 3 }) {
//   const geojson = useMemo(() => ({
//     type: "FeatureCollection",
//     features: points.map(([lat, lng, intensity]) => ({
//       type: "Feature",
//       geometry: { type: "Point", coordinates: [lng, lat] },
//       properties: { intensity: Math.max(0, Math.min(1, intensity ?? 0)) },
//     })),
//   }), [points]);

//   if (points.length === 0) return null;

//   return (
//     <Source id="heatmap-source" type="geojson" data={geojson}>

//       {/* Heatmap layer (zoom 0 → 16) */}
//       <Layer
//         id="heatmap-heat"
//         type="heatmap"
//         maxzoom={16}
//         paint={{
//           // base tự động từ calcHeatmapBase() trong rssi.js
//           // điểm yếu → weight gần 0, điểm mạnh → weight = 1
//           "heatmap-weight": [
//             "interpolate", ["exponential", base], ["get", "intensity"],
//             0,    0,      // RSSI = min  — không đóng góp
//             0.10, 0.005,  // rất yếu     — gần vô hình
//             0.20, 0.01,   // rất yếu     — vô hình
//             0.30, 0.03,   // yếu         — rất mờ
//             0.40, 0.07,   // yếu         — mờ
//             0.50, 0.15,   // trung bình  — bắt đầu thấy
//             0.60, 0.28,   // trung bình  — thấy rõ hơn
//             0.70, 0.45,   // khá tốt     — rõ
//             0.80, 0.65,   // tốt         — rõ
//             0.90, 0.82,   // mạnh        — sáng
//             1,    1.0,    // RSSI = max  — sáng nhất
//           ],

//           "heatmap-intensity": [
//             "interpolate", ["cubic-bezier", 0.4, 0, 0.6, 1], ["zoom"],
//             0,  0.5,   // zoom xa     — nhạt tránh bão hòa
//             10, 1.0,   // zoom thành phố — bình thường
//             13, 2.0,   // zoom khu vực   — tăng bù density
//             16, 3.5,   // zoom đường phố — đậm nhất
//           ],
          
//           // Cold → Hot (RdYlBu)
//           "heatmap-color": [
//             "interpolate", ["linear"], ["heatmap-density"],
//             0,    "rgba(49,54,149,0)",
//             0.01, "rgba(49,54,149,0.8)",
//             0.2,  "rgba(116,173,209,0.9)",
//             0.4,  "rgba(255,255,191,0.92)",
//             0.6,  "rgba(253,174,97,0.95)",
//             0.8,  "rgba(244,109,67,0.97)",
//             1,    "rgba(165,0,38,1)",
//           ],

//           "heatmap-radius": [
//             "interpolate", ["linear"], ["zoom"],
//             0,  3,
//             8,  radius * 0.5,
//             12, radius,
//             15, radius * 1.8,
//           ],

//           "heatmap-opacity": 0.9,
//         }}
//       />

//       {/* Circle chính xác khi zoom gần (zoom 13+) */}
//       <Layer
//         id="heatmap-point"
//         type="circle"
//         minzoom={13}
//         paint={{
//           "circle-radius": ["interpolate", ["linear"], ["zoom"],
//             13, 3,
//             16, 7,
//             18, 12,
//           ],
//           // Màu circle đồng bộ thang RdYlBu với heatmap
//           "circle-color": ["interpolate", ["linear"], ["get", "intensity"],
//             0,    "#313695",
//             0.25, "#74add1",
//             0.50, "#ffffbf",
//             0.75, "#fdae61",
//             1,    "#a50026",
//           ],
//           "circle-opacity": ["interpolate", ["linear"], ["zoom"],
//             13, 0,
//             14, 0.9,
//           ],
//           "circle-stroke-width": 0.5,
//           "circle-stroke-color": "rgba(255,255,255,0.4)",
//         }}
//       />
//     </Source>
//   );
// }


// /**
//  * HeatmapLayer.jsx — MẬT ĐỘ ĐIỂM ĐO
//  * Hiển thị nơi nào đã đo nhiều/ít — không phản ánh RSSI.
//  * Màu: xanh (ít điểm đo) → đỏ (nhiều điểm đo)
//  */
// import { useMemo } from "react";
// import { Source, Layer } from "react-map-gl";

// export default function HeatmapLayer({ points = [], radius = 25 }) {
//   const geojson = useMemo(() => ({
//     type: "FeatureCollection",
//     features: points.map(([lat, lng]) => ({
//       type: "Feature",
//       geometry: { type: "Point", coordinates: [lng, lat] },
//       properties: {},
//     })),
//   }), [points]);

//   if (points.length === 0) return null;

//   return (
//     <Source id="heatmap-source" type="geojson" data={geojson}>
//       <Layer
//         id="heatmap-heat"
//         type="heatmap"
//         maxzoom={18}
//         paint={{
//           // Mỗi điểm đóng góp bằng nhau — chỉ thể hiện mật độ
//           "heatmap-weight": 1,

//           "heatmap-intensity": [
//             "interpolate", ["linear"], ["zoom"],
//             0,  0.5,
//             10, 1.0,
//             13, 2.0,
//             16, 3.5,
//           ],

//           // Xanh (ít đo) → vàng → đỏ (nhiều đo)
//           "heatmap-color": [
//             "interpolate", ["linear"], ["heatmap-density"],
//             0,    "rgba(49,54,149,0)",
//             0.1,  "rgba(49,54,149,0.8)",
//             0.3,  "rgba(116,173,209,0.9)",
//             0.5,  "rgba(255,255,191,0.92)",
//             0.7,  "rgba(253,174,97,0.95)",
//             0.85, "rgba(244,109,67,0.97)",
//             1,    "rgba(165,0,38,1)",
//           ],

//           "heatmap-radius": [
//             "interpolate", ["linear"], ["zoom"],
//             0,  1,
//             8,  radius * 0.2,
//             12, radius,
//             15, radius * 1.8,
//           ],

//           "heatmap-opacity": [
//             "interpolate", ["linear"], ["zoom"],
//             13, 0.9,
//             16, 0.3,
//           ],
//         }}
//       />

//       {/* Điểm xám khi zoom gần — chỉ hiện vị trí đo, không có màu RSSI */}
//       <Layer
//         id="heatmap-point"
//         type="circle"
//         minzoom={13}
//         paint={{
//           "circle-radius": ["interpolate", ["linear"], ["zoom"],
//             13, 2,
//             16, 5,
//             18, 9,
//           ],
//           "circle-color": "#74add1",
//           "circle-opacity": ["interpolate", ["linear"], ["zoom"],
//             13, 0,
//             14, 0.8,
//           ],
//           "circle-stroke-width": 0.5,
//           "circle-stroke-color": "rgba(255,255,255,0.5)",
//         }}
//       />
//     </Source>
//   );
// }


/** GeoJSON Grid Layer — Heatmap theo lưới ô vuông
 * HeatmapLayer.jsx — Heatmap thô theo cường độ tín hiệu
 * Chia lưới ô vuông, mỗi ô = RSSI trung bình các điểm đo trong ô.
 * Màu đúng theo RSSI, không bị ảnh hưởng bởi mật độ điểm.
 * Zoom thay đổi → cellSize thay đổi → rebuild grid tự động.
 */
/**
 * HeatmapLayer.jsx — Heatmap thô cường độ tín hiệu LoRaWAN
 * Áp dụng quy chuẩn:
 * - LoRa Alliance Coverage Verification: lưới 50m đô thị, 100m ngoại ô
 */
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
 
  const maxCount = Math.max(...Array.from(cells.values()).map(c => c.count), 1);
 
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