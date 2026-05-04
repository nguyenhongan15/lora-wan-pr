import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import S from "../strings";
import NavBar from "../components/NavBar";


export default function CalibrationPage() {
  const [campaigns,    setCampaigns]    = useState([]);
  const [campaignId,   setCampaignId]   = useState("");
  const [file,         setFile]         = useState(null);
  const [uploading,    setUploading]    = useState(false);
  const [result,       setResult]       = useState(null);
  const [metrics,      setMetrics]      = useState(null);
  const [error,        setError]        = useState(null);
  const fileInputRef = useRef(null);

  useEffect(() => {
    api.getCampaigns()
      .then(arr => {
        setCampaigns(arr ?? []);
        if (arr?.length && !campaignId) setCampaignId(arr[0].id);
      })
      .catch(e => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    // Reset metrics khi đổi campaign — intentional pattern
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (!campaignId) { setMetrics(null); return; }
    api.getCalibrationMetrics(campaignId)
      .then(setMetrics)
      .catch(() => setMetrics(null));
  }, [campaignId]);

  const handleUpload = async () => {
    if (!file || !campaignId) return;
    setUploading(true);
    setError(null);
    setResult(null);
    try {
      const data = await api.uploadCalibrationCsv(campaignId, file);
      setResult(data);
      setMetrics(data.calibrationMetrics);
    } catch (e) {
      setError(e.message);
    } finally {
      setUploading(false);
    }
  };

  return (
    <>
      <NavBar />
      <main style={page}>
        <header style={{ marginBottom: 18 }}>
          <h1 style={{ fontSize: 22, margin: 0 }}>{S.calibration.title}</h1>
          <p style={{ fontSize: 13, color: "#94a3b8", margin: "4px 0 0" }}>
            {S.calibration.subtitle}
          </p>
        </header>

        <section style={card}>
          <div style={field}>
            <label htmlFor="cmp" style={lbl}>{S.calibration.campaign}</label>
            <select
              id="cmp" value={campaignId}
              onChange={e => setCampaignId(e.target.value)}
              style={selectStyle}
            >
              {campaigns.map(c => (
                <option key={c.id} value={c.id} style={{ background: "#1a1a2e" }}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>

          <div style={{ ...field, marginTop: 12 }}>
            <div style={{ ...lbl, marginBottom: 4 }}>CSV</div>
            <p style={hint}>{S.calibration.uploadHint}</p>
            <p style={hintSub}>{S.calibration.uploadOptional}</p>

            <input
              ref={fileInputRef}
              id="csv"
              type="file"
              accept=".csv,text/csv"
              onChange={e => setFile(e.target.files?.[0] ?? null)}
              style={{ display: "none" }}
            />

            <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 6 }}>
              <button type="button" onClick={() => fileInputRef.current?.click()}
                      style={btnSecondary}>
                {S.calibration.btnPick}
              </button>
              <span style={{ fontSize: 13, color: file ? "#cbd5e1" : "#64748b" }}>
                {file ? file.name : S.calibration.noFile}
              </span>
            </div>
          </div>

          <button
            type="button"
            onClick={handleUpload}
            disabled={!file || !campaignId || uploading}
            style={btnPrimary(!file || !campaignId || uploading)}
          >
            {uploading ? S.calibration.btnUploading : S.calibration.btnUpload}
          </button>

          {error && (
            <div role="alert" style={errorBox}>{error}</div>
          )}
        </section>

        {result && (
          <section style={card}>
            <h2 style={h2}>{S.calibration.resultTitle}</h2>
            <Row label={S.calibration.rowsInFile} value={result.rowsInFile} />
            <Row label={S.calibration.inserted}   value={result.inserted}   accent="#10b981" />
            <Row label={S.calibration.skipped}    value={result.skipped}    accent={result.skipped > 0 ? "#f59e0b" : null} />
          </section>
        )}

        <section style={card}>
          <h2 style={h2}>{S.calibration.metricsTitle}</h2>

          {!metrics || metrics.n === 0 ? (
            <p style={{ fontSize: 13, color: "#94a3b8", margin: 0 }}>
              {S.calibration.noMetrics}
            </p>
          ) : (
            <>
              <Row label={S.calibration.metricsN}    value={metrics.n} />
              <Row label={S.calibration.metricsRmse} value={metrics.rmseDb} mono />
              <Row label={S.calibration.metricsMae}  value={metrics.maeDb}  mono />
              <Row label={S.calibration.metricsBias} value={metrics.biasDb} mono
                   accent={Math.abs(metrics.biasDb ?? 0) > 3 ? "#f59e0b" : null} />
              <p style={{ fontSize: 11, color: "#64748b", marginTop: 8 }}>
                {S.calibration.biasHint}
              </p>
            </>
          )}
        </section>
      </main>
    </>
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


const page = {
  minHeight: "100vh", background: "#0f172a", color: "#f8fafc",
  padding: "70px 28px 24px", fontFamily: "system-ui, -apple-system, sans-serif",
  maxWidth: 720, margin: "0 auto", boxSizing: "border-box",
};
const card = {
  background: "rgba(20,20,30,0.6)",
  border: "1px solid rgba(255,255,255,0.1)",
  borderRadius: 12, padding: 18, marginBottom: 14,
};
const h2 = { fontSize: 14, color: "#c4b5fd", margin: "0 0 10px",
             textTransform: "uppercase", letterSpacing: "0.05em" };
const field = { display: "flex", flexDirection: "column", gap: 4 };
const lbl   = { fontSize: 12, color: "#94a3b8", fontWeight: 600 };
const hint  = { fontSize: 12, color: "#94a3b8", margin: "2px 0" };
const hintSub = { fontSize: 11, color: "#64748b", margin: 0 };
const selectStyle = {
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
const btnSecondary = {
  padding: "8px 14px", borderRadius: 8, border: "none",
  background: "rgba(255,255,255,0.08)", color: "#f1f5f9",
  cursor: "pointer", fontSize: 13, fontWeight: 500, minHeight: 40,
};
const errorBox = {
  marginTop: 10, padding: "8px 12px",
  background: "#7f1d1d", color: "#fee2e2",
  borderRadius: 8, fontSize: 13,
};