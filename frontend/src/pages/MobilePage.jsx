/**
 * pages/MobilePage.jsx
 * ────────────────────
 * Trang Mobile-first cho Persona 5 (end-user) — trả lời câu hỏi
 * duy nhất họ quan tâm: "Khu vực của tôi có sóng không?".
 *
 * Tuân thủ:
 *   - Atomic Design: page-level component, gọi atoms/molecules
 *   - WCAG 2.1: touch target ≥ 44px, aria-live cho verdict động,
 *     contrast ≥ 4.5:1, không phụ thuộc màu sắc (mỗi level có icon + text)
 *   - Tiêu chuẩn lập trình web tiếp cận: semantic HTML (main/section/h1/h2),
 *     visible focus, button thực thay vì div onClick
 *   - Component-driven: tách atoms (Card, ScanButton) trong cùng file vì
 *     chỉ dùng trong page này (Simplicity First — không over-engineer)
 *   - Không lộ thông số kỹ thuật cho Persona 5 (RSSI/SNR/SF ẩn)
 */

import { useCallback, useState } from "react";
import { api } from "../api";
import S from "../strings";

// ─────────────────────────────────────────────────────────────
// Design tokens — đặt cạnh page vì single-use (Simplicity First)
// Màu chọn theo WCAG large text 3:1 với nền trắng
// ─────────────────────────────────────────────────────────────
const LEVEL_STYLE = {
  strong:  { bg: "#059669", border: "#047857", icon: "✓" },
  medium:  { bg: "#d97706", border: "#b45309", icon: "≈" },
  weak:    { bg: "#ea580c", border: "#c2410c", icon: "!" },
  none:    { bg: "#dc2626", border: "#b91c1c", icon: "✕" },
  no_data: { bg: "#475569", border: "#334155", icon: "?" },
};


// ─────────────────────────────────────────────────────────────
// Bearing helpers — mirror backend routers/coverage.py
// In-file vì single-use trong page Persona 5
// ─────────────────────────────────────────────────────────────
const DIRS_VI = ["Bắc", "Đông Bắc", "Đông", "Đông Nam",
                 "Nam", "Tây Nam", "Tây", "Tây Bắc"];

function bearingDeg(lat1, lng1, lat2, lng2) {
  const toRad = (d) => (d * Math.PI) / 180;
  const p1 = toRad(lat1), p2 = toRad(lat2);
  const dl = toRad(lng2 - lng1);
  const y  = Math.sin(dl) * Math.cos(p2);
  const x  = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl);
  return ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360;
}

function directionVi(deg) {
  return DIRS_VI[Math.round(deg / 45) % 8];
}


// ─────────────────────────────────────────────────────────────
// Atoms (in-file vì single-use)
// ─────────────────────────────────────────────────────────────

function VerdictCard({ loading, error, coverage }) {
  const level = coverage?.level;
  const style = level ? LEVEL_STYLE[level] : null;

  const cardStyle = {
    border:        "2px solid",
    borderRadius:  16,
    padding:       "28px 20px",
    minHeight:     180,
    display:       "flex",
    flexDirection: "column",
    justifyContent:"center",
    alignItems:    "center",
    textAlign:     "center",
    gap:           8,
    color:         "#fff",
    background:    style?.bg     ?? "#1e293b",
    borderColor:   style?.border ?? "#334155",
    transition:    "background 0.3s, border-color 0.3s",
  };

  return (
    <section
      aria-live="polite"
      aria-busy={loading}
      aria-label="Kết quả kiểm tra phủ sóng"
      style={cardStyle}
    >
      {loading && (
        <div style={{ fontSize: 22, fontWeight: 600 }}>
          {S.mobile.scanning}
        </div>
      )}

      {!loading && error && (
        <div style={{ fontSize: 16, color: "#fee2e2", lineHeight: 1.5 }}>
          {error}
        </div>
      )}

      {!loading && !error && !coverage && (
        <div style={{ fontSize: 22, color: "#cbd5e1", fontWeight: 500 }}>
          {S.mobile.idle}
        </div>
      )}

      {!loading && !error && coverage && (
        <>
          <div aria-hidden="true" style={{ fontSize: 56, fontWeight: 800, lineHeight: 1 }}>
            {style.icon}
          </div>
          <div style={{ fontSize: 26, fontWeight: 700 }}>
            {coverage.verdict}
          </div>
          <div style={{ fontSize: 13, opacity: 0.92 }}>
            {S.mobile.basedOn(coverage.samplesUsed ?? 0)}
          </div>
        </>
      )}
    </section>
  );
}


function NearestGatewayCard({ gw }) {
  if (!gw) return null;
  return (
    <section style={infoCardStyle}>
      <h2 style={h2Style}>{S.mobile.nearestGateway}</h2>
      <p style={{ fontSize: 15, margin: "6px 0 0", color: "#f1f5f9" }}>
        <strong>{gw.name || S.mobile.unnamedGw}</strong>
        <span style={{ color: "#94a3b8" }}>
          {" · "}{Math.round(gw.distanceM)}{S.mobile.meterUnit}
          {" · "}{S.mobile.directionPrefix} {gw.direction}
        </span>
      </p>
    </section>
  );
}


function PathCard({ path }) {
  if (!path) return null;

  // path.path[0] là start, các phần tử sau là từng bước.
  // stopReason in {no_data, no_improvement, reached_strong, max_steps}.
  const wps  = path.path || [];
  const noMovement = wps.length <= 1;
  const failed     = path.stopReason === "no_data";

  if (failed) {
    return (
      <section style={{ ...infoCardStyle, background: "#1e293b" }}>
        <h2 style={h2Style}>{S.mobile.pathTitle}</h2>
        <p style={{ fontSize: 14, color: "#cbd5e1", margin: "6px 0 0" }}>
          {path.message || S.mobile.suggestionNotFound}
        </p>
      </section>
    );
  }

  if (noMovement) {
    return (
      <section style={{ ...infoCardStyle, background: "#1e293b" }}>
        <h2 style={h2Style}>{S.mobile.pathTitle}</h2>
        <p style={{ fontSize: 14, color: "#cbd5e1", margin: "6px 0 0" }}>
          {path.message || S.mobile.pathNoSteps}
        </p>
      </section>
    );
  }

  // Tính bearing per step (backend chỉ trả tọa độ)
  const steps = [];
  for (let i = 1; i < wps.length; i++) {
    const prev = wps[i - 1], cur = wps[i];
    const deg  = bearingDeg(prev.lat, prev.lng, cur.lat, cur.lng);
    steps.push({
      n:        i,
      dir:      directionVi(deg),
      meters:   Math.round(cur.stepDistanceM ?? 0),
      level:    cur.level,
      verdict:  cur.verdict,
    });
  }

  const totalM = Math.round(path.totalDistanceM ?? 0);

  return (
    <section style={{ ...infoCardStyle, background: "#1e3a8a", borderColor: "#3b82f6" }}>
      <h2 style={h2Style}>{S.mobile.pathTitle}</h2>

      <ol style={{
        margin:        "10px 0 6px",
        padding:       0,
        listStyle:     "none",
        display:       "flex",
        flexDirection: "column",
        gap:           6,
      }}>
        {steps.map((s) => {
          const st = LEVEL_STYLE[s.level] || LEVEL_STYLE.no_data;
          return (
            <li key={s.n} style={{
              display:    "flex",
              alignItems: "center",
              gap:        10,
              fontSize:   15,
              color:      "#f1f5f9",
            }}>
              <span aria-hidden="true" style={{
                flex:        "0 0 28px",
                height:      28,
                lineHeight:  "28px",
                textAlign:   "center",
                fontWeight:  700,
                fontSize:    13,
                background:  st.bg,
                borderRadius: 14,
              }}>
                {st.icon}
              </span>
              <span>{S.mobile.pathStep(s.n, s.dir, s.meters)}</span>
            </li>
          );
        })}
      </ol>

      <p style={{ fontSize: 13, color: "#bfdbfe", margin: "8px 0 0" }}>
        {S.mobile.pathSummary(steps.length, totalM)}
      </p>

      {path.finalVerdict && (
        <p style={{ fontSize: 13, color: "#bfdbfe", margin: "2px 0 0" }}>
          {S.mobile.pathExpectedFinal} {path.finalVerdict}
        </p>
      )}

      {path.message && (
        <p style={{ fontSize: 12, color: "#94a3b8", margin: "6px 0 0", fontStyle: "italic" }}>
          {path.message}
        </p>
      )}
    </section>
  );
}


function ScanButton({ loading, hasResult, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={loading}
      aria-label={S.mobile.scanButtonAria}
      style={{
        marginTop:  4,
        padding:    "16px 24px",
        minHeight:  56,                        // > WCAG 44×44 touch target
        fontSize:   17,
        fontWeight: 700,
        background: "#7c3aed",
        color:      "#fff",
        border:     "none",
        borderRadius: 14,
        boxShadow:  "0 4px 14px rgba(124,58,237,0.4)",
        cursor:     loading ? "not-allowed" : "pointer",
        opacity:    loading ? 0.6 : 1,
        transition: "opacity 0.15s, transform 0.05s",
      }}
    >
      {loading
        ? S.mobile.scanning
        : hasResult ? S.mobile.retry : S.mobile.scanButton}
    </button>
  );
}


// ─────────────────────────────────────────────────────────────
// Page
// ─────────────────────────────────────────────────────────────

export default function MobilePage() {
  const [loading,  setLoading]  = useState(false);
  const [coverage, setCoverage] = useState(null);
  const [path,     setPath]     = useState(null);
  const [error,    setError]    = useState(null);
  const [coords,   setCoords]   = useState(null);

  const fetchCoverage = useCallback(async (lat, lng) => {
    try {
      const data = await api.getCoverageCheck(lat, lng);
      setCoverage(data);

      // Sóng yếu/không có/no_data → tự động lấy đường đi đến vùng tốt hơn
      if (data.level === "weak" || data.level === "none" || data.level === "no_data") {
        try {
          const p = await api.getCoveragePathToCoverage(lat, lng);
          setPath(p);
        } catch {
          // Path là tính năng phụ — không làm hỏng main flow
          setPath(null);
        }
      } else {
        setPath(null);
      }
    } catch (e) {
      setError(e.message || S.mobile.errorGeneric);
    } finally {
      setLoading(false);
    }
  }, []);

  const handleScan = useCallback(() => {
    if (!navigator.geolocation) {
      setError(S.mobile.errorGpsUnsupported);
      return;
    }

    setLoading(true);
    setError(null);
    setCoverage(null);
    setPath(null);

    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const c = { lat: pos.coords.latitude, lng: pos.coords.longitude };
        setCoords(c);
        fetchCoverage(c.lat, c.lng);
      },
      (err) => {
        setLoading(false);
        setError(
          err.code === err.PERMISSION_DENIED ? S.mobile.errorGpsDenied
                                             : S.mobile.errorGpsFailed,
        );
      },
      { enableHighAccuracy: true, timeout: 10_000, maximumAge: 30_000 },
    );
  }, [fetchCoverage]);

  return (
    <main style={containerStyle}>
      <header style={{ textAlign: "center", marginBottom: 4 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, margin: 0 }}>
          {S.mobile.title}
        </h1>
        <p style={{ fontSize: 13, color: "#94a3b8", margin: "4px 0 0" }}>
          {S.mobile.subtitle}
        </p>
      </header>

      <VerdictCard loading={loading} error={error} coverage={coverage} />

      <NearestGatewayCard gw={coverage?.nearestGateway} />

      <PathCard path={path} />

      <ScanButton
        loading={loading}
        hasResult={!!coverage || !!error}
        onClick={handleScan}
      />

      {coords && (
        <p style={{
          textAlign:  "center",
          color:      "#64748b",
          fontSize:   12,
          fontFamily: "monospace",
          margin:     0,
        }}>
          📍 {coords.lat.toFixed(5)}, {coords.lng.toFixed(5)}
        </p>
      )}
    </main>
  );
}


// ─────────────────────────────────────────────────────────────
// Shared inline styles (Simplicity First — single-use, no abstraction)
// ─────────────────────────────────────────────────────────────

const containerStyle = {
  maxWidth:      480,
  margin:        "0 auto",
  minHeight:     "100vh",
  padding:       "20px 16px 32px",
  background:    "#0f172a",
  color:         "#f8fafc",
  fontFamily:    "system-ui, -apple-system, sans-serif",
  display:       "flex",
  flexDirection: "column",
  gap:           14,
  boxSizing:     "border-box",
};

const infoCardStyle = {
  background:   "#1e293b",
  border:       "1px solid #334155",
  borderRadius: 12,
  padding:      "12px 16px",
};

const h2Style = {
  fontSize:       12,
  color:          "#94a3b8",
  margin:         0,
  fontWeight:     600,
  letterSpacing:  "0.05em",
  textTransform:  "uppercase",
};