// @ts-check
// MLRetrainPanel — admin trigger retrain Extra Trees ML model.
//
// Clone CoverageRebuildPanel:
//   1. Click "Retrain ngay" → POST /admin/ml/retrain → job_id queued.
//   2. Poll GET /admin/ml/retrain/{job_id} mỗi 5s tới succeeded/failed.
//   3. Hiển thị metrics (RMSE/MAE/R²) + rows_trained + history 5 jobs gần nhất.
//
// Note (CSV gap): pipeline đọc CSV preprocessed, không phải ts.survey_training
// → joblib output có thể không thay đổi sau admin xoá batch. Warning shown
// top of panel.

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../auth/client.js";
import {
  enqueueMlRetrain,
  fetchMlRetrainReportHtml,
  fetchMlRetrainReportPdf,
  getMlRetrainJob,
  listRecentMlRetrains,
} from "./client.js";
import { strings } from "../strings.js";

const t = strings.admin.retrain;
const tErr = strings.admin.errors;

export function MLRetrainPanel() {
  const qc = useQueryClient();
  const [activeJobId, setActiveJobId] = useState(
    /** @type {string | null} */ (null),
  );

  const enqueueM = useMutation({
    mutationFn: enqueueMlRetrain,
    onSuccess: (data) => {
      setActiveJobId(data.job_id);
      qc.invalidateQueries({ queryKey: ["admin", "ml", "retrain", "history"] });
    },
  });

  const jobQ = useQuery({
    queryKey: ["admin", "ml", "retrain", "job", activeJobId],
    queryFn: () => {
      if (!activeJobId) throw new Error("no job");
      return getMlRetrainJob(activeJobId);
    },
    enabled: !!activeJobId,
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      if (s === "succeeded" || s === "failed") return false;
      return 5000;
    },
  });

  const historyQ = useQuery({
    queryKey: ["admin", "ml", "retrain", "history"],
    queryFn: listRecentMlRetrains,
  });

  const status = jobQ.data?.status;
  useEffect(() => {
    if (status === "succeeded" || status === "failed") {
      qc.invalidateQueries({ queryKey: ["admin", "ml", "retrain", "history"] });
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
          disabled={
            enqueueM.isPending ||
            jobQ.data?.status === "running" ||
            jobQ.data?.status === "queued"
          }
          className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white shadow-sm hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
        >
          {enqueueM.isPending ? t.btnPending : t.btn}
        </button>
      </header>

      <div className="mb-3 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] text-amber-800">
        {t.csvGapWarning}
      </div>

      {enqueueM.isError && <RetrainError error={enqueueM.error} />}
      {jobQ.data && <JobStatusView job={jobQ.data} />}

      <HistoryView query={historyQ} />
    </section>
  );
}

// Mở HTML báo cáo trong tab mới. Authentication bằng Bearer → không dùng anchor
// trực tiếp được; phải fetch blob rồi tạo object URL. Trình duyệt giữ blob sau
// khi tab phụ load, revoke sau 60s để tránh leak.
async function openReportHtml(jobId) {
  try {
    const blob = await fetchMlRetrainReportHtml(jobId);
    const url = URL.createObjectURL(blob);
    window.open(url, "_blank", "noopener,noreferrer");
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  } catch {
    alert(t.reportOpenFailed);
  }
}

async function downloadReportPdf(jobId) {
  try {
    const blob = await fetchMlRetrainReportPdf(jobId);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `bao-cao-ml-${jobId}.pdf`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  } catch {
    alert(t.reportDownloadFailed);
  }
}

/** @param {{ jobId: string }} props */
function ReportActions({ jobId }) {
  return (
    <div className="inline-flex gap-1">
      <button
        type="button"
        onClick={() => openReportHtml(jobId)}
        className="rounded border border-slate-300 bg-white px-2 py-0.5 text-[11px] text-slate-700 hover:bg-slate-50"
      >
        {t.reportView}
      </button>
      <button
        type="button"
        onClick={() => downloadReportPdf(jobId)}
        className="rounded border border-slate-300 bg-white px-2 py-0.5 text-[11px] text-slate-700 hover:bg-slate-50"
      >
        {t.reportDownloadPdf}
      </button>
    </div>
  );
}

/** @param {{ job: import("./client.js").MlRetrainJobT }} props */
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

  return (
    <div className="mt-3 space-y-2 text-xs">
      <div className="flex items-center gap-2">
        <span
          className={`rounded px-2 py-0.5 text-[11px] font-medium ${badgeClass}`}
        >
          {statusLabel}
        </span>
        {job.status === "succeeded" && (
          <span className="text-slate-600">{t.summary(job.rows_trained)}</span>
        )}
        {job.status === "succeeded" &&
          typeof job.metrics?.promoted === "boolean" && (
            <PromotionBadge promoted={job.metrics.promoted} />
          )}
        {isDone && job.report_dir && <ReportActions jobId={job.id} />}
      </div>

      {job.status === "succeeded" &&
        job.metrics?.promoted === false &&
        typeof job.metrics?.promotion_reason === "string" && (
          <div className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] text-amber-800">
            {t.promotionReasonLabel}: {job.metrics.promotion_reason}
          </div>
        )}

      {job.error_text && (
        <details className="rounded border border-red-200 bg-red-50 px-3 py-2">
          <summary className="cursor-pointer font-medium text-red-800">
            {t.statusFailed}
          </summary>
          <pre className="mt-2 whitespace-pre-wrap break-all text-[11px] text-red-700">
            {job.error_text}
          </pre>
        </details>
      )}

      {isDone && Object.keys(job.metrics).length > 0 && (
        <details
          open
          className="rounded border border-slate-200 bg-slate-50 px-3 py-2"
        >
          <summary className="cursor-pointer font-medium text-slate-700">
            {t.metricsHeading}
          </summary>
          <TestMetricsBlock test={job.metrics?.test} />
          <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-[11px]">
            {Object.entries(job.metrics)
              .filter(([k, v]) => {
                // promoted/promotion_reason đã hiển thị bằng badge riêng.
                if (k === "promoted" || k === "promotion_reason") return false;
                return typeof v !== "object" || v === null;
              })
              .map(([k, v]) => (
                <MetricRow key={k} k={k} v={v} />
              ))}
            {job.artifact_path && (
              <>
                <span className="text-slate-500">{t.artifactLabel}</span>
                <span className="break-all font-mono text-slate-700">
                  {job.artifact_path}
                </span>
              </>
            )}
          </div>
        </details>
      )}
    </div>
  );
}

/** @param {{ test: any }} props */
function TestMetricsBlock({ test }) {
  if (!test || typeof test !== "object") return null;
  const fmt = (v, digits = 2) =>
    typeof v === "number" ? v.toFixed(digits) : "—";
  const sign = (v) =>
    typeof v === "number" ? `${v >= 0 ? "+" : ""}${v.toFixed(2)}` : "—";
  return (
    <div className="mt-2 rounded border border-emerald-200 bg-emerald-50 px-3 py-2">
      <div className="mb-1 text-[11px] font-semibold text-emerald-900">
        {t.testMetricsHeading}
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[11px]">
        <span className="text-emerald-800">{t.testRmse}</span>
        <span className="font-mono text-emerald-900">{fmt(test.rmse_db)}</span>
        <span className="text-emerald-800">{t.testMae}</span>
        <span className="font-mono text-emerald-900">{fmt(test.mae_db)}</span>
        <span className="text-emerald-800">{t.testR2}</span>
        <span className="font-mono text-emerald-900">{fmt(test.r2, 4)}</span>
        <span className="text-emerald-800">{t.testBias}</span>
        <span className="font-mono text-emerald-900">{sign(test.bias_db)}</span>
        <span className="text-emerald-800">{t.testN}</span>
        <span className="font-mono text-emerald-900">
          {typeof test.n === "number" ? test.n.toLocaleString("vi-VN") : "—"}
        </span>
      </div>
    </div>
  );
}

/** @param {{ k: string, v: any }} props */
function MetricRow({ k, v }) {
  const label = t.metricsLabel[k] ?? k;
  const display =
    typeof v === "number"
      ? Number.isInteger(v)
        ? v.toLocaleString("vi-VN")
        : v.toFixed(3)
      : String(v);
  return (
    <>
      <span className="text-slate-500">{label}</span>
      <span className="font-mono text-slate-700">{display}</span>
    </>
  );
}

/** @param {{ query: import("@tanstack/react-query").UseQueryResult<import("./client.js").MlRetrainJobListT> }} props */
function HistoryView({ query }) {
  if (!query.data) return null;
  if (query.data.items.length === 0) {
    return (
      <div className="mt-4 text-xs text-slate-500">
        <div className="mb-1 font-medium text-slate-700">
          {t.historyHeading}
        </div>
        <div>{t.historyEmpty}</div>
      </div>
    );
  }
  return (
    <div className="mt-4 text-xs">
      <div className="mb-1 font-medium text-slate-700">{t.historyHeading}</div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[480px]">
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
            {query.data.items.map((j) => {
              const test = j.metrics?.test;
              const num2 = (x) => (typeof x === "number" ? x.toFixed(2) : "");
              const num4 = (x) => (typeof x === "number" ? x.toFixed(4) : "");
              const bias = (x) =>
                typeof x === "number" ? `${x >= 0 ? "+" : ""}${x.toFixed(2)}` : "";
              return (
                <tr key={j.id} className="border-t border-slate-200">
                  <td className="py-1 pr-2 text-slate-600">
                    {new Date(j.triggered_at).toLocaleString("vi-VN")}
                  </td>
                  <td className="py-1 pr-2 text-slate-600">
                    {j.finished_at
                      ? new Date(j.finished_at).toLocaleString("vi-VN")
                      : "—"}
                  </td>
                  <td className="py-1 pr-2">
                    <StatusBadge status={j.status} />
                  </td>
                  <td className="py-1 pr-2 text-slate-700">
                    {j.rows_trained ?? ""}
                  </td>
                  <td className="py-1 pr-2 font-mono text-slate-700">
                    {num2(test?.rmse_db)}
                  </td>
                  <td className="py-1 pr-2 font-mono text-slate-700">
                    {num2(test?.mae_db)}
                  </td>
                  <td className="py-1 pr-2 font-mono text-slate-700">
                    {num4(test?.r2)}
                  </td>
                  <td className="py-1 pr-2 font-mono text-slate-700">
                    {bias(test?.bias_db)}
                  </td>
                  <td className="py-1 pr-2">
                    {j.report_dir ? (
                      <ReportActions jobId={j.id} />
                    ) : (
                      <span className="text-slate-400">{t.reportEmpty}</span>
                    )}
                  </td>
                  <td className="py-1 pr-2 text-red-700">
                    {j.error_text ? j.error_text.split("\n")[0].slice(0, 80) : ""}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** @param {{ promoted: boolean }} props */
function PromotionBadge({ promoted }) {
  const cls = promoted
    ? "bg-emerald-100 text-emerald-700"
    : "bg-amber-100 text-amber-800";
  return (
    <span className={`rounded px-2 py-0.5 text-[11px] font-medium ${cls}`}>
      {promoted ? t.promotedYes : t.promotedNo}
    </span>
  );
}

/** @param {{ status: import("./client.js").MlRetrainJobT["status"] }} props */
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
function RetrainError({ error }) {
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
