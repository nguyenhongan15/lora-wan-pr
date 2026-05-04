import { useMemo, useState } from "react";
import { api } from "../api";
import S from "../strings";
import NavBar from "../components/NavBar";


const ENV_KEYS = ["urban", "suburban", "rural", "forest", "coastal", "mountain"];
const SF_OPTIONS = [7, 8, 9, 10, 11, 12];


export default function SandboxPage() {
  const [form, setForm] = useState({
    txLat: 16.054, txLng: 108.202,
    rxLat: 16.060, rxLng: 108.210,
    txPowerDbm: 14, antennaGainDbi: 8,
    environment: "urban",
    pathLossExponentOverride: "",
    spreadingFactor: 9,
    bearingDeg: 90, maxDistanceM: 5000, nSamples: 50,
  });
  const [running, setRunning]  = useState(false);
  const [result,  setResult]   = useState(null);
  const [curve,   setCurve]    = useState(null);
  const [error,   setError]    = useState(null);

  const setField = (k) => (v) => setForm(f => ({ ...f, [k]: v }));

  const expOverride = form.pathLossExponentOverride === ""
                    ? null
                    : Number(form.pathLossExponentOverride);

  const runPoint = async () => {
    setRunning(true);
    setError(null);
    try {
      const data = await api.sandboxPredictPoint({
        txLat: +form.txLat, txLng: +form.txLng,
        rxLat: +form.rxLat, rxLng: +form.rxLng,
        txPowerDbm:     +form.txPowerDbm,
        antennaGainDbi: +form.antennaGainDbi,
        environment:    form.environment,
        pathLossExponentOverride: expOverride,
        spreadingFactor: +form.spreadingFactor,
      });
      setResult(data);
    } catch (e) { setError(e.message); }
    finally     { setRunning(false); }
  };

  const runRadial = async () => {
    setRunning(true);
    setError(null);
    try {
      const data = await api.sandboxRadialProfile({
        txLat: +form.txLat, txLng: +form.txLng,
        bearingDeg:    +form.bearingDeg,
        maxDistanceM:  +form.maxDistanceM,
        nSamples:      +form.nSamples,
        txPowerDbm:    +form.txPowerDbm,
        antennaGainDbi:+form.antennaGainDbi,
        environment:   form.environment,
        pathLossExponentOverride: expOverride,
      });
      setCurve(data.points);
    } catch (e) { setError(e.message); }
    finally     { setRunning(false); }
  };

  return (
    <>
      <NavBar />
      <main style={page}>
        <header style={{ marginBottom: 18 }}>
          <h1 style={{ fontSize: 22, margin: 0 }}>{S.sandbox.title}</h1>
          <p style={{ fontSize: 13, color: "#94a3b8", margin: "4px 0 0" }}>
            {S.sandbox.subtitle}
          </p>
        </header>

        <section style={card}>
          <h2 style={h2}>{S.sandbox.sectionTx}</h2>
          <div style={grid2}>
            <Field id="txLat" label={S.sandbox.labelLat}
                   value={form.txLat} onChange={setField("txLat")} type="number" step="0.0001" />
            <Field id="txLng" label={S.sandbox.labelLng}
                   value={form.txLng} onChange={setField("txLng")} type="number" step="0.0001" />
          </div>

          <h2 style={h2}>{S.sandbox.sectionRx}</h2>
          <div style={grid2}>
            <Field id="rxLat" label={S.sandbox.labelLat}
                   value={form.rxLat} onChange={setField("rxLat")} type="number" step="0.0001" />
            <Field id="rxLng" label={S.sandbox.labelLng}
                   value={form.rxLng} onChange={setField("rxLng")} type="number" step="0.0001" />
          </div>

          <h2 style={h2}>{S.sandbox.sectionPhysical}</h2>
          <div style={grid2}>
            <Field id="txp"  label={S.sandbox.labelTxPower}
                   value={form.txPowerDbm} onChange={setField("txPowerDbm")} type="number" min="0" max="30" />
            <Field id="ant"  label={S.sandbox.labelAntennaGain}
                   value={form.antennaGainDbi} onChange={setField("antennaGainDbi")} type="number" min="0" max="20" />

            <div>
              <label htmlFor="env" style={lbl}>{S.sandbox.labelEnv}</label>
              <select id="env" value={form.environment}
                      onChange={e => setField("environment")(e.target.value)}
                      style={selectStyle}>
                {ENV_KEYS.map(k => (
                  <option key={k} value={k} style={{ background: "#1a1a2e" }}>
                    {S.simulator.envOptions[k]}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label htmlFor="sf" style={lbl}>{S.sandbox.labelSf}</label>
              <select id="sf" value={form.spreadingFactor}
                      onChange={e => setField("spreadingFactor")(e.target.value)}
                      style={selectStyle}>
                {SF_OPTIONS.map(s => (
                  <option key={s} value={s} style={{ background: "#1a1a2e" }}>SF{s}</option>
                ))}
              </select>
            </div>

            <Field id="exp" label={S.sandbox.labelExpOverride}
                   value={form.pathLossExponentOverride}
                   onChange={setField("pathLossExponentOverride")}
                   type="number" step="0.1" min="1.5" max="6"
                   placeholder="—" />
          </div>

          <div style={{ display: "flex", gap: 10, marginTop: 14 }}>
            <button type="button" onClick={runPoint} disabled={running}
                    style={btnPrimary(running)}>
              {running ? S.sandbox.btnRunning : S.sandbox.btnRunPoint}
            </button>
            <button type="button" onClick={runRadial} disabled={running}
                    style={btnSecondary(running)}>
              {running ? S.sandbox.btnRunning : S.sandbox.btnRunRadial}
            </button>
          </div>

          {error && <div role="alert" style={errorBox}>{error}</div>}
        </section>

        {result && (
          <section style={card}>
            <h2 style={h2}>{S.sandbox.resultTitle}</h2>
            <Row label={S.sandbox.labelDistance}    value={`${result.distanceM} m`} mono />
            <Row label={S.sandbox.labelPathLoss}    value={`${result.pathLossDb} dB`} mono />
            <Row label={S.sandbox.labelExp}         value={result.pathLossExponent} mono />
            <Row label={S.sandbox.labelPredicted}   value={`${result.predictedRssiDbm} dBm`} mono accent="#a78bfa" />
            <Row label={S.sandbox.labelSensitivity} value={`${result.sensitivityDbm} dBm`} mono />
            <Row label={S.sandbox.labelLinkMargin}  value={`${result.linkMarginDb} dB`} mono
                 accent={result.linkMarginDb > 0 ? "#10b981" : "#ef4444"} />
            <Row label={S.sandbox.labelDecodeable}
                 value={result.decodeable ? S.sandbox.labelDecodeYes : S.sandbox.labelDecodeNo}
                 accent={result.decodeable ? "#10b981" : "#ef4444"} />
            <Row label={S.sandbox.labelLevel}       value={result.verdict} accent={LEVEL_COLOR[result.level]} />
          </section>
        )}

        <section style={card}>
          <h2 style={h2}>{S.sandbox.curveTitle}</h2>
          {curve
            ? <Curve points={curve} />
            : <p style={{ fontSize: 13, color: "#94a3b8", margin: 0 }}>
                {S.sandbox.noCurve}
              </p>}
        </section>
      </main>
    </>
  );
}


const LEVEL_COLOR = {
  strong: "#10b981", medium: "#f59e0b",
  weak:   "#ea580c", none:   "#ef4444",
};


function Field({ id, label, value, onChange, ...rest }) {
  return (
    <div>
      <label htmlFor={id} style={lbl}>{label}</label>
      <input
        id={id} value={value}
        onChange={e => onChange(e.target.value)}
        style={inputStyle} {...rest}
      />
    </div>
  );
}


function Row({ label, value, mono, accent }) {
  return (
    <div style={{
      display: "flex", justifyContent: "space-between",
      padding: "6px 0", borderBottom: "1px solid rgba(255,255,255,0.05)",
      fontSize: 14,
    }}>
      <span style={{ color: "#94a3b8" }}>{label}</span>
      <span style={{
        fontWeight: 600,
        color: accent ?? "#f1f5f9",
        fontFamily: mono ? "monospace" : "inherit",
      }}>{value ?? "—"}</span>
    </div>
  );
}


function Curve({ points }) {
  const W = 600, H = 240, pad = 40;
  const { path, xTicks, yTicks } = useMemo(() => {
    const xs = points.map(p => p.distanceM);
    const ys = points.map(p => p.rssiDbm);
    const xMin = Math.min(...xs), xMax = Math.max(...xs);
    const yMin = Math.min(...ys), yMax = Math.max(...ys);

    const sx = (x) => pad + (x - xMin) / (xMax - xMin) * (W - 2*pad);
    const sy = (y) => H - pad - (y - yMin) / (yMax - yMin) * (H - 2*pad);

    const path = points
      .map((p, i) => `${i === 0 ? "M" : "L"} ${sx(p.distanceM).toFixed(1)} ${sy(p.rssiDbm).toFixed(1)}`)
      .join(" ");

    const xTicks = [0, 0.25, 0.5, 0.75, 1].map(t => {
      const v = xMin + t * (xMax - xMin);
      return { x: sx(v), label: `${Math.round(v)}` };
    });
    const yTicks = [0, 0.5, 1].map(t => {
      const v = yMin + t * (yMax - yMin);
      return { y: sy(v), label: `${v.toFixed(0)}` };
    });

    return { path, xTicks, yTicks };
  }, [points]);

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      style={{ width: "100%", height: "auto", display: "block" }}
      role="img"
      aria-label={`${S.sandbox.curveYLabel} theo ${S.sandbox.curveXLabel}, ${points.length} điểm dữ liệu`}
    >
      <line x1={pad} y1={H-pad} x2={W-pad} y2={H-pad} stroke="#475569" />
      <line x1={pad} y1={pad}   x2={pad}   y2={H-pad} stroke="#475569" />

      {yTicks.map((t, i) => (
        <g key={i}>
          <line x1={pad-4} y1={t.y} x2={pad} y2={t.y} stroke="#475569" />
          <text x={pad-8} y={t.y+4} textAnchor="end" fontSize="10" fill="#94a3b8">
            {t.label}
          </text>
        </g>
      ))}

      {xTicks.map((t, i) => (
        <g key={i}>
          <line x1={t.x} y1={H-pad} x2={t.x} y2={H-pad+4} stroke="#475569" />
          <text x={t.x} y={H-pad+18} textAnchor="middle" fontSize="10" fill="#94a3b8">
            {t.label}
          </text>
        </g>
      ))}

      <path d={path} fill="none" stroke="#a78bfa" strokeWidth="2" />

      <text x={W/2} y={H-6} textAnchor="middle" fontSize="11" fill="#94a3b8">
        {S.sandbox.curveXLabel}
      </text>
      <text x={12} y={H/2} textAnchor="middle" fontSize="11" fill="#94a3b8"
            transform={`rotate(-90 12 ${H/2})`}>
        {S.sandbox.curveYLabel}
      </text>
    </svg>
  );
}


const page = {
  minHeight: "100vh", background: "#0f172a", color: "#f8fafc",
  padding: "70px 28px 24px", fontFamily: "system-ui, -apple-system, sans-serif",
  maxWidth: 800, margin: "0 auto", boxSizing: "border-box",
};
const card = {
  background: "rgba(20,20,30,0.6)",
  border: "1px solid rgba(255,255,255,0.1)",
  borderRadius: 12, padding: 18, marginBottom: 14,
};
const h2 = { fontSize: 12, color: "#c4b5fd", margin: "10px 0 8px",
             textTransform: "uppercase", letterSpacing: "0.05em" };
const lbl = { fontSize: 12, color: "#94a3b8", fontWeight: 600,
              display: "block", marginBottom: 4 };
const grid2 = { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 };
const inputStyle = {
  width: "100%", boxSizing: "border-box",
  background: "rgba(255,255,255,0.08)",
  border: "1px solid rgba(255,255,255,0.15)",
  color: "#f9fafb", borderRadius: 8, padding: "8px 10px",
  fontSize: 13, minHeight: 38,
};
const selectStyle = { ...inputStyle, cursor: "pointer" };

const btnPrimary = (disabled) => ({
  padding: "10px 16px", borderRadius: 8, border: "none",
  cursor: disabled ? "not-allowed" : "pointer",
  fontSize: 14, fontWeight: 600,
  background: disabled ? "#3d3d5c" : "#7c3aed",
  color: "#fff", opacity: disabled ? 0.6 : 1,
  minHeight: 44,
});
const btnSecondary = (disabled) => ({
  padding: "10px 16px", borderRadius: 8, border: "none",
  cursor: disabled ? "not-allowed" : "pointer",
  fontSize: 14, fontWeight: 600,
  background: "rgba(255,255,255,0.08)",
  color: "#f1f5f9", opacity: disabled ? 0.6 : 1,
  minHeight: 44,
});
const errorBox = {
  marginTop: 10, padding: "8px 12px",
  background: "#7f1d1d", color: "#fee2e2",
  borderRadius: 8, fontSize: 13,
};