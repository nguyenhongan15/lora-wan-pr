/**
 * ScatterLayer.jsx — Mapbox GL circle layer cho điểm đo RSSI.
 *
 * Backend đã trả camelCase: rssiDbm, snrDb, spreadingFactor, gatewayId.
 */
import { useMemo } from "react";
import { Source, Layer, Popup } from "react-map-gl";
import { rssiLabel, fmt, snrMargin, snrMarginLabel, SNR_THRESHOLD } from "../utils";
import { RSSI_SCALE_MIN, RSSI_WEAK, RSSI_MEDIUM, RSSI_STRONG, RSSI_SCALE_MAX } from "../utils/rssiThresholds";
import S from "../strings";

export const SCATTER_LAYER_ID = "scatter-circles";

// Cold → Hot stops tại các ngưỡng CVT
const CIRCLE_COLOR = ["interpolate", ["linear"], ["get", "rssi"],
  RSSI_SCALE_MIN, "#313695",
  RSSI_WEAK,      "#74add1",
  RSSI_MEDIUM,    "#ffffbf",
  RSSI_STRONG,    "#fdae61",
  -70,            "#f46d43",
  RSSI_SCALE_MAX, "#a50026",
];

// Opacity theo SNR margin — điểm unreliable mờ hơn
const CIRCLE_OPACITY = [
  "case",
  ["==", ["get", "snrMargin"], null], 0.88,
  [">",  ["get", "snrMargin"], 0],    0.90,
  /* unreliable */                     0.45,
];

function Row({ label, value, mono, accent }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
      <span style={{ color: "#64748b" }}>{label}</span>
      <span style={{
        fontWeight: 600,
        fontFamily: mono ? "monospace" : "inherit",
        color: accent ?? "inherit",
      }}>{value}</span>
    </div>
  );
}

function MarginBadge({ margin }) {
  if (margin == null) return null;
  const { bg, text } =
    margin > 6 ? { bg: "rgba(34,197,94,0.15)",  text: "#22c55e" } :
    margin > 2 ? { bg: "rgba(234,179,8,0.15)",  text: "#eab308" } :
    margin > 0 ? { bg: "rgba(249,115,22,0.15)", text: "#f97316" } :
                 { bg: "rgba(239,68,68,0.15)",  text: "#ef4444" };

  return (
    <span style={{
      display: "inline-block", marginLeft: 6,
      padding: "1px 6px", borderRadius: 4, fontSize: 10,
      background: bg, color: text, fontWeight: 700,
    }}>
      {margin > 0 ? `+${margin}` : margin} dB
    </span>
  );
}

export default function ScatterLayer({ features = [], popupInfo, onPopup }) {
  // GeoJSON thêm field dẫn xuất `rssi` + `snrMargin` vào properties
  const geojson = useMemo(() => ({
    type: "FeatureCollection",
    features: features.map(f => {
      const p = f.properties;
      const margin = snrMargin(p.snrDb, p.spreadingFactor);
      return {
        ...f,
        properties: {
          ...p,
          rssi:      p.rssiDbm,    // dùng cho expression ở CIRCLE_COLOR
          snrMargin: margin,
        },
      };
    }),
  }), [features]);

  // Đường nối từ điểm click → nearest gateway
  const lineGeojson = useMemo(() => {
    if (!popupInfo?.nearest) return null;
    const { gateway } = popupInfo.nearest;
    return {
      type: "Feature",
      geometry: {
        type: "LineString",
        coordinates: [
          [popupInfo.longitude, popupInfo.latitude],
          [gateway.longitude, gateway.latitude],
        ],
      },
    };
  }, [popupInfo]);

  const popupMargin = useMemo(() => {
    if (!popupInfo?.props) return null;
    return snrMargin(popupInfo.props.snrDb, popupInfo.props.spreadingFactor);
  }, [popupInfo]);

  if (features.length === 0) return null;

  const sf = popupInfo?.props?.spreadingFactor;

  return (
    <>
      {/* Scatter circles */}
      <Source id="scatter-source" type="geojson" data={geojson}>
        <Layer
          id={SCATTER_LAYER_ID}
          type="circle"
          paint={{
            "circle-radius": ["interpolate", ["linear"], ["zoom"],
              10, 3,  14, 5,  18, 9,
            ],
            "circle-color":        CIRCLE_COLOR,
            "circle-opacity":      CIRCLE_OPACITY,
            "circle-stroke-width": 0.8,
            "circle-stroke-color": "rgba(255,255,255,0.4)",
          }}
        />
      </Source>

      {/* Đường nối đến nearest gateway */}
      {lineGeojson && (
        <Source id="nearest-gw-line" type="geojson" data={lineGeojson}>
          <Layer
            id="nearest-gw-line-layer"
            type="line"
            paint={{
              "line-color":     "#534AB7",
              "line-width":     2,
              "line-opacity":   0.75,
              "line-dasharray": [3, 2],
            }}
          />
        </Source>
      )}

      {/* Popup */}
      {popupInfo && (
        <Popup
          longitude={popupInfo.longitude}
          latitude={popupInfo.latitude}
          onClose={() => onPopup?.(null)}
          closeButton
          anchor="bottom"
          style={{ zIndex: 10 }}
        >
          <div style={{ fontSize: 12, lineHeight: 1.85, color: "#1e293b", minWidth: 185 }}>

            <div style={{
              fontWeight: 700, fontSize: 13, marginBottom: 6,
              paddingBottom: 5, borderBottom: "1px solid #e2e8f0",
              display: "flex", alignItems: "center",
            }}>
              {rssiLabel(popupInfo.props.rssiDbm)}
            </div>

            <Row label={S.scatter.popupRssi} value={fmt(popupInfo.props.rssiDbm, " dBm")} />
            <Row label={S.scatter.popupSnr}  value={fmt(popupInfo.props.snrDb, " dB")} />
            <Row label={S.scatter.popupSf}   value={`SF${sf ?? "?"}`} />

            {sf != null && (
              <div style={{ marginTop: 7, paddingTop: 6, borderTop: "1px solid #e2e8f0" }}>
                <div style={{ fontSize: 10, color: "#94a3b8", marginBottom: 4, fontWeight: 600, letterSpacing: "0.04em" }}>
                  {S.scatter.SNR_link}
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, marginBottom: 2 }}>
                  <span style={{ color: "#64748b" }}>Ngưỡng SF{sf}</span>
                  <span style={{ fontWeight: 600, fontFamily: "monospace" }}>
                    {SNR_THRESHOLD[sf]} dB
                  </span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 11 }}>
                  <span style={{ color: "#64748b" }}>Margin</span>
                  <span style={{ display: "flex", alignItems: "center" }}>
                    <MarginBadge margin={popupMargin} />
                    <span style={{ marginLeft: 4, fontSize: 10, color: "#94a3b8" }}>
                      {snrMarginLabel(popupMargin)}
                    </span>
                  </span>
                </div>
              </div>
            )}

            {popupInfo.nearest ? (
              <div style={{ marginTop: 7, paddingTop: 6, borderTop: "1px solid #e2e8f0" }}>
                <div style={{ fontSize: 10, color: "#94a3b8", marginBottom: 3, fontWeight: 600, letterSpacing: "0.04em" }}>
                  📡 GATEWAY GẦN NHẤT
                </div>
                <Row
                  label={popupInfo.nearest.gateway.name || "Gateway"}
                  value={`${(popupInfo.nearest.distanceKm * 1000).toFixed(0)} m`}
                />
                <div style={{ fontSize: 10, color: "#94a3b8", fontFamily: "monospace", marginTop: 1 }}>
                  {popupInfo.nearest.gateway.gatewayEui?.slice(0, 16) ?? popupInfo.props.gatewayId?.slice(0, 8)}
                </div>
              </div>
            ) : (
              <div style={{ marginTop: 6, color: "#94a3b8", fontSize: 11 }}>
                {S.scatter.popupGw} {popupInfo.props.gatewayId?.slice(0, 8) ?? S.scatter.popupUnknown}…
              </div>
            )}
          </div>
        </Popup>
      )}
    </>
  );
}
