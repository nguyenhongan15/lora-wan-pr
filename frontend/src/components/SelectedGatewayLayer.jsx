/**
 * SelectedGatewayLayer.jsx — Render K gateway được chọn từ optimization run.
 * Numbered theo rank (1, 2, 3...). Top 3 màu đỏ, còn lại tím.
 */

import { Marker } from "react-map-gl";

export default function SelectedGatewayLayer({ selections = [] }) {
  if (!selections.length) return null;

  return (
    <>
      {selections.map(s => (
        <Marker
          key={s.candidateId}
          longitude={s.lng}
          latitude={s.lat}
          anchor="center"
        >
          <div
            title={`Rank ${s.rank} — ${s.source} — gain ${s.marginalGain.toFixed(1)} — cost ${s.cost.toFixed(2)}`}
            style={{
              width: 30, height: 30, borderRadius: "50%",
              background: s.rank <= 3 ? "#dc2626" : "#7c3aed",
              color: "#fff", fontSize: 12, fontWeight: 700,
              display: "flex", alignItems: "center", justifyContent: "center",
              border: "3px solid #fff",
              boxShadow: "0 2px 12px rgba(0,0,0,0.6)",
              cursor: "pointer",
            }}
          >
            {s.rank}
          </div>
        </Marker>
      ))}
    </>
  );
}