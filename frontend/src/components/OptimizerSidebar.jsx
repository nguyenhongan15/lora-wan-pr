/**
 * OptimizerSidebar.jsx — Combined optimizer panel.
 *
 * Sections (collapsible):
 *   1. Layers toggle (AOI + Candidates visibility)
 *   2. Config form (mode, K/target, SF, txPower, txHeight, costAware)
 *   3. Result (sau khi run): metrics + warnings + top selections
 *   4. History (recent runs, click load)
 */

import { useState } from "react";
import S from "../strings";

export default function OptimizerSidebar({
  // Layer toggles
  showAoi,         onToggleAoi,
  showUrban,       onToggleUrban,
  showCandidates,  onToggleCandidates,
  // Config
  mode,            onMode,
  kMax,            onKMax,
  targetCoverage,  onTargetCoverage,
  sf,              onSf,
  txPowerDbm,      onTxPowerDbm,
  txAntennaHeightM,onTxAntennaHeightM,
  costAware,       onCostAware,
  // Action
  running,         onRun,
  // Result
  result,
  // History
  history,         onSelectRun, onDeleteRun,
}) {
  const [open, setOpen] = useState({
    layers: true, config: true, result: true, history: false,
  });
  const toggle = (k) => setOpen(s => ({ ...s, [k]: !s[k] }));

  const candCount = (result?.selectionDetails ?? []).length;

  return (
    <div style={panelStyle}>
      <div style={titleStyle}>{S.optimizer.title}</div>
      <div style={hintStyle}>{S.optimizer.hint}</div>

      {/* ── Layers ────────────────────────────────────── */}
      <Section title={S.optimizer.sectionLayers}
               open={open.layers} onToggle={() => toggle("layers")}>
        <Check label={S.optimizer.showAoi}        value={showAoi}        onChange={onToggleAoi} />
        <Check label={S.optimizer.showUrban}      value={showUrban}      onChange={onToggleUrban} />
        <Check label={S.optimizer.showCandidates} value={showCandidates} onChange={onToggleCandidates} />
      </Section>

      {/* ── Config ────────────────────────────────────── */}
      <Section title={S.optimizer.sectionConfig}
               open={open.config} onToggle={() => toggle("config")}>
        {/* Mode */}
        <div style={rowStyle}>
          <button onClick={() => onMode("mclp")} style={tabBtn(mode === "mclp")}>
            {S.optimizer.modeMclp}
          </button>
          <button onClick={() => onMode("lscp")} style={tabBtn(mode === "lscp")}>
            {S.optimizer.modeLscp}
          </button>
        </div>

        {/* K_max (MCLP) */}
        {mode === "mclp" && (
          <Field label={`${S.optimizer.labelKMax}: ${kMax}`}>
            <input type="range" min={1} max={50} step={1}
                   value={kMax} onChange={e => onKMax(Number(e.target.value))}
                   style={rangeStyle} />
          </Field>
        )}

        {/* Target coverage (LSCP) */}
        {mode === "lscp" && (
          <Field label={`${S.optimizer.labelTargetCoverage}: ${(targetCoverage * 100).toFixed(0)}%`}>
            <input type="range" min={0.1} max={0.95} step={0.05}
                   value={targetCoverage}
                   onChange={e => onTargetCoverage(Number(e.target.value))}
                   style={rangeStyle} />
          </Field>
        )}

        <Field label={`${S.optimizer.labelSf}: SF${sf}`}>
          <input type="range" min={7} max={12} step={1}
                 value={sf} onChange={e => onSf(Number(e.target.value))}
                 style={rangeStyle} />
        </Field>

        <Field label={`${S.optimizer.labelTxPower}: ${txPowerDbm} dBm`}>
          <input type="range" min={0} max={27} step={1}
                 value={txPowerDbm} onChange={e => onTxPowerDbm(Number(e.target.value))}
                 style={rangeStyle} />
        </Field>

        <Field label={`${S.optimizer.labelTxHeight}: ${txAntennaHeightM} m`}>
          <input type="range" min={5} max={100} step={5}
                 value={txAntennaHeightM}
                 onChange={e => onTxAntennaHeightM(Number(e.target.value))}
                 style={rangeStyle} />
        </Field>

        <label style={{ ...checkStyle, marginTop: 4 }}>
          <input type="checkbox" checked={costAware}
                 onChange={e => onCostAware(e.target.checked)} />
          <span>{S.optimizer.labelCostAware}</span>
        </label>

        <button onClick={onRun} disabled={running} style={btnPrimary(running)}>
          {running ? S.optimizer.btnRunning : S.optimizer.btnRun}
        </button>
      </Section>

      {/* ── Result ────────────────────────────────────── */}
      {result && (
        <Section title={`${S.optimizer.sectionResult} (${candCount})`}
                 open={open.result} onToggle={() => toggle("result")}>
          <Metric label={S.optimizer.resultK}        value={result.nSelected} />
          <Metric label={S.optimizer.resultCoverage}
                  value={`${(result.coverageRatio * 100).toFixed(2)}%`} />
          <Metric label={S.optimizer.resultCost}
                  value={Number(result.totalCost).toFixed(2)} />
          <Metric label={S.optimizer.resultCompute}
                  value={`${result.computeMs} ms`} />
          <Metric label={S.optimizer.resultIterations} value={result.nIterations} />

          {(result.warnings ?? []).length > 0 && (
            <div style={warnBoxStyle} role="status">
              {result.warnings.map((w, i) => <div key={i}>⚠ {w}</div>)}
            </div>
          )}

          <div style={{ ...secLabelStyle, marginTop: 8 }}>
            {S.optimizer.resultTopSelections}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 3, maxHeight: 220, overflowY: "auto" }}>
            {(result.selectionDetails ?? []).slice(0, 10).map(s => (
              <div key={s.candidateId} style={selectionRowStyle}>
                <span style={{ color: s.rank <= 3 ? "#fca5a5" : "#c4b5fd", fontWeight: 700, minWidth: 22 }}>
                  #{s.rank}
                </span>
                <span style={{ color: s.source === "infra" ? "#fb923c" : "#9ca3af", fontSize: 10 }}>
                  {s.source}
                </span>
                <span style={{ color: "#d1d5db", fontSize: 11, marginLeft: "auto" }}>
                  +{s.marginalGain.toFixed(1)}
                </span>
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* ── History ───────────────────────────────────── */}
      <Section title={`${S.optimizer.sectionHistory} (${history.length})`}
               open={open.history} onToggle={() => toggle("history")}>
        {history.length === 0 ? (
          <div style={{ ...hintStyle, padding: "8px 0" }}>{S.optimizer.emptyHistory}</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 4, maxHeight: 280, overflowY: "auto" }}>
            {history.map(h => (
              <div key={h.id} style={historyRowStyle}>
                <button onClick={() => onSelectRun(h.id)} style={historyClickStyle}>
                  <div style={{ fontSize: 11, fontWeight: 600, color: "#e5e7eb" }}>
                    {h.mode === "mclp" ? `MCLP K=${h.kMax}` : `LSCP ${(Number(h.targetCoverage) * 100).toFixed(0)}%`}
                  </div>
                  <div style={{ fontSize: 10, color: "#9ca3af" }}>
                    {h.nSelected} GW · {(Number(h.coverageRatio) * 100).toFixed(1)}% · {h.computeMs}ms
                  </div>
                </button>
                <button onClick={() => onDeleteRun(h.id)} style={historyDelStyle}
                        title={S.optimizer.btnDelete}>×</button>
              </div>
            ))}
          </div>
        )}
      </Section>
    </div>
  );
}


// ── Atoms ────────────────────────────────────────────────────

function Section({ title, open, onToggle, children }) {
  return (
    <div style={sectionStyle}>
      <button onClick={onToggle} style={sectionHeaderStyle}>
        <span>{title}</span>
        <span style={{ color: "#9ca3af" }}>{open ? "▾" : "▸"}</span>
      </button>
      {open && <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>{children}</div>}
    </div>
  );
}

function Field({ label, children }) {
  return (
    <div style={{ marginTop: 4 }}>
      <div style={secLabelStyle}>{label}</div>
      {children}
    </div>
  );
}

function Metric({ label, value }) {
  return (
    <div style={metricRowStyle}>
      <span style={{ color: "#9ca3af", fontSize: 11 }}>{label}</span>
      <span style={{ color: "#f9fafb", fontSize: 12, fontWeight: 600 }}>{value}</span>
    </div>
  );
}

function Check({ label, value, onChange }) {
  return (
    <label style={checkStyle}>
      <input type="checkbox" checked={value} onChange={e => onChange(e.target.checked)} />
      <span>{label}</span>
    </label>
  );
}


// ── Styles ───────────────────────────────────────────────────

const panelStyle = {
  background: "rgba(20,20,30,0.88)", backdropFilter: "blur(8px)",
  borderRadius: 10, padding: "10px 12px",
  border: "1px solid rgba(255,255,255,0.1)",
  display: "flex", flexDirection: "column", gap: 6,
};
const titleStyle    = { fontSize: 13, fontWeight: 600, color: "#c4b5fd" };
const hintStyle     = { fontSize: 11, color: "#9ca3af" };
const secLabelStyle = { fontSize: 11, color: "#9ca3af", marginBottom: 3 };

const sectionStyle = {
  borderTop: "1px solid rgba(255,255,255,0.08)",
  paddingTop: 6, marginTop: 2,
};
const sectionHeaderStyle = {
  display: "flex", justifyContent: "space-between", alignItems: "center",
  width: "100%", padding: "4px 0", border: "none", background: "none",
  cursor: "pointer", fontSize: 11, fontWeight: 600, color: "#cbd5e1",
};

const rowStyle = { display: "flex", gap: 4, marginBottom: 4 };
const tabBtn = (active) => ({
  flex: 1, padding: "6px 8px", borderRadius: 6, border: "none",
  cursor: "pointer", fontSize: 11, fontWeight: 600,
  background: active ? "#7c3aed" : "rgba(255,255,255,0.07)",
  color: active ? "#fff" : "#cbd5e1",
});

const rangeStyle = { width: "100%", accentColor: "#534AB7", cursor: "pointer" };
const btnPrimary = (disabled) => ({
  marginTop: 6, padding: "8px 12px", borderRadius: 8, border: "none",
  cursor: disabled ? "not-allowed" : "pointer",
  fontSize: 13, fontWeight: 600,
  background: disabled ? "#3d3d5c" : "#7F77DD",
  color: "#fff", opacity: disabled ? 0.6 : 1,
});

const checkStyle = {
  display: "flex", alignItems: "center", gap: 6,
  fontSize: 11, color: "#d1d5db", cursor: "pointer",
};

const metricRowStyle = {
  display: "flex", justifyContent: "space-between", alignItems: "center",
  padding: "3px 0",
};

const warnBoxStyle = {
  fontSize: 11, color: "#fde68a",
  background: "rgba(245,158,11,0.15)",
  border: "1px solid rgba(245,158,11,0.4)",
  borderRadius: 6, padding: "5px 8px", marginTop: 6,
  display: "flex", flexDirection: "column", gap: 2,
};

const selectionRowStyle = {
  display: "flex", alignItems: "center", gap: 6,
  padding: "4px 6px", borderRadius: 4,
  background: "rgba(255,255,255,0.04)",
  fontSize: 11,
};

const historyRowStyle = {
  display: "flex", gap: 4,
  background: "rgba(255,255,255,0.04)",
  borderRadius: 6,
};
const historyClickStyle = {
  flex: 1, padding: "6px 8px", border: "none",
  background: "none", cursor: "pointer", textAlign: "left",
};
const historyDelStyle = {
  width: 24, padding: "0 4px", border: "none",
  background: "rgba(220,38,38,0.15)", color: "#fca5a5",
  cursor: "pointer", fontSize: 16, fontWeight: 700,
  borderRadius: "0 6px 6px 0",
};