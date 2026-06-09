// @ts-check
// Coverage rebuild panel — admin trigger rebuild composite + per-gw RSSI map.
//
// UX flow:
//   1. Click "Rebuild ngay" → POST /admin/coverage/rebuild → job_id (queued).
//   2. Poll GET /admin/coverage/rebuild/{job_id} mỗi 5s tới khi status ∈
//      {succeeded, failed}. React-query handles refetch + stop.
//   3. Hiển thị per_gw_log + summary. Lịch sử 5 jobs gần nhất ở dưới.
//
// Lý do polling 5s (không WebSocket): job ~5-10 phút, polling overhead nhỏ;
// thêm WS phức tạp hơn nhiều giá trị mang lại. Match pattern với GlobalSyncPanel
// (request → render report → invalidate liên quan).

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../auth/client.js";
import {
  enqueueCoverageRebuild,
  getCoverageRebuildJob,
  listRecentCoverageRebuilds,
} from "./client.js";
import { strings } from "../strings.js";

const t = strings.admin.rebuild;
const tErr = strings.admin.errors;

export function CoverageRebuildPanel() {
  const qc = useQueryClient();
  const [activeJobId, setActiveJobId] = useState(/** @type {string | null} */ (null));

  const enqueueM = useMutation({
    mutationFn: enqueueCoverageRebuild,
    onSuccess: (data) => {
      setActiveJobId(data.job_id);
      qc.invalidateQueries({ queryKey: ["admin", "coverage", "rebuild", "history"] });
    },
  });

  const jobQ = useQuery({
    queryKey: ["admin", "coverage", "rebuild", "job", activeJobId],
    queryFn: () => {
      if (!activeJobId) throw new Error("no job");
      return getCoverageRebuildJob(activeJobId);
    },
    enabled: !!activeJobId,
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      if (s === "succeeded" || s === "failed") return false;
      return 5000;
    },
  });

  const historyQ = useQuery({
    queryKey: ["admin", "coverage", "rebuild", "history"],
    queryFn: listRecentCoverageRebuilds,
  });

  // Khi job vừa kết thúc → invalidate history + composite geojson cache.
  const status = jobQ.data?.status;
  useEffect(() => {
    if (status === "succeeded" || status === "failed") {
      qc.invalidateQueries({ queryKey: ["admin", "coverage", "rebuild", "history"] });
    }
  }, [status, qc]);

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <header className="mb-3 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">{t.title}</h3>
          <p className="text-xs text-slate-500">{t.subtitle}</p>
        </div>
        <button
          type="button"
          onClick={() => enqueueM.mutate()}
          disabled={enqueueM.isPending || jobQ.data?.status === "running" || jobQ.data?.status === "queued"}
          className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white shadow-sm hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
        >
          {enqueueM.isPending ? t.btnPending : t.btn}
        </button>
      </header>

      {enqueueM.isError && <RebuildError error={enqueueM.error} />}
      {jobQ.data && <JobStatusView job={jobQ.data} />}

      <HistoryView query={historyQ} />
    </section>
  );
}

/** @param {{ job: import("./client.js").CoverageRebuildJobT }} props */
function JobStatusView({ job }) {
  const statusLabel = {
    queued: t.statusQueued,
    running: t.statusRunning,
    succeeded: t.statusSucceeded,
    failed: t.statusFailed,
  }[job.status];

  const badgeClass = {
    queued: "bg-slate-100 text-slate-700",
    running: "bg-blue-100 text-blue-700",
    succeeded: "bg-emerald-100 text-emerald-700",
    failed: "bg-red-100 text-red-700",
  }[job.status];

  const isDone = job.status === "succeeded" || job.status === "failed";
  const noNewData =
    job.status === "succeeded" && job.gateways_rebuilt === 0 && job.gateways_skipped > 0;

  return (
    <div className="mt-3 space-y-2 text-xs">
      <div className="flex items-center gap-2">
        <span className={`rounded px-2 py-0.5 text-[11px] font-medium ${badgeClass}`}>
          {statusLabel}
        </span>
        {isDone && (
          <span className="text-slate-600">{t.summary(job.gateways_rebuilt, job.gateways_skipped)}</span>
        )}
      </div>

      {noNewData && (
        <div className="rounded bg-amber-50 px-3 py-2 text-amber-800">{t.noNewData}</div>
      )}

      {job.error_text && (
        <details className="rounded border border-red-200 bg-red-50 px-3 py-2">
          <summary className="cursor-pointer font-medium text-red-800">{t.statusFailed}</summary>
          <pre className="mt-2 whitespace-pre-wrap break-all text-[11px] text-red-700">
            {job.error_text}
          </pre>
        </details>
      )}

      {isDone && Object.keys(job.per_gw_log).length > 0 && (
        <details className="rounded border border-slate-200 bg-slate-50 px-3 py-2">
          <summary className="cursor-pointer font-medium text-slate-700">{t.perGwHeading}</summary>
          <table className="mt-2 w-full text-[11px]">
            <thead className="text-left text-slate-500">
              <tr>
                {t.perGwHeaders.map((h) => (
                  <th key={h} className="py-1 pr-2">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {Object.entries(job.per_gw_log).map(([code, info]) => (
                <PerGwRow key={code} code={code} info={info} />
              ))}
            </tbody>
          </table>
        </details>
      )}
    </div>
  );
}

/** @param {{ code: string, info: any }} props */
function PerGwRow({ code, info }) {
  const status = info?.status ?? "unknown";
  const reason = info?.reason ?? null;
  const statusLabel = t.perGwStatus[status] ?? status;
  const reasonLabel = reason ? t.perGwReason[reason] ?? reason : "";
  return (
    <tr className="border-t border-slate-200">
      <td className="py-1 pr-2 font-mono">{code}</td>
      <td className="py-1 pr-2">{statusLabel}</td>
      <td className="py-1 pr-2 text-slate-500">{reasonLabel}</td>
    </tr>
  );
}

/** @param {{ query: import("@tanstack/react-query").UseQueryResult<import("./client.js").CoverageRebuildJobListT> }} props */
function HistoryView({ query }) {
  if (!query.data) return null;
  if (query.data.items.length === 0) {
    return (
      <div className="mt-4 text-xs text-slate-500">
        <div className="mb-1 font-medium text-slate-700">{t.historyHeading}</div>
        <div>{t.historyEmpty}</div>
      </div>
    );
  }
  return (
    <div className="mt-4 text-xs">
      <div className="mb-1 font-medium text-slate-700">{t.historyHeading}</div>
      <table className="w-full">
        <thead className="text-left text-[11px] text-slate-500">
          <tr>
            {t.historyHeaders.map((h) => (
              <th key={h} className="py-1 pr-2 font-normal">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {query.data.items.map((j) => (
            <tr key={j.id} className="border-t border-slate-200">
              <td className="py-1 pr-2 text-slate-600">
                {new Date(j.triggered_at).toLocaleString("vi-VN")}
              </td>
              <td className="py-1 pr-2">
                <StatusBadge status={j.status} />
              </td>
              <td className="py-1 pr-2 text-slate-700">{j.gateways_rebuilt}</td>
              <td className="py-1 pr-2 text-slate-700">{j.gateways_skipped}</td>
              <td className="py-1 pr-2 text-red-700">
                {j.error_text ? j.error_text.split("\n")[0].slice(0, 80) : ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** @param {{ status: import("./client.js").CoverageRebuildJobT["status"] }} props */
function StatusBadge({ status }) {
  const label = {
    queued: t.statusQueued,
    running: t.statusRunning,
    succeeded: t.statusSucceeded,
    failed: t.statusFailed,
  }[status];
  const cls = {
    queued: "bg-slate-100 text-slate-700",
    running: "bg-blue-100 text-blue-700",
    succeeded: "bg-emerald-100 text-emerald-700",
    failed: "bg-red-100 text-red-700",
  }[status];
  return <span className={`rounded px-2 py-0.5 text-[11px] ${cls}`}>{label}</span>;
}

/** @param {{ error: unknown }} props */
function RebuildError({ error }) {
  let msg = t.errorRequest;
  let code = "";
  if (error instanceof ApiError) {
    code = error.problem.code ?? "";
    const localized = tErr.byCode(code);
    msg = localized || error.problem.detail || error.problem.title || msg;
  }
  return (
    <div
      role="alert"
      className="mt-3 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-800"
    >
      <div className="font-semibold">{msg}</div>
      {code && (
        <div className="mt-1 text-[11px] text-red-600">
          {tErr.errorCodeLabel}: {code}
        </div>
      )}
    </div>
  );
}
