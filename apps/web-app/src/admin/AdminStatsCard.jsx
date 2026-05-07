// @ts-check
// Stats grid — 6 counter card cho /admin/stats. Plain GET, refresh thủ công
// hoặc khi user invalidate (vd sau global sync).
//
// Snapshot count tại thời điểm query (không transactional cross-table). Đủ
// dùng cho admin overview, không phải nguồn cho metrics → không cần realtime.

import { useQuery } from "@tanstack/react-query";
import { ApiError } from "../auth/client.js";
import { getStats } from "./client.js";
import { strings } from "../strings.js";

const t = strings.admin.stats;
const tErr = strings.admin.errors;

export function AdminStatsCard() {
  const q = useQuery({
    queryKey: ["admin", "stats"],
    queryFn: getStats,
  });

  if (q.isPending) {
    return <SkeletonGrid label={t.loading} />;
  }
  if (q.isError) {
    return <StatsError error={q.error} />;
  }

  const s = q.data;
  /** @type {Array<[string, number]>} */
  const cells = [
    [t.userCount, s.user_count],
    [t.activeUserCount, s.active_user_count],
    [t.linkedSourceCount, s.linked_source_count],
    [t.activeSourceCount, s.active_source_count],
    [t.gatewayCount, s.gateway_count],
    [t.measurementCount, s.measurement_count],
  ];

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      {cells.map(([label, value]) => (
        <div
          key={label}
          className="rounded-lg border border-slate-200 bg-white px-3 py-3 shadow-sm"
        >
          <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
            {label}
          </div>
          <div className="mt-1 text-2xl font-bold text-slate-900">
            {value.toLocaleString("vi-VN")}
          </div>
        </div>
      ))}
    </div>
  );
}

/** @param {{ label: string }} props */
function SkeletonGrid({ label }) {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 px-3 py-6 text-center text-sm text-slate-500">
      {label}
    </div>
  );
}

/** @param {{ error: unknown }} props */
function StatsError({ error }) {
  let msg = strings.admin.errors.statsLoad;
  let code = "";
  if (error instanceof ApiError) {
    code = error.problem.code ?? "";
    const localized = tErr.byCode(code);
    msg = localized || error.problem.detail || error.problem.title || msg;
  }
  return (
    <div
      role="alert"
      className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800"
    >
      <div className="font-semibold">{msg}</div>
      {code && (
        <div className="mt-1 text-xs text-red-600">
          {tErr.errorCodeLabel}: {code}
        </div>
      )}
    </div>
  );
}
