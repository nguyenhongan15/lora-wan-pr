// @ts-check
// OverviewDashboard — 3 time-series chart (visits / signups / training points)
// + 1 horizontal bar chart (top 5 gateway). Mỗi time-series chart có dropdown
// chọn bucket (tuần / tháng / năm) độc lập. Backend trả buckets đầy đủ kể cả 0.

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ApiError } from "../auth/client.js";
import { getStatsTimeseries, getTopGateways } from "./client.js";
import { strings } from "../strings.js";

const t = strings.admin.dashboard;
const tErr = strings.admin.errors;

export function OverviewDashboard() {
  return (
    <section className="mt-4">
      <header className="mb-3">
        <h3 className="text-sm font-semibold text-slate-900">{t.sectionTitle}</h3>
        <p className="mt-1 text-xs text-slate-500">{t.sectionSubtitle}</p>
      </header>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <TimeseriesChart
          metric="visits"
          title={t.chartVisitsTitle}
          color="#0ea5e9"
        />
        <TimeseriesChart
          metric="signups"
          title={t.chartSignupsTitle}
          color="#10b981"
        />
        <TimeseriesChart
          metric="training_points"
          title={t.chartTrainingTitle}
          color="#f59e0b"
        />
        <TopGatewaysChart />
      </div>
    </section>
  );
}

/**
 * @param {{
 *   metric: "visits" | "signups" | "training_points",
 *   title: string,
 *   color: string,
 * }} props
 */
function TimeseriesChart({ metric, title, color }) {
  const [bucket, setBucket] = useState(
    /** @type {"week"|"month"|"year"} */ ("week"),
  );
  const q = useQuery({
    queryKey: ["admin", "stats", "timeseries", metric, bucket],
    queryFn: () => getStatsTimeseries(metric, bucket),
  });

  const data = (q.data?.items ?? []).map((p) => ({
    label: formatBucketLabel(p.bucket_start, bucket),
    count: p.count,
  }));

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h4 className="text-xs font-semibold text-slate-800">{title}</h4>
        <select
          value={bucket}
          onChange={(e) =>
            setBucket(/** @type {"week"|"month"|"year"} */ (e.target.value))
          }
          className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs"
        >
          <option value="week">{t.bucketWeek}</option>
          <option value="month">{t.bucketMonth}</option>
          <option value="year">{t.bucketYear}</option>
        </select>
      </div>

      {q.isPending && <div className="text-xs text-slate-500">{t.loading}</div>}
      {q.isError && <ChartError error={q.error} />}

      {q.data && (
        <div className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
              <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" />
              <XAxis dataKey="label" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
              <YAxis allowDecimals={false} tick={{ fontSize: 10 }} />
              <Tooltip
                contentStyle={{ fontSize: 12 }}
                formatter={(v) => [Number(v).toLocaleString("vi-VN"), t.yAxisCount]}
              />
              <Line
                type="monotone"
                dataKey="count"
                stroke={color}
                strokeWidth={2}
                dot={{ r: 3 }}
                activeDot={{ r: 5 }}
                name={t.yAxisCount}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

function TopGatewaysChart() {
  const q = useQuery({
    queryKey: ["admin", "stats", "top-gateways"],
    queryFn: getTopGateways,
  });

  const data = (q.data?.items ?? []).map((g) => ({
    label: g.name ? `${g.gateway_code} — ${g.name}` : g.gateway_code,
    count: g.training_count,
  }));

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
      <h4 className="mb-2 text-xs font-semibold text-slate-800">{t.chartTopGwTitle}</h4>

      {q.isPending && <div className="text-xs text-slate-500">{t.loading}</div>}
      {q.isError && <ChartError error={q.error} />}
      {q.data && data.length === 0 && (
        <div className="text-xs text-slate-500">{t.empty}</div>
      )}

      {q.data && data.length > 0 && (
        <div className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={data}
              layout="vertical"
              margin={{ top: 5, right: 10, left: 60, bottom: 0 }}
            >
              <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" />
              <XAxis type="number" allowDecimals={false} tick={{ fontSize: 10 }} />
              <YAxis
                type="category"
                dataKey="label"
                tick={{ fontSize: 10 }}
                width={140}
              />
              <Tooltip
                contentStyle={{ fontSize: 12 }}
                formatter={(v) => [Number(v).toLocaleString("vi-VN"), t.yAxisCount]}
              />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar dataKey="count" fill="#8b5cf6" name={t.gatewayLabel} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

/**
 * @param {string} iso
 * @param {"week"|"month"|"year"} bucket
 */
function formatBucketLabel(iso, bucket) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  if (bucket === "year") return String(d.getFullYear());
  if (bucket === "month") {
    return d.toLocaleDateString("vi-VN", { month: "2-digit", year: "2-digit" });
  }
  return d.toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit" });
}

/** @param {{ error: unknown }} props */
function ChartError({ error }) {
  let msg = t.errorLoad;
  let code = "";
  if (error instanceof ApiError) {
    code = error.problem.code ?? "";
    const localized = tErr.byCode(code);
    msg = localized || error.problem.detail || error.problem.title || msg;
  }
  return (
    <div className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-800">
      <div className="font-semibold">{msg}</div>
      {code && (
        <div className="mt-1 text-[11px] text-red-600">
          {tErr.errorCodeLabel}: {code}
        </div>
      )}
    </div>
  );
}
