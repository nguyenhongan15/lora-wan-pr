import { MAP_STYLES, LIGHT_PRESETS, isStandard } from "../styles/mapbox";
import S from "../strings";
import ExportButtons from "./ExportButtons";

const MODES = [
  { key: "scatter",   label: S.toolbar.modes.scatter },
  { key: "heat",      label: S.toolbar.modes.heat },
  { key: "ml-heat",   label: S.toolbar.modes["ml-heat"] },
];

const SF_OPTIONS = [7, 8, 9, 10, 11, 12];

const ML_ALGORITHMS = [
  { key: "idw",              label: "IDW" },
  { key: "kriging",          label: "Kriging" },
  { key: "rbf",              label: "RBF" },
  { key: "delaunay",         label: "Delaunay" },
  { key: "xgboost",          label: "XGBoost" },
  { key: "random_forest",    label: "Random Forest" },
  { key: "gaussian_process", label: "Gaussian Process" },
];

export default function Toolbar({
  mode, onMode,
  campaignId, onCampaign, campaigns,
  onRunML, mlRunning, mlDone,
  mlAlgorithm, onMlAlgorithm,
  showGateways, onToggleGateways,
  showRangeCircles,  onToggleRangeCircles,
  rangeKm,           onRangeKm,
  mapStyle,     onMapStyle,
  lightPreset,  onLightPreset,
  rssiMin, onRssiMin,
  sfFilter, onSfFilter,
}) {
  const std = isStandard(mapStyle);

  const panel = {
    background: "rgba(20,20,30,0.88)", backdropFilter: "blur(8px)",
    borderRadius: 10, padding: "10px 12px",
    border: "1px solid rgba(255,255,255,0.1)",
    display: "flex", flexDirection: "column", gap: 5,
  };
  const secLabel = { fontSize: 11, color: "#9ca3af", marginBottom: 3 };
  const btn = (active) => ({
    padding: "6px 10px", borderRadius: 7, border: "none",
    cursor: "pointer", fontSize: 12, fontWeight: 500, textAlign: "left",
    background: active ? "#534AB7" : "rgba(255,255,255,0.07)",
    color: active ? "#fff" : "#d1d5db", transition: "all .15s",
  });
  const toggleBtn = (active) => ({
    borderRadius: 8, padding: "7px 11px", textAlign: "left",
    border: `1px solid ${active ? "rgba(83,74,183,0.55)" : "rgba(255,255,255,0.1)"}`,
    cursor: "pointer", fontSize: 12, fontWeight: 500,
    background: active ? "rgba(83,74,183,0.3)" : "rgba(255,255,255,0.05)",
    color: active ? "#c4b5fd" : "#d1d5db", transition: "all .15s",
  });

  return (
    <div style={{
      position: "absolute", top: 12, left: 12, zIndex: 1000,
      display: "flex", flexDirection: "column", gap: 8,
      maxHeight: "calc(100vh - 24px)", overflowY: "auto",
      width: 240,
    }}>
      {/* Campaign */}
      <div style={panel}>
        <div style={secLabel}>{S.toolbar.sectionCampaign}</div>
        <select value={campaignId} onChange={e => onCampaign(e.target.value)} style={{
          background: "rgba(255,255,255,0.08)", border: "1px solid rgba(255,255,255,0.15)",
          color: "#f9fafb", borderRadius: 6, padding: "4px 8px",
          fontSize: 12, width: "100%", cursor: "pointer",
        }}>
          {campaigns.map(c => (
            <option key={c.id} value={c.id} style={{ background: "#1a1a2e" }}>{c.name}</option>
          ))}
        </select>
      </div>

      {/* Chế độ hiển thị */}
      <div style={panel}>
        <div style={secLabel}>{S.toolbar.sectionDisplayMode}</div>
        {MODES.map(m => (
          <button key={m.key} style={btn(mode === m.key)} onClick={() => onMode(m.key)}>
            {m.label}
          </button>
        ))}
      </div>

      {/* Nền bản đồ */}
      <div style={panel}>
        <div style={secLabel}>{S.toolbar.sectionMapStyle}</div>
        {MAP_STYLES.map(s => (
          <button key={s.key} style={btn(mapStyle === s.key)} onClick={() => onMapStyle(s.key)}>
            {s.label}
          </button>
        ))}
      </div>

      {/* Ánh sáng */}
      {std && (
        <div style={panel}>
          <div style={secLabel}>{S.toolbar.sectionLighting}</div>
          {LIGHT_PRESETS.map(p => (
            <button key={p.key} style={btn(lightPreset === p.key)} onClick={() => onLightPreset(p.key)}>
              {p.label}
            </button>
          ))}
        </div>
      )}

      {/* Lớp bản đồ */}
      <div style={panel}>
        <div style={secLabel}>{S.toolbar.sectionLayers}</div>
        <button onClick={onToggleGateways} style={toggleBtn(showGateways)}>
          {showGateways ? S.toolbar.hideGateways : S.toolbar.showGateways}
        </button>
        {showGateways && (
          <>
            <button onClick={onToggleRangeCircles} style={toggleBtn(showRangeCircles)}>
              {showRangeCircles ? S.toolbar.hideRangeCircles : S.toolbar.showRangeCircles}
            </button>
            {showRangeCircles && (
              <div style={{ paddingTop: 4 }}>
                <div style={{ ...secLabel, marginBottom: 4 }}>
                  {S.toolbar.radius}
                  <span style={{ float: "right", color: "#f9fafb", fontWeight: 600 }}>
                    {rangeKm} km
                  </span>
                </div>
                <input
                  type="range" min={0.5} max={10} step={0.5}
                  value={rangeKm}
                  onChange={e => onRangeKm(Number(e.target.value))}
                  style={{ width: "100%", accentColor: "#534AB7", cursor: "pointer" }}
                />
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "#6b7280" }}>
                <span>{S.toolbar.radiusMin}</span><span>{S.toolbar.radiusMid}</span><span>{S.toolbar.radiusMax}</span>
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {/* Filter RSSI */}
      <div style={panel}>
        <div style={secLabel}>
          {S.toolbar.sectionRssiFilter}
          <span style={{ float: "right", color: "#f9fafb", fontWeight: 600 }}>
            {rssiMin} {S.toolbar.rssiUnit}
          </span>
        </div>
        <input
          type="range" min={-120} max={-40} step={5}
          value={rssiMin}
          onChange={e => onRssiMin(Number(e.target.value))}
          style={{ width: "100%", accentColor: "#534AB7", cursor: "pointer" }}
        />
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "#6b7280" }}>
          <span>{S.toolbar.rssiAxisMin}</span>
          <span>{S.toolbar.rssiAxisMid}</span>
          <span>{S.toolbar.rssiAxisMax}</span>
        </div>
      </div>

      {/* Filter Spreading Factor */}
      <div style={panel}>
        <div style={secLabel}>
          {S.toolbar.sectionSF}
          <span
            style={{ float: "right", color: "#9ca3af", fontSize: 10, cursor: "pointer" }}
            onClick={() => onSfFilter(SF_OPTIONS)}
          >
            {S.toolbar.sfAll}
          </span>
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
          {SF_OPTIONS.map(sf => {
            const active = sfFilter.includes(sf);
            return (
              <button
                key={sf}
                onClick={() => {
                  if (active && sfFilter.length === 1) return;
                  onSfFilter(active
                    ? sfFilter.filter(s => s !== sf)
                    : [...sfFilter, sf].sort()
                  );
                }}
                style={{
                  padding: "4px 8px", borderRadius: 6, border: "none",
                  cursor: "pointer", fontSize: 11, fontWeight: 600,
                  background: active ? "#534AB7" : "rgba(255,255,255,0.07)",
                  color: active ? "#fff" : "#6b7280",
                  transition: "all .15s", minWidth: 34,
                }}
              >
                SF{sf}
              </button>
            );
          })}
        </div>
      </div>

      {/* Thuật toán dự đoán */}
      <div style={panel}>
        <div style={secLabel}>Thuật toán</div>
        <select
          value={mlAlgorithm}
          onChange={e => onMlAlgorithm(e.target.value)}
          style={{
            background: "rgba(255,255,255,0.08)", border: "1px solid rgba(255,255,255,0.15)",
            color: "#f9fafb", borderRadius: 6, padding: "4px 8px",
            fontSize: 12, width: "100%", cursor: "pointer",
          }}
        >
          {ML_ALGORITHMS.map(a => (
            <option key={a.key} value={a.key} style={{ background: "#1a1a2e" }}>{a.label}</option>
          ))}
        </select>
      </div>

      {/* Chạy ML */}
      <button onClick={onRunML} disabled={mlRunning} style={{
        padding: "8px 12px", borderRadius: 10, border: "none",
        cursor: mlRunning ? "not-allowed" : "pointer",
        fontSize: 13, fontWeight: 500, transition: "all .2s",
        background: mlRunning ? "#3d3d5c" : mlDone ? "#1D9E75" : "#7F77DD",
        color: "#fff",
      }}>
        {mlRunning ? S.toolbar.mlRunning : mlDone ? S.toolbar.mlRerun : S.toolbar.mlRun}
      </button>

      {/* Exports */}
      <div style={panel}>
        <div style={secLabel}>{S.toolbar.sectionExport}</div>
        <ExportButtons campaignId={campaignId} />
      </div>
    </div>
  );
}