import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import S from "../strings";
import NavBar from "../components/NavBar";


export default function SnapshotsPage() {
  const [campaigns,  setCampaigns]  = useState([]);
  const [campaignId, setCampaignId] = useState("");
  const [snapshots,  setSnapshots]  = useState([]);
  const [loading,    setLoading]    = useState(false);
  const [error,      setError]      = useState(null);
  const [toast,      setToast]      = useState(null);

  useEffect(() => {
    api.getCampaigns()
      .then(arr => {
        setCampaigns(arr ?? []);
        if (arr?.length) setCampaignId(arr[0].id);
      })
      .catch(e => setError(e.message));
  }, []);

  const load = useCallback(async () => {
    if (!campaignId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await api.listSnapshots(campaignId);
      setSnapshots(data ?? []);
    } catch (e) { setError(e.message); }
    finally     { setLoading(false); }
  }, [campaignId]);

  // Reload khi campaignId thay đổi (load là useCallback phụ thuộc campaignId)
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { load(); }, [load]);

  const handleRestore = async (id) => {
    if (!confirm(S.snapshots.confirmRestore)) return;
    try {
      const r = await api.restoreSnapshot(id);
      setToast(S.snapshots.restored(r.gridPoints));
      setTimeout(() => setToast(null), 4000);
      await load();
    } catch (e) { setError(e.message); }
  };

  const handleDelete = async (id) => {
    if (!confirm(S.snapshots.confirmDelete)) return;
    try {
      await api.deleteSnapshot(id);
      await load();
    } catch (e) { setError(e.message); }
  };

  return (
    <>
      <NavBar />
      <main style={page}>
        <header style={{ marginBottom: 18 }}>
          <h1 style={{ fontSize: 22, margin: 0 }}>{S.snapshots.title}</h1>
          <p style={{ fontSize: 13, color: "#94a3b8", margin: "4px 0 0" }}>
            {S.snapshots.subtitle}
          </p>
        </header>

        <section style={card}>
          <label htmlFor="cmp" style={lbl}>{S.snapshots.campaign}</label>
          <select id="cmp" value={campaignId}
                  onChange={e => setCampaignId(e.target.value)}
                  style={selectStyle}>
            {campaigns.map(c => (
              <option key={c.id} value={c.id} style={{ background: "#1a1a2e" }}>
                {c.name}
              </option>
            ))}
          </select>
          <button type="button" onClick={load} disabled={loading} style={btnGhost}>
            {S.snapshots.reload}
          </button>
        </section>

        {error && <div role="alert" style={errorBox}>{error}</div>}

        {snapshots.length === 0 && !loading && (
          <p style={{ color: "#94a3b8" }}>{S.snapshots.empty}</p>
        )}

        {snapshots.length > 0 && (
          <div style={{ overflow: "auto" }}>
            <table style={tbl}>
              <thead>
                <tr>
                  <th scope="col" style={th}>{S.snapshots.colCreatedAt}</th>
                  <th scope="col" style={th}>{S.snapshots.colAlgorithm}</th>
                  <th scope="col" style={th}>{S.snapshots.colLabel}</th>
                  <th scope="col" style={{ ...th, textAlign: "right" }}>{S.snapshots.colCount}</th>
                  <th scope="col" style={{ ...th, textAlign: "right" }}>{S.snapshots.colAvg}</th>
                  <th scope="col" style={th}>{S.snapshots.colActions}</th>
                </tr>
              </thead>
              <tbody>
                {snapshots.map(s => (
                  <tr key={s.id} style={tr}>
                    <td style={td}>
                      {new Date(s.createdAt).toLocaleString("vi-VN")}
                    </td>
                    <td style={td}>{s.algorithm?.toUpperCase()}</td>
                    <td style={{ ...td, color: "#94a3b8" }}>
                      {s.label || "—"}
                    </td>
                    <td style={{ ...td, textAlign: "right", fontFamily: "monospace" }}>
                      {s.gridCount?.toLocaleString()}
                    </td>
                    <td style={{ ...td, textAlign: "right", fontFamily: "monospace" }}>
                      {s.avgRssi ? `${Number(s.avgRssi).toFixed(1)} dBm` : "—"}
                    </td>
                    <td style={td}>
                      <button onClick={() => handleRestore(s.id)} style={miniBtn}>
                        {S.snapshots.btnRestore}
                      </button>
                      <button onClick={() => handleDelete(s.id)} style={miniDanger}>
                        {S.snapshots.btnDelete}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {toast && (
          <div role="status" style={toastStyle}>{toast}</div>
        )}
      </main>
    </>
  );
}


const page = {
  minHeight: "100vh", background: "#0f172a", color: "#f8fafc",
  padding: "70px 28px 24px", fontFamily: "system-ui, -apple-system, sans-serif",
  maxWidth: 1100, margin: "0 auto", boxSizing: "border-box",
};
const card = {
  background: "rgba(20,20,30,0.6)",
  border: "1px solid rgba(255,255,255,0.1)",
  borderRadius: 12, padding: 18, marginBottom: 14,
  display: "flex", gap: 10, alignItems: "flex-end",
};
const lbl = { fontSize: 12, color: "#94a3b8", fontWeight: 600,
              display: "block", marginBottom: 4 };
const selectStyle = {
  flex: 1, minWidth: 260,
  background: "rgba(255,255,255,0.08)",
  border: "1px solid rgba(255,255,255,0.15)",
  color: "#f9fafb", borderRadius: 8, padding: "8px 10px",
  fontSize: 14, cursor: "pointer", minHeight: 40,
};
const btnGhost = {
  padding: "8px 14px", borderRadius: 8, border: "none",
  background: "rgba(255,255,255,0.06)", color: "#cbd5e1",
  cursor: "pointer", fontSize: 13, minHeight: 40,
};
const tbl = {
  width: "100%", borderCollapse: "collapse", fontSize: 13,
  background: "rgba(20,20,30,0.6)",
  border: "1px solid rgba(255,255,255,0.1)",
  borderRadius: 10,
};
const th = {
  textAlign: "left", padding: "10px 14px",
  borderBottom: "1px solid rgba(255,255,255,0.15)",
  fontSize: 11, color: "#94a3b8", fontWeight: 600,
  textTransform: "uppercase", letterSpacing: "0.05em",
};
const td = { padding: "10px 14px",
              borderBottom: "1px solid rgba(255,255,255,0.05)" };
const tr = { transition: "background 0.1s" };

const miniBtn = {
  padding: "5px 10px", borderRadius: 5, border: "none",
  background: "rgba(124,58,237,0.4)", color: "#fff",
  cursor: "pointer", fontSize: 11, marginRight: 4, fontWeight: 600,
};
const miniDanger = {
  padding: "5px 10px", borderRadius: 5, border: "none",
  background: "rgba(239,68,68,0.4)", color: "#fff",
  cursor: "pointer", fontSize: 11, fontWeight: 600,
};
const errorBox = {
  marginBottom: 12, padding: "8px 12px",
  background: "#7f1d1d", color: "#fee2e2",
  borderRadius: 8, fontSize: 13,
};
const toastStyle = {
  position: "fixed", bottom: 24, left: "50%",
  transform: "translateX(-50%)",
  background: "rgba(20,20,30,0.95)", color: "#f9fafb",
  padding: "10px 20px", borderRadius: 10, fontSize: 13,
  border: "1px solid rgba(255,255,255,0.15)", zIndex: 2000,
};