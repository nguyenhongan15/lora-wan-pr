// @ts-check
// Global sync panel — button + report tóm tắt.
//
// Sync v1 synchronous (plan §3.4). Backend trả 200 KỂ CẢ KHI từng source
// fail (per-source error nằm trong items[].error). Caller cần đọc cả 2:
//   - HTTP error → ApiError (request fail toàn cục)
//   - report.failures > 0 → soft fail, hiện chi tiết
//
// Sau success: invalidate ['admin', 'stats'] (measurement_count thay đổi)
// + ['surveys'] (map points cập nhật) + ['sources'] (per-source last_sync).

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../auth/client.js";
import { globalSync } from "./client.js";
import { strings } from "../strings.js";

const t = strings.admin.sync;
const tErr = strings.admin.errors;

export function GlobalSyncPanel() {
  const qc = useQueryClient();

  const syncM = useMutation({
    mutationFn: globalSync,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "stats"] });
      qc.invalidateQueries({ queryKey: ["surveys"] });
      qc.invalidateQueries({ queryKey: ["sources"] });
    },
  });

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <header className="mb-3 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">{t.title}</h3>
          <p className="text-xs text-slate-500">{t.subtitle}</p>
        </div>
        <button
          type="button"
          onClick={() => syncM.mutate()}
          disabled={syncM.isPending}
          className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white shadow-sm hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
        >
          {syncM.isPending ? t.btnPending : t.btn}
        </button>
      </header>

      {syncM.isSuccess && <SyncReportView report={syncM.data} />}
      {syncM.isError && <SyncError error={syncM.error} />}
    </section>
  );
}

/** @param {{ report: import("./client.js").SyncReportT }} props */
function SyncReportView({ report }) {
  const failures = report.items.filter((r) => r.error !== null);
  return (
    <div className="space-y-2 text-xs">
      <div className="rounded bg-slate-50 px-3 py-2 text-slate-700">
        {t.summary(report.total, report.successes, report.failures)}
      </div>

      {failures.length > 0 && (
        <details className="rounded border border-red-200 bg-red-50 px-3 py-2">
          <summary className="cursor-pointer font-medium text-red-800">
            {t.failuresTitle(failures.length)}
          </summary>
          <ul className="mt-2 space-y-1 text-red-700">
            {failures.map((r) => (
              <li key={r.linked_source_id} className="font-mono text-[11px]">
                {r.linked_source_id}: {r.error}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

/** @param {{ error: unknown }} props */
function SyncError({ error }) {
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
      className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-800"
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
