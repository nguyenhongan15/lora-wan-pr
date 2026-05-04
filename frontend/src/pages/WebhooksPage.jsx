import { Fragment, useCallback, useEffect, useState } from "react";
import { api } from "../api";
import S from "../strings";
import NavBar from "../components/NavBar";


export default function WebhooksPage() {
  const [list,    setList]     = useState([]);
  const [loading, setLoading]  = useState(false);
  const [error,   setError]    = useState(null);
  const [toast,   setToast]    = useState(null);

  const [projectId,  setProjectId]  = useState("");
  const [name,       setName]       = useState("");
  const [targetUrl,  setTargetUrl]  = useState("");
  const [eventTypes, setEventTypes] = useState("");

  const [newSub, setNewSub] = useState(null);

  const [openSubId,  setOpenSubId]  = useState(null);
  const [deliveries, setDeliveries] = useState([]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.listWebhookSubs();
      setList(data ?? []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleCreate = async () => {
    if (!projectId || !name || !targetUrl) return;
    try {
      const events = eventTypes.split(",").map(s => s.trim()).filter(Boolean);
      const data = await api.createWebhookSub(projectId, name, targetUrl, events);
      setNewSub(data);
      setName("");
      setTargetUrl("");
      setEventTypes("");
      await load();
    } catch (e) {
      setError(e.message);
    }
  };

  const handleTest = async (id) => {
    try {
      const r = await api.testFireWebhook(id);
      setToast(S.webhooks.testFired(r.delivered, r.failed));
      setTimeout(() => setToast(null), 3500);
    } catch (e) { setError(e.message); }
  };

  const handleDelete = async (id) => {
    try {
      await api.deleteWebhookSub(id);
      await load();
    } catch (e) { setError(e.message); }
  };

  const handleOpenDeliveries = async (id) => {
    setOpenSubId(id === openSubId ? null : id);
    if (id === openSubId) return;
    try {
      const data = await api.listWebhookDeliveries(id);
      setDeliveries(data ?? []);
    } catch (e) { setError(e.message); }
  };

  const copySecret = (s) => {
    navigator.clipboard?.writeText(s)
      .then(() => setToast(S.webhooks.copied))
      .catch(() => {});
    setTimeout(() => setToast(null), 2000);
  };

  return (
    <>
      <NavBar />
      <main style={page}>
        <header style={{ marginBottom: 18 }}>
          <h1 style={{ fontSize: 22, margin: 0 }}>{S.webhooks.title}</h1>
          <p style={{ fontSize: 13, color: "#94a3b8", margin: "4px 0 0" }}>
            {S.webhooks.subtitle}
          </p>
        </header>

        <section style={card}>
          <h2 style={h2}>{S.webhooks.sectionCreate}</h2>
          <Field id="pid"  label={S.webhooks.labelProjectId} value={projectId}
                 onChange={setProjectId} placeholder="00000000-0000-0000-0000-000000000001" />
          <Field id="name" label={S.webhooks.labelName} value={name} onChange={setName} />
          <Field id="url"  label={S.webhooks.labelTargetUrl} value={targetUrl}
                 onChange={setTargetUrl} placeholder="https://example.com/hook" />
          <Field id="ev"   label={S.webhooks.labelEvents} value={eventTypes}
                 onChange={setEventTypes} placeholder="gateway.offline, webhook.test" />

          <button type="button" onClick={handleCreate}
                  disabled={!projectId || !name || !targetUrl}
                  style={btnPrimary(!projectId || !name || !targetUrl)}>
            {S.webhooks.btnCreate}
          </button>
        </section>

        {newSub && (
          <section style={{ ...card, background: "#1e3a8a", borderColor: "#3b82f6" }}>
            <h2 style={{ ...h2, color: "#bfdbfe" }}>{S.webhooks.newSecret}</h2>
            <code style={secretBox}
                  role="button" tabIndex={0}
                  title={S.webhooks.copyHint}
                  onClick={() => copySecret(newSub.secret)}>
              {newSub.secret}
            </code>
            <p style={{ fontSize: 12, color: "#bfdbfe", marginTop: 8 }}>
              ⚠️ {newSub.warning}
            </p>
            <button type="button" onClick={() => setNewSub(null)} style={btnSecondary}>
              ✕ Đóng
            </button>
          </section>
        )}

        <section style={card}>
          <div style={{ display: "flex", justifyContent: "space-between",
                         alignItems: "center", marginBottom: 8 }}>
            <h2 style={h2}>{S.webhooks.sectionList}</h2>
            <button type="button" onClick={load} disabled={loading} style={btnGhost}>
              {S.webhooks.btnReload}
            </button>
          </div>

          {error && <div role="alert" style={errorBox}>{error}</div>}

          {list.length === 0 && !loading && (
            <p style={{ color: "#94a3b8", fontSize: 13 }}>{S.webhooks.empty}</p>
          )}

          {list.length > 0 && (
            <div style={{ overflow: "auto" }}>
              <table style={tbl}>
                <thead>
                  <tr>
                    <th scope="col" style={th}>{S.webhooks.colName}</th>
                    <th scope="col" style={th}>{S.webhooks.colUrl}</th>
                    <th scope="col" style={th}>{S.webhooks.colEvents}</th>
                    <th scope="col" style={th}>{S.webhooks.colActions}</th>
                  </tr>
                </thead>
                <tbody>
                  {list.map(s => (
                    // Fragment để tránh React key warning khi render 2 row liền kề
                    <Fragment key={s.id}>
                      <tr style={tr}>
                        <td style={td}>{s.name}</td>
                        <td style={{ ...td, fontFamily: "monospace", fontSize: 11,
                                      maxWidth: 240, overflow: "hidden",
                                      textOverflow: "ellipsis" }}>
                          {s.targetUrl}
                        </td>
                        <td style={{ ...td, fontSize: 12 }}>
                          {!s.eventTypes?.length
                            ? <span style={{ color: "#94a3b8" }}>{S.webhooks.eventsAll}</span>
                            : s.eventTypes.join(", ")}
                        </td>
                        <td style={td}>
                          <button onClick={() => handleTest(s.id)}            style={miniBtn}>{S.webhooks.btnTest}</button>
                          <button onClick={() => handleOpenDeliveries(s.id)}  style={miniBtn}>{S.webhooks.btnDeliveries}</button>
                          <button onClick={() => handleDelete(s.id)}          style={miniDanger}>{S.webhooks.btnDelete}</button>
                        </td>
                      </tr>
                      {openSubId === s.id && (
                        <tr>
                          <td colSpan="4" style={{ padding: 0 }}>
                            <DeliveriesTable items={deliveries} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        {toast && (
          <div role="status" style={toastStyle}>{toast}</div>
        )}
      </main>
    </>
  );
}


function Field({ id, label, value, onChange, placeholder }) {
  return (
    <div style={{ marginBottom: 8 }}>
      <label htmlFor={id} style={lbl}>{label}</label>
      <input id={id} value={value} placeholder={placeholder}
             onChange={e => onChange(e.target.value)}
             style={inputStyle} />
    </div>
  );
}


function DeliveriesTable({ items }) {
  if (!items.length) {
    return (
      <div style={{ padding: 12, fontSize: 12, color: "#94a3b8" }}>
        {S.webhooks.empty}
      </div>
    );
  }
  return (
    <div style={{ background: "rgba(0,0,0,0.25)", padding: 8 }}>
      <div style={{ fontSize: 11, color: "#94a3b8", marginBottom: 6,
                     textTransform: "uppercase", letterSpacing: "0.05em" }}>
        {S.webhooks.deliveriesTitle}
      </div>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
        <thead>
          <tr>
            <th style={th2}>{S.webhooks.colEvent}</th>
            <th style={th2}>{S.webhooks.colStatus}</th>
            <th style={th2}>{S.webhooks.colDuration}</th>
            <th style={th2}>{S.webhooks.colTime}</th>
          </tr>
        </thead>
        <tbody>
          {items.map(d => {
            const ok = d.statusCode && d.statusCode < 300;
            return (
              <tr key={d.id}>
                <td style={td2}>{d.eventType}</td>
                <td style={{ ...td2, color: ok ? "#10b981" : "#ef4444",
                              fontFamily: "monospace" }}>
                  {d.statusCode ?? "ERR"}
                </td>
                <td style={{ ...td2, fontFamily: "monospace" }}>{d.durationMs}ms</td>
                <td style={{ ...td2, color: "#94a3b8" }}>
                  {new Date(d.deliveredAt).toLocaleString("vi-VN")}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}


const page = {
  minHeight: "100vh", background: "#0f172a", color: "#f8fafc",
  padding: "70px 28px 24px", fontFamily: "system-ui, -apple-system, sans-serif",
  maxWidth: 980, margin: "0 auto", boxSizing: "border-box",
};
const card = {
  background: "rgba(20,20,30,0.6)",
  border: "1px solid rgba(255,255,255,0.1)",
  borderRadius: 12, padding: 18, marginBottom: 14,
};
const h2 = { fontSize: 12, color: "#c4b5fd", margin: "0 0 10px",
             textTransform: "uppercase", letterSpacing: "0.05em" };
const lbl = { fontSize: 12, color: "#94a3b8", fontWeight: 600,
              display: "block", marginBottom: 4 };
const inputStyle = {
  width: "100%", boxSizing: "border-box",
  background: "rgba(255,255,255,0.08)",
  border: "1px solid rgba(255,255,255,0.15)",
  color: "#f9fafb", borderRadius: 8, padding: "8px 10px",
  fontSize: 13, minHeight: 38,
};
const tbl = { width: "100%", borderCollapse: "collapse", fontSize: 13 };
const th = {
  textAlign: "left", padding: "8px 10px",
  borderBottom: "1px solid rgba(255,255,255,0.15)",
  fontSize: 11, color: "#94a3b8", fontWeight: 600,
  textTransform: "uppercase", letterSpacing: "0.05em",
};
const th2 = { ...th, padding: "4px 8px", fontSize: 10 };
const td  = { padding: "8px 10px",
              borderBottom: "1px solid rgba(255,255,255,0.05)" };
const td2 = { padding: "4px 8px",
              borderBottom: "1px solid rgba(255,255,255,0.05)" };
const tr  = { transition: "background 0.1s" };

const btnPrimary = (disabled) => ({
  marginTop: 10,
  padding: "10px 16px", borderRadius: 8, border: "none",
  cursor: disabled ? "not-allowed" : "pointer",
  fontSize: 14, fontWeight: 600,
  background: disabled ? "#3d3d5c" : "#7c3aed",
  color: "#fff", opacity: disabled ? 0.6 : 1, minHeight: 44,
});
const btnSecondary = {
  marginTop: 10,
  padding: "8px 14px", borderRadius: 8, border: "none",
  background: "rgba(255,255,255,0.08)", color: "#f1f5f9",
  cursor: "pointer", fontSize: 13, fontWeight: 500, minHeight: 38,
};
const btnGhost = {
  padding: "6px 12px", borderRadius: 6, border: "none",
  background: "rgba(255,255,255,0.06)", color: "#cbd5e1",
  cursor: "pointer", fontSize: 12,
};
const miniBtn = {
  padding: "4px 8px", borderRadius: 5, border: "none",
  background: "rgba(124,58,237,0.4)", color: "#fff",
  cursor: "pointer", fontSize: 11, marginRight: 4, fontWeight: 600,
};
const miniDanger = {
  padding: "4px 8px", borderRadius: 5, border: "none",
  background: "rgba(239,68,68,0.4)", color: "#fff",
  cursor: "pointer", fontSize: 11, fontWeight: 600,
};
const errorBox = {
  margin: "10px 0", padding: "8px 12px",
  background: "#7f1d1d", color: "#fee2e2",
  borderRadius: 8, fontSize: 13,
};
const secretBox = {
  display: "block", padding: "10px 14px",
  background: "rgba(0,0,0,0.4)", borderRadius: 6,
  fontFamily: "monospace", fontSize: 13, color: "#bfdbfe",
  wordBreak: "break-all", cursor: "pointer", userSelect: "all",
};
const toastStyle = {
  position: "fixed", bottom: 24, left: "50%",
  transform: "translateX(-50%)",
  background: "rgba(20,20,30,0.95)", color: "#f9fafb",
  padding: "10px 20px", borderRadius: 10, fontSize: 13,
  border: "1px solid rgba(255,255,255,0.15)", zIndex: 2000,
};