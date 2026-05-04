/**
 * GatewayMarkers.jsx
 * - Marker + Popup thông tin gateway
 * - Vòng tròn bán kính lý thuyết LoRa (có thể bật/tắt, điều chỉnh km)
 *
 * Backend trả camelCase: gatewayEui, altitudeM, antennaHeightM, txPowerDbm, antennaType
 */
import { useState, useMemo } from "react";
import { Marker, Popup, Source, Layer } from "react-map-gl";
import { createCirclePolygon } from "../utils";
import S from "../strings";

const RING_COLORS = [
  "#534AB7", "#1D9E75", "#EF9F27", "#E24B4A",
  "#3B8BD4", "#7B21E8", "#F472B6", "#14B8A6",
];

function GwPin({ color }) {
  return (
    <div style={{
      width: 32, height: 32, borderRadius: "50%",
      background: color, border: "3px solid #fff",
      boxShadow: "0 2px 10px rgba(0,0,0,0.55)",
      display: "flex", alignItems: "center", justifyContent: "center",
      fontSize: 13, color: "#fff", fontWeight: 700,
      cursor: "pointer", userSelect: "none",
    }}>
      G
    </div>
  );
}

export default function GatewayMarkers({
  gateways = [],
  showRangeCircles = true,
  rangeKm = 2,
}) {
  const [selected, setSelected] = useState(null);

  const circleGeojson = useMemo(() => ({
    type: "FeatureCollection",
    features: gateways
      .filter(gw => gw.latitude && gw.longitude)
      .map((gw, i) => ({
        ...createCirclePolygon([gw.longitude, gw.latitude], rangeKm),
        properties: { id: gw.id, color: RING_COLORS[i % RING_COLORS.length] },
      })),
  }), [gateways, rangeKm]);

  return (
    <>
      {/* Vòng tròn bán kính lý thuyết */}
      {showRangeCircles && gateways.length > 0 && (
        <Source id="gw-range-source" type="geojson" data={circleGeojson}>
          <Layer id="gw-range-fill" type="fill" paint={{
            "fill-color": ["get", "color"], "fill-opacity": 0.07,
          }}/>
          <Layer id="gw-range-line" type="line" paint={{
            "line-color": ["get", "color"], "line-opacity": 0.6,
            "line-width": 1.8, "line-dasharray": [4, 3],
          }}/>
        </Source>
      )}

      {/* Markers */}
      {gateways.map((gw, i) => {
        if (!gw.latitude || !gw.longitude) return null;
        const color = RING_COLORS[i % RING_COLORS.length];
        return (
          <Marker
            key={gw.id}
            longitude={gw.longitude}
            latitude={gw.latitude}
            anchor="center"
            onClick={e => { e.originalEvent.stopPropagation(); setSelected(gw); }}
          >
            <GwPin color={color} />
          </Marker>
        );
      })}

      {/* Popup */}
      {selected && (
        <Popup
          longitude={selected.longitude}
          latitude={selected.latitude}
          anchor="bottom"
          onClose={() => setSelected(null)}
          closeButton
          style={{ zIndex: 20 }}
        >
          <div style={{ fontSize: 12, lineHeight: 1.9, color: "#1e293b", minWidth: 170 }}>
            <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 2 }}>
              {selected.name || S.gateway.defaultName}
            </div>
            {selected.gatewayEui && (
              <div style={{ color: "#64748b", fontFamily: "monospace", fontSize: 11 }}>
                {selected.gatewayEui}
              </div>
            )}
            {selected.altitudeM != null && (
              <div>{S.gateway.altitude} <b>{selected.altitudeM}</b> {S.gateway.altitudeUnit}</div>
            )}
            {selected.antennaHeightM != null && (
              <div>{S.gateway.antenna} <b>{selected.antennaHeightM}</b> {S.gateway.antennaUnit}</div>
            )}
            {showRangeCircles && (
              <div style={{
                marginTop: 6, paddingTop: 6,
                borderTop: "1px solid #e2e8f0",
                color: "#7c3aed", fontWeight: 600, fontSize: 11,
              }}>
                📡 Bán kính lý thuyết: {rangeKm} km
              </div>
            )}
          </div>
        </Popup>
      )}
    </>
  );
}
