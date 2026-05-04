import { useEffect, useState } from "react";
import { api } from "../api";
import S from "../strings";
import NavBar from "../components/NavBar";


export default function ComparePage() {
  const [campaigns, setCampaigns] = useState([]);
  const [aId, setAId]             = useState("");
  const [bId, setBId]             = useState("");
  const [running, setRunning]     = useState(false);
  const [result,  setResult]      = useState(null);
  const [error,   setError]       = useState(null);

  useEffect(() => {
    api.getCampaigns()
      .then(arr => {
        setCampaigns(arr ?? []);
        if (arr?.length >= 2) {
          setAId(arr[0].id);
          setBId(arr[1].id);
        } else if (arr?.length === 1) {
          setAId(arr[0].id);
          setBId(arr[0].id);
        }
      })
      .catch(e => setError(e.message));
  }, []);

  const handleRun = async () => {
    if (!aId || !bId) return;
    if (aId === bId) {
      setError(S.compare.sameError);
      return;
    }
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const data = await api.compareScenarios(aId, bId);
      setResult(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setRunning(false);
    }
  };

  return (
    <>
      <NavBar />
      <main style={page}>
        <header style={{ marginBottom: 18 }}>
          <h1 style={{ fontSize: 22, margin: 0 }}>{S.compare.title}</h1>
          <p style={{ fontSize: 13, color: "#94a3b8", margin: "4px 0 0" }}>
            {S.compare.subtitle}
          </p>
        </header>

        <section style={card}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
            <CampaignSelect
              id="cmpA" label={S.compare.campaignA}
              value={aId} onChange={setAId} options={campaigns}
            />
            <CampaignSelect
              id="cmpB" label={S.compare.campaignB}
              value={bId} onChange={setBId} options={campaigns}
            />
          </div>

          <button
            type="button" onClick={handleRun}
            disabled={!aId || !bId || running}
            style={btnPrimary(!aId || !bId || running)}
          >
            {running ? S.compare.btnRunning : S.compare.btnRun}
          </button>

          {error && <div role="alert" style={errorBox}>{error}</div>}
        </section>

        {result && (
          <>
            <section style={card}>
              <h2 style={h2}>{S.compare.summaryTitle}</h2>
              <Row label={S.compare.matchedCells} value={result.summary.matchedCells} />
              <Row label={S.compare.onlyInA}      value={result.summary.onlyInA} />
              <Row label={S.compare.onlyInB}      value={result.summary.onlyInB} />
              <Row label={S.compare.avgDelta}     value={result.summary.avgDeltaDb}    mono accent={accent(result.summary.avgDeltaDb)} />
              <Row label={S.compare.maxGain}      value={`+${result.summary.maxGainDb}`} mono accent="#10b981" />
              <Row label={S.compare.maxLoss}      value={result.summary.maxLossDb} mono accent="#ef4444" />
              <Row label={S.compare.strongChange} value={pct(result.summary.strongPctChange)} mono accent={accent(result.summary.strongPctChange)} />
              <Row label={S.compare.mediumChange} value={pct(result.summary.mediumPctChange)} mono accent={accent(result.summary.mediumPctChange)} />
            </section>

            <section style={card}>
              <h2 style={h2}>{S.compare.distTitle}</h2>
              <DistTable a={result.distributionA} b={result.distributionB} />
            </section>
          </>
        )}
      </main>
    </>
  );
}


function CampaignSelect({ id, label, value, onChange, options }) {
  return (
    <div>
      <label htmlFor={id} style={lbl}>{label}</label>
      <select id={id} value={value} onChange={e => onChange(e.target.value)} style={selectStyle}>
        <option value="" style={{ background: "#1a1a2e" }}>—</option>
        {options.map(c => (
          <option key={c.id} value={c.id} style={{ background: "#1a1a2e" }}>
            {c.name}
          </option>
        ))}
      </select>
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
      }}>
        {value ?? "—"}
      </span>
    </div>
  );
}


function DistTable({ a, b }) {
  const rows = [
    { key: "strongPct",   label: S.stats.coverageStrong },
    { key: "mediumPct",   label: S.stats.coverageMedium },
    { key: "weakPct",     label: S.stats.coverageWeak },
    { key: "veryWeakPct", label: S.stats.coverageVeryWeak },
  ];
  return (
    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
      <thead>
        <tr>
          <th scope="col" style={th}>{S.compare.colLevel}</th>
          <th scope="col" style={{ ...th, textAlign: "right" }}>{S.compare.colA}</th>
          <th scope="col" style={{ ...th, textAlign: "right" }}>{S.compare.colB}</th>
          <th scope="col" style={{ ...th, textAlign: "right" }}>{S.compare.colDiff}</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(r => {
          const av = a[r.key] ?? 0;
          const bv = b[r.key] ?? 0;
          const dv = +(bv - av).toFixed(2);
          return (
            <tr key={r.key}>
              <td style={td}>{r.label}</td>
              <td style={{ ...td, textAlign: "right", fontFamily: "monospace" }}>{av}%</td>
              <td style={{ ...td, textAlign: "right", fontFamily: "monospace" }}>{bv}%</td>
              <td style={{ ...td, textAlign: "right", fontFamily: "monospace",
                            color: accent(dv), fontWeight: 600 }}>
                {pct(dv)}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}


function pct(v) {
  if (v == null) return "—";
  if (v > 0)     return `+${v}%`;
  return `${v}%`;
}

function accent(v) {
  if (v == null || v === 0) return null;
  return v > 0 ? "#10b981" : "#ef4444";
}


const page = {
  minHeight: "100vh", background: "#0f172a", color: "#f8fafc",
  padding: "70px 28px 24px", fontFamily: "system-ui, -apple-system, sans-serif",
  maxWidth: 760, margin: "0 auto", boxSizing: "border-box",
};
const card = {
  background: "rgba(20,20,30,0.6)",
  border: "1px solid rgba(255,255,255,0.1)",
  borderRadius: 12, padding: 18, marginBottom: 14,
};
const h2 = { fontSize: 14, color: "#c4b5fd", margin: "0 0 10px",
             textTransform: "uppercase", letterSpacing: "0.05em" };
const lbl = { fontSize: 12, color: "#94a3b8", fontWeight: 600,
              display: "block", marginBottom: 4 };
const selectStyle = {
  width: "100%",
  background: "rgba(255,255,255,0.08)",
  border: "1px solid rgba(255,255,255,0.15)",
  color: "#f9fafb", borderRadius: 8, padding: "8px 10px",
  fontSize: 14, cursor: "pointer", minHeight: 40,
};
const btnPrimary = (disabled) => ({
  marginTop: 14,
  padding: "12px 18px", borderRadius: 10, border: "none",
  cursor: disabled ? "not-allowed" : "pointer",
  fontSize: 14, fontWeight: 600,
  background: disabled ? "#3d3d5c" : "#7c3aed",
  color: "#fff", opacity: disabled ? 0.6 : 1,
  minHeight: 44,
});
const errorBox = {
  marginTop: 10, padding: "8px 12px",
  background: "#7f1d1d", color: "#fee2e2",
  borderRadius: 8, fontSize: 13,
};
const th = {
  textAlign: "left", padding: "8px 10px",
  borderBottom: "1px solid rgba(255,255,255,0.15)",
  fontSize: 11, color: "#94a3b8", fontWeight: 600,
  textTransform: "uppercase", letterSpacing: "0.05em",
};
const td = { padding: "8px 10px",
             borderBottom: "1px solid rgba(255,255,255,0.05)" };