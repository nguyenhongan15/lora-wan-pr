/**
 * SimulatorPanel.jsx — Persona 1 (B2B planner) what-if mode.
 *
 * Tách 2 component theo SRP:
 *   - SimulatorPanel:   UI bên trái (config + danh sách + nút chạy)
 *   - SimulatorLayer:   Mapbox marker + GeoJSON heatmap kết quả
 *
 * Single-file vì 2 component cùng vòng đời, dùng chung props (Simplicity First).
 */

import { Marker, Source, Layer } from "react-map-gl";
import S from "../strings";

const ENV_KEYS = ["urban", "suburban", "rural", "forest", "coastal", "mountain"];

// ─────────────────────────────────────────────────────────────
// Stale visual config
// Khi tham số đã đổi sau lần chạy mô phỏng gần nhất (isStale = true),
// heatmap được làm mờ để báo hiệu kết quả lỗi thời. Điều chỉnh ở đây nếu
// muốn stale "mờ" hơn (giảm OPACITY_STALE) hoặc đậm hơn (tăng).
// ─────────────────────────────────────────────────────────────
const OPACITY_FRESH = 0.7;
const OPACITY_STALE = 0.3;


// ─────────────────────────────────────────────────────────────
// Layer (markers gateway giả định + heatmap kết quả)
// ─────────────────────────────────────────────────────────────

export function SimulatorLayer({ transmitters, simResult, isStale = false }) {
  return (
    <>
      {/* Marker cho gateway giả định */}
      {transmitters.map((tx, i) => (
        <Marker
          key={i}
          longitude={tx.lng}
          latitude={tx.lat}
          anchor="center"
        >
          <div style={{
            width: 28, height: 28, borderRadius: "50%",
            background: "#7c3aed", border: "3px solid #fff",
            color: "#fff", fontSize: 12, fontWeight: 700,
            display: "flex", alignItems: "center", justifyContent: "center",
            boxShadow: "0 2px 10px rgba(0,0,0,0.5)",
          }}>
            S{i + 1}
          </div>
        </Marker>
      ))}

      {/* Kết quả mô phỏng — circle layer theo intensity */}
      {simResult && simResult.features?.length > 0 && (
        <Source id="sim-source" type="geojson" data={simResult}>
          <Layer
            id="sim-circles"
            type="circle"
            paint={{
              "circle-radius": ["interpolate", ["linear"], ["zoom"], 10, 4, 14, 8, 18, 14],
              "circle-color": ["interpolate", ["linear"], ["get", "intensity"],
                0,    "#313695",
                0.19, "#74add1",
                0.38, "#ffffbf",
                0.56, "#fdae61",
                0.75, "#f46d43",
                1,    "#a50026",
              ],
              // Stale → giảm opacity (xem block "Stale visual config" ở đầu file)
              "circle-opacity":      isStale ? OPACITY_STALE : OPACITY_FRESH,
              "circle-stroke-width": 0,
            }}
          />
        </Source>
      )}
    </>
  );
}


// ─────────────────────────────────────────────────────────────
// Control panel
// ─────────────────────────────────────────────────────────────

export default function SimulatorPanel({
  transmitters, onClear,
  environment,    onEnv,
  resolution,     onResolution,
  txPower,        onTxPower,
  txGain,         onTxGain,
  txHeight,       onTxHeight,
  useCalibration, onUseCalibration,
  running, onRun,
  isStale = false,
}) {
  const hasTx = transmitters.length > 0;

  return (
    <div style={panelStyle}>
      <div style={titleStyle}>{S.simulator.title}</div>
      <div style={hintStyle}>{S.simulator.hint}</div>

      <div style={badgeStyle}>
        {hasTx ? S.simulator.transmittersN(transmitters.length)
               : S.simulator.noTransmitters}
      </div>

      {/* Cảnh báo kết quả lỗi thời — text + icon (WCAG: không chỉ dựa trên màu) */}
      {isStale && (
        <div style={staleBadgeStyle} role="status" aria-live="polite">
          {S.simulator.staleWarning}
        </div>
      )}

      <Section label={S.simulator.sectionEnv}>
        <select value={environment} onChange={e => onEnv(e.target.value)} style={selectStyle}>
          {ENV_KEYS.map(k => (
            <option key={k} value={k} style={{ background: "#1a1a2e" }}>
              {S.simulator.envOptions[k]}
            </option>
          ))}
        </select>
      </Section>

      <Section label={S.simulator.sectionUseCalibration}>
        <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "#d1d5db", cursor: "pointer" }}>
          <input
            type="checkbox"
            checked={useCalibration}
            onChange={e => onUseCalibration(e.target.checked)}
            style={{ accentColor: "#534AB7", cursor: "pointer" }}
          />
          {S.simulator.useCalibrationHint}
        </label>
      </Section>

      <Section label={`${S.simulator.sectionResolution}: ${resolution} m`}>
        <input type="range" min={20} max={200} step={10}
               value={resolution} onChange={e => onResolution(Number(e.target.value))}
               style={rangeStyle} />
      </Section>

      <Section label={`${S.simulator.sectionTxPower}: ${txPower} dBm`}>
        <input type="range" min={0} max={16} step={1}
               value={txPower} onChange={e => onTxPower(Number(e.target.value))}
               style={rangeStyle} />
      </Section>

      <Section label={`${S.simulator.sectionAntenna}: ${txGain} dBi`}>
        <input type="range" min={0} max={20} step={0.5}
               value={txGain} onChange={e => onTxGain(Number(e.target.value))}
               style={rangeStyle} />
      </Section>

      <Section label={`${S.simulator.sectionAntennaHeight}: ${txHeight} m`}>
        <input type="range" min={5} max={100} step={1}
               value={txHeight} onChange={e => onTxHeight(Number(e.target.value))}
               style={rangeStyle} />
      </Section>

      <button onClick={onRun} disabled={!hasTx || running} style={btnPrimary(running || !hasTx)}>
        {running ? S.simulator.btnRunning : S.simulator.btnRun}
      </button>

      <button onClick={onClear} disabled={!hasTx} style={btnSecondary}>
        {S.simulator.btnClear}
      </button>
    </div>
  );
}


// ─────────────────────────────────────────────────────────────
// Local atoms (single-use)
// ─────────────────────────────────────────────────────────────

function Section({ label, children }) {
  return (
    <div style={{ marginTop: 6 }}>
      <div style={secLabelStyle}>{label}</div>
      {children}
    </div>
  );
}

const panelStyle = {
  background:   "rgba(20,20,30,0.88)",
  backdropFilter: "blur(8px)",
  borderRadius: 10,
  padding:      "10px 12px",
  border:       "1px solid rgba(255,255,255,0.1)",
  display:      "flex",
  flexDirection:"column",
  gap:          5,
};

const titleStyle  = { fontSize: 13, fontWeight: 600, color: "#c4b5fd" };
const hintStyle   = { fontSize: 11, color: "#9ca3af" };
const secLabelStyle = { fontSize: 11, color: "#9ca3af", marginBottom: 3 };
const badgeStyle  = {
  fontSize: 11, color: "#d1d5db",
  background: "rgba(255,255,255,0.05)",
  borderRadius: 6, padding: "5px 8px", marginTop: 4,
};
// Stale warning: nền vàng nhạt + text vàng đậm → đủ contrast (WCAG AA)
const staleBadgeStyle = {
  fontSize: 11, color: "#fde68a",
  background: "rgba(245, 158, 11, 0.15)",
  border: "1px solid rgba(245, 158, 11, 0.4)",
  borderRadius: 6, padding: "5px 8px", marginTop: 2,
};
const selectStyle = {
  background: "rgba(255,255,255,0.08)",
  border: "1px solid rgba(255,255,255,0.15)",
  color: "#f9fafb", borderRadius: 6, padding: "4px 8px",
  fontSize: 12, width: "100%", cursor: "pointer",
};
const rangeStyle  = { width: "100%", accentColor: "#534AB7", cursor: "pointer" };
const btnPrimary  = (disabled) => ({
  marginTop: 6,
  padding: "8px 12px", borderRadius: 8, border: "none",
  cursor: disabled ? "not-allowed" : "pointer",
  fontSize: 13, fontWeight: 500,
  background: disabled ? "#3d3d5c" : "#7F77DD",
  color: "#fff", opacity: disabled ? 0.6 : 1,
});
const btnSecondary = {
  padding: "6px 10px", borderRadius: 7, border: "none",
  cursor: "pointer", fontSize: 12, fontWeight: 500,
  background: "rgba(255,255,255,0.07)", color: "#d1d5db",
};