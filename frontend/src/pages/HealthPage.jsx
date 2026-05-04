import { useEffect, useState, useCallback } from "react";
import { api } from "../api";
import S from "../strings";
import NavBar from "../components/NavBar";

const STATUS_COLOR = {
  online:   "#10b981",
  degraded: "#f59e0b",
  offline:  "#ef4444",
};

const STATUS_LABEL = {
  online:   S.health.statusOnline,
  degraded: S.health.statusDegraded,
  offline:  S.health.statusOffline,
};


function StatusDot({ status }) {
  const color = STATUS_COLOR[status] ?? "#64748b";
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      <span aria-hidden="true" style={{
        display: "inline-block", width: 9, height: 9, borderRadius: "50%",
        background: color, boxShadow: `0 0 0 2px ${color}33`,
      }} />
      <span style={{ color: STATUS_COLOR[status], fontWeight: 600 }}>
        {STATUS_LABEL[status] ?? status}
      </span>
    </span>
  );
}


function SummaryCard({ label, value, color }) {
  return (
    <div style={{
      background: "rgba(255,255,255,0.05)",
      border: `1px solid ${color}55`,
      borderRadius: 10, padding: "12px 16px",
      minWidth: 110, textAlign: "left",
    }}>
      <div style={{ fontSize: 11, color: "#9ca3af", textTransform: "uppercase",
                    letterSpacing: "0.05em" }}>{label}</div>
      <div style={{ fontSize: 24, fontWeight: 700, color }}>{value}</div>
    </div>
  );
}


export default function HealthPage() {
  const [items,   setItems]   = useState([]);
  const [summary, setSummary] = useState({ online: 0, degraded: 0, offline: 0, total: 0 });
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const json = await api.getGatewayHealth();
      setItems(json.data ?? []);
      setSummary(json.meta?.summary ?? { online: 0, degraded: 0, offline: 0, total: 0 });
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <>
      <NavBar />
      <main style={page}>
        <header style={{ marginBottom: 16 }}>
          <h1 style={{ fontSize: 22, margin: 0, color: "#f8fafc" }}>
            {S.health.title}
          </h1>
          <p style={{ fontSize: 13, color: "#94a3b8", margin: "4px 0 0" }}>
            {S.health.subtitle}
          </p>
        </header>

        <section aria-label="Summary" style={{
          display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 16,
        }}>
          <SummaryCard label={S.health.summaryOnline}   value={summary.online}   color={STATUS_COLOR.online} />
          <SummaryCard label={S.health.summaryDegraded} value={summary.degraded} color={STATUS_COLOR.degraded} />
          <SummaryCard label={S.health.summaryOffline}  value={summary.offline}  color={STATUS_COLOR.offline} />
          <SummaryCard label={S.health.summaryTotal}    value={summary.total}    color="#94a3b8" />

          <button onClick={load} disabled={loading} style={reloadBtn(loading)}>
            {S.health.reload}
          </button>
        </section>

        {error && <ErrorBox message={error} />}

        {!error && items.length === 0 && !loading && (
          <p style={{ color: "#9ca3af" }}>{S.health.empty}</p>
        )}

        {items.length > 0 && (
          <div style={{ overflow: "auto", border: "1px solid rgba(255,255,255,0.1)",
                         borderRadius: 10 }}>
            <table style={tbl}>
              <caption style={visuallyHidden}>{S.health.title}</caption>
              <thead>
                <tr>
                  <th scope="col" style={th}>{S.health.colName}</th>
                  <th scope="col" style={th}>{S.health.colEui}</th>
                  <th scope="col" style={th}>{S.health.colStatus}</th>
                  <th scope="col" style={th}>{S.health.colLastSeen}</th>
                  <th scope="col" style={th}>{S.health.colUplinks}</th>
                  <th scope="col" style={th}>{S.health.colUptime}</th>
                </tr>
              </thead>
              <tbody>
                {items.map(g => (
                  <tr key={g.id} style={tr}>
                    <td style={td}>{g.name || "—"}</td>
                    <td style={{ ...td, fontFamily: "monospace", fontSize: 11 }}>
                      {g.gatewayEui}
                    </td>
                    <td style={td}><StatusDot status={g.status} /></td>
                    <td style={td}>
                      {g.lastSeenAt
                        ? S.health.hoursAgo(g.hoursSinceLastSeen)
                        : <span style={{ color: "#64748b" }}>{S.health.neverSeen}</span>}
                    </td>
                    <td style={td}>{g.uplinkCount24h}</td>
                    <td style={td}>{g.uptimePercent24h}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </main>
    </>
  );
}


function ErrorBox({ message }) {
  return (
    <div role="alert" style={{
      background: "#7f1d1d", color: "#fee2e2",
      padding: "10px 14px", borderRadius: 8,
      fontSize: 13, marginBottom: 12,
    }}>{message}</div>
  );
}


const page = {
  minHeight: "100vh", background: "#0f172a", color: "#f8fafc",
  padding: "70px 28px 24px", fontFamily: "system-ui, -apple-system, sans-serif",
  boxSizing: "border-box",
};
const tbl = {
  width: "100%", borderCollapse: "collapse", fontSize: 13,
  background: "rgba(20,20,30,0.6)",
};
const th = {
  textAlign: "left", padding: "10px 14px",
  borderBottom: "1px solid rgba(255,255,255,0.15)",
  fontSize: 11, color: "#94a3b8", fontWeight: 600,
  textTransform: "uppercase", letterSpacing: "0.05em",
};
const td = {
  padding: "10px 14px",
  borderBottom: "1px solid rgba(255,255,255,0.05)",
};
const tr = { transition: "background 0.1s" };
const reloadBtn = (loading) => ({
  marginLeft: "auto",
  padding: "8px 16px", borderRadius: 8, border: "none",
  background: "#7c3aed", color: "#fff",
  cursor: loading ? "wait" : "pointer", opacity: loading ? 0.6 : 1,
  fontSize: 13, fontWeight: 600,
});
const visuallyHidden = {
  position: "absolute", width: 1, height: 1, padding: 0, margin: -1,
  overflow: "hidden", clip: "rect(0,0,0,0)", border: 0,
};