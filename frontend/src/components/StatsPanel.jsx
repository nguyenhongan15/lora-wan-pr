import { fmt, computeCoverage } from "../utils";
import S from "../strings";

// ── Thang màu RdYlBu đồng bộ toàn app ──────────────────────────────────────
const RDYLBU = {
  veryWeak: "#313695",
  weak:     "#74add1",
  medium:   "#fdae61",
  good:     "#f46d43",
  strong:   "#a50026",
};

// Legend gradient thanh ngang
function HeatLegend() {
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{
        height: 10, borderRadius: 5,
        background: "linear-gradient(to right,#313695,#74add1,#ffffbf,#fdae61,#f46d43,#a50026)",
        marginBottom: 4,
      }} />
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9, color: "#6b7280" }}>
        <span>−135</span><span>−110</span><span>−85</span><span>−70</span><span>−55</span>
      </div>
    </div>
  );
}

function StatCard({ label, value, highlight }) {
  return (
    <div style={{
      background: highlight ? "rgba(124,58,237,0.18)" : "rgba(255,255,255,0.07)",
      borderRadius: 8, padding: "8px 12px", marginBottom: 6,
      border: highlight ? "1px solid rgba(167,139,250,0.3)" : "1px solid transparent",
    }}>
      <div style={{ fontSize: 11, color: "#9ca3af", marginBottom: 2 }}>{label}</div>
      <div style={{ fontSize: 16, fontWeight: 600, color: highlight ? "#c4b5fd" : "#f9fafb" }}>
        {value}
      </div>
    </div>
  );
}

function CoverageBar({ label, color, pct, count }) {
  return (
    <div style={{ marginBottom: 7 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, marginBottom: 3 }}>
        <span style={{ color: "#d1d5db" }}>{label}</span>
        <span style={{ color, fontWeight: 600 }}>{pct}%</span>
      </div>
      <div style={{ background: "rgba(255,255,255,0.1)", borderRadius: 4, height: 6, overflow: "hidden" }}>
        <div style={{
          width: `${pct}%`, height: "100%",
          background: color, borderRadius: 4,
          transition: "width 0.6s ease",
        }} />
      </div>
      <div style={{ fontSize: 10, color: "#6b7280", marginTop: 2 }}>
        {count.toLocaleString()} {S.stats.pointsUnit}
      </div>
    </div>
  );
}

function ModelBadge({ method, runAt }) {
  if (!method) return null;
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 6,
      background: "rgba(124,58,237,0.15)", borderRadius: 6,
      padding: "4px 8px", marginBottom: 8,
    }}>
      <div style={{ width: 7, height: 7, borderRadius: "50%", background: "#a78bfa" }} />
      <span style={{ fontSize: 11, color: "#c4b5fd", fontWeight: 600 }}>
        {method.toUpperCase()}
      </span>
      {runAt && (
        <span style={{ fontSize: 10, color: "#6b7280", marginLeft: "auto" }}>
          {new Date(runAt).toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" })}
        </span>
      )}
    </div>
  );
}

/**
 * StatsPanel — hiển thị thống kê từ backend.
 * Backend trả camelCase:
 *   stats: { total, avgRssi, minRssi, maxRssi, avgSnr }
 *   gridStatus: { hasGrid, totalPoints, avgRssiDbm, minRssiDbm, maxRssiDbm,
 *                 avgUncertaintyDb, lastGenerated }
 */
export default function StatsPanel({ stats, gridStatus, mode, pointCount, features = [] }) {
  const coverage = computeCoverage(features);

  const COVERAGE_BARS = [
    { key: "strong",   label: S.stats.coverageStrong,   color: RDYLBU.strong,   pctKey: "strongPct",   countKey: "strong"   },
    { key: "medium",   label: S.stats.coverageMedium,   color: RDYLBU.medium,   pctKey: "mediumPct",   countKey: "medium"   },
    { key: "weak",     label: S.stats.coverageWeak,     color: RDYLBU.weak,     pctKey: "weakPct",     countKey: "weak"     },
    { key: "veryWeak", label: S.stats.coverageVeryWeak, color: RDYLBU.veryWeak, pctKey: "veryWeakPct", countKey: "veryWeak" },
  ];

  const UNCERTAINTY_COLORS = ["#1D9E75", "#EF9F27", "#E24B4A", "#7B21E8"];

  return (
    <div style={{
      position: "absolute", top: 12, right: 12, zIndex: 1000,
      background: "rgba(20,20,30,0.90)", backdropFilter: "blur(10px)",
      borderRadius: 12, padding: "14px 16px", width: 215,
      color: "#f9fafb", boxShadow: "0 4px 24px rgba(0,0,0,0.35)",
      border: "1px solid rgba(255,255,255,0.1)",
      maxHeight: "92vh", overflowY: "auto",
    }}>
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 10, color: "#c4b5fd" }}>
        {S.stats.title}
      </div>

      <StatCard label={S.stats.totalPoints} value={stats?.total ?? S.scatter.popupUnknown} />
      <StatCard label={S.stats.avgRssi}    value={fmt(stats?.avgRssi, " dBm")} />
      <StatCard label={S.stats.maxRssi}    value={fmt(stats?.maxRssi, " dBm")} />
      <StatCard label={S.stats.minRssi}    value={fmt(stats?.minRssi, " dBm")} />
      <StatCard label={S.stats.avgSnr}     value={fmt(stats?.avgSnr, " dB")} />

      {mode === "scatter" && (
        <StatCard label={S.stats.displaying} value={`${pointCount} ${S.stats.pointsUnit}`} />
      )}

      <SectionDivider label={S.stats.sectionSignal} />
      <HeatLegend />

      {coverage && (
        <>
          <SectionDivider label={S.stats.sectionCoverage} />
          {COVERAGE_BARS.map(b => (
            <CoverageBar
              key={b.key}
              label={b.label}
              color={b.color}
              pct={coverage[b.pctKey]}
              count={coverage[b.countKey]}
            />
          ))}
        </>
      )}

      {(mode === "ml-heat" || mode === "uncertainty") && gridStatus?.hasGrid && (
        <>
          <SectionDivider label={S.stats.sectionML} />
          <ModelBadge
            method={gridStatus?.algorithm ?? "IDW"}
            runAt={gridStatus?.lastGenerated}
          />
          <StatCard label={S.stats.gridPoints}     value={gridStatus.totalPoints?.toLocaleString()} />
          <StatCard label={S.stats.avgPredRssi}    value={fmt(gridStatus.avgRssiDbm, " dBm")} />
          <StatCard label={S.stats.avgUncertainty} value={fmt(gridStatus.avgUncertaintyDb, " dB")} highlight />

          <div style={{
            fontSize: 10, color: "#6b7280", lineHeight: 1.5,
            background: "rgba(255,255,255,0.04)", borderRadius: 6,
            padding: "6px 8px", marginTop: 4,
          }}>
            {S.stats.mlNoMetric}
          </div>
        </>
      )}

      {mode === "uncertainty" && (
        <>
          <SectionDivider label={S.stats.sectionUncertainty} />
          <div style={{ fontSize: 11, lineHeight: 1.6 }}>
            {S.stats.uncertaintyLevels.map(({ label }, i) => (
              <div key={label} style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 4 }}>
                <div style={{ width: 10, height: 10, borderRadius: "50%", background: UNCERTAINTY_COLORS[i], flexShrink: 0 }} />
                <span style={{ color: "#d1d5db" }}>{label}</span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function SectionDivider({ label }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, margin: "12px 0 8px" }}>
      <div style={{ flex: 1, height: 1, background: "rgba(255,255,255,0.1)" }} />
      <span style={{ fontSize: 10, color: "#6b7280", whiteSpace: "nowrap" }}>{label}</span>
      <div style={{ flex: 1, height: 1, background: "rgba(255,255,255,0.1)" }} />
    </div>
  );
}
