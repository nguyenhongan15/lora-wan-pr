// @ts-check
// Card "Dữ liệu CSV của tôi" — hiển thị backlog CSV upload của user + nút
// "Đóng góp cộng đồng" để chạy TrustValidator over toàn bộ rows pending.
//
// Tương tự LinkedSourceCard nhưng:
//   - 1 card duy nhất / user (CSV upload không có linked_source row riêng).
//   - Không có toggle on/off — promote là one-shot, rows đã promote ở training.
//   - Stats query qua GET /me/uploads/csv/stats; promote qua POST /promote.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../auth/client.js";
import {
  deleteCsvUploadBatch,
  fetchCsvUploadStats,
  listCsvUploadBatches,
  promoteCsvUploads,
} from "../api/client.js";
import { strings } from "../strings.js";

const t = strings.csvContributeCard;
const tBatch = strings.csvContributeCard.batches;
const tReason = strings.contributeUpload.rejectReasonLabel;

/** @param {string} key */
function labelReason(key) {
  return /** @type {Record<string, string>} */ (tReason)[key] ?? key;
}

/** @param {string} iso */
function formatTs(iso) {
  try {
    return new Date(iso).toLocaleString("vi-VN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export function CsvContributeCard() {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["csv-upload-stats"],
    queryFn: fetchCsvUploadStats,
  });
  const qBatches = useQuery({
    queryKey: ["csv-upload-batches"],
    queryFn: listCsvUploadBatches,
  });

  const invalidateAll = () => {
    qc.invalidateQueries({ queryKey: ["csv-upload-stats"] });
    qc.invalidateQueries({ queryKey: ["csv-upload-batches"] });
    qc.invalidateQueries({ queryKey: ["surveys"] });
  };

  const m = useMutation({
    mutationFn: promoteCsvUploads,
    onSuccess: invalidateAll,
  });

  const delM = useMutation({
    mutationFn: deleteCsvUploadBatch,
    onSuccess: invalidateAll,
  });

  const stats = q.data;
  const hasUpload = stats !== undefined && stats.total > 0;
  const canPromote = stats !== undefined && stats.pending > 0;

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <h3 className="text-base font-semibold text-slate-900">{t.title}</h3>
      <p className="mt-1 text-sm text-slate-600">{t.subtitle}</p>

      {q.isPending && (
        <p className="mt-3 text-sm text-slate-500">{t.loading}</p>
      )}

      {stats && (
        <ul className="mt-3 space-y-1 text-sm text-slate-700">
          <li>• {t.stats.total(stats.total)}</li>
          <li className="text-amber-700">• {t.stats.pending(stats.pending)}</li>
          {stats.promoted > 0 && (
            <li className="text-emerald-700">
              • {t.stats.promoted(stats.promoted)}
            </li>
          )}
          {stats.rejected > 0 && (
            <li className="text-rose-700">• {t.stats.rejected(stats.rejected)}</li>
          )}
        </ul>
      )}

      {stats && !hasUpload && (
        <p className="mt-3 text-xs text-slate-500">{t.emptyHint}</p>
      )}

      {stats && hasUpload && !canPromote && !m.isSuccess && (
        <p className="mt-3 text-xs text-slate-500">{t.nothingToPromote}</p>
      )}

      <div className="mt-4">
        <button
          type="button"
          onClick={() => m.mutate()}
          disabled={!canPromote || m.isPending}
          className="rounded-md bg-emerald-700 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-emerald-800 disabled:opacity-50"
        >
          {m.isPending ? t.btnPromotePending : t.btnPromote}
        </button>
      </div>

      {m.isSuccess && m.data && (
        <div
          role="status"
          className="mt-3 rounded-md border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-900"
        >
          <div className="font-semibold">{t.successTitle}</div>
          <div className="mt-1">
            {t.successLine(m.data.promoted_count, m.data.promote_rejected_count)}
          </div>
          {Object.keys(m.data.promote_rejected_by_reason).length > 0 && (
            <>
              <div className="mt-2 font-semibold">{t.rejectBreakdownTitle}</div>
              <ul className="mt-1 list-disc pl-4">
                {Object.entries(m.data.promote_rejected_by_reason).map(
                  ([reason, count]) => (
                    <li key={reason}>
                      {labelReason(reason)}: {count}
                    </li>
                  ),
                )}
              </ul>
            </>
          )}
        </div>
      )}

      {m.isError && (
        <div
          role="alert"
          className="mt-3 rounded-md border border-red-300 bg-red-50 p-3 text-xs text-red-800"
        >
          <div className="font-semibold">{t.errorTitle}</div>
          <div className="mt-1">
            {m.error instanceof ApiError
              ? m.error.problem.detail || m.error.problem.title
              : String(m.error)}
          </div>
        </div>
      )}

      <div className="mt-6 border-t border-slate-200 pt-4">
        <h4 className="text-sm font-semibold text-slate-900">{tBatch.title}</h4>

        {qBatches.isPending && (
          <p className="mt-2 text-xs text-slate-500">{tBatch.loading}</p>
        )}

        {qBatches.data && qBatches.data.length === 0 && (
          <p className="mt-2 text-xs text-slate-500">{tBatch.empty}</p>
        )}

        {qBatches.data && qBatches.data.length > 0 && (
          <div className="mt-2 overflow-x-auto">
            <table className="min-w-full text-xs">
              <thead>
                <tr className="border-b border-slate-200 text-left text-slate-600">
                  <th className="py-1.5 pr-3 font-medium">
                    {tBatch.header.uploadedAt}
                  </th>
                  <th className="py-1.5 pr-3 text-right font-medium">
                    {tBatch.header.total}
                  </th>
                  <th className="py-1.5 pr-3 text-right font-medium">
                    {tBatch.header.pending}
                  </th>
                  <th className="py-1.5 pr-3 text-right font-medium">
                    {tBatch.header.promoted}
                  </th>
                  <th className="py-1.5 pr-3 text-right font-medium">
                    {tBatch.header.rejected}
                  </th>
                  <th className="py-1.5 text-right font-medium">
                    {tBatch.header.actions}
                  </th>
                </tr>
              </thead>
              <tbody>
                {qBatches.data.map((batch) => {
                  const isDeletingThis =
                    delM.isPending && delM.variables === batch.uploaded_at;
                  return (
                    <tr
                      key={batch.uploaded_at}
                      className="border-b border-slate-100 text-slate-700"
                    >
                      <td className="py-1.5 pr-3">{formatTs(batch.uploaded_at)}</td>
                      <td className="py-1.5 pr-3 text-right tabular-nums">
                        {batch.total}
                      </td>
                      <td className="py-1.5 pr-3 text-right tabular-nums text-amber-700">
                        {batch.pending}
                      </td>
                      <td className="py-1.5 pr-3 text-right tabular-nums text-emerald-700">
                        {batch.promoted}
                      </td>
                      <td className="py-1.5 pr-3 text-right tabular-nums text-rose-700">
                        {batch.rejected}
                      </td>
                      <td className="py-1.5 text-right">
                        <button
                          type="button"
                          onClick={() => {
                            if (window.confirm(tBatch.confirmDelete(batch.total))) {
                              delM.mutate(batch.uploaded_at);
                            }
                          }}
                          disabled={isDeletingThis}
                          className="rounded-md border border-rose-300 px-2 py-1 text-rose-700 hover:bg-rose-50 disabled:opacity-50"
                        >
                          {isDeletingThis
                            ? tBatch.btnDeletePending
                            : tBatch.btnDelete}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {delM.isError && (
          <div
            role="alert"
            className="mt-3 rounded-md border border-red-300 bg-red-50 p-3 text-xs text-red-800"
          >
            <div className="font-semibold">{tBatch.deleteErrorTitle}</div>
            <div className="mt-1">
              {delM.error instanceof ApiError
                ? delM.error.problem.detail || delM.error.problem.title
                : String(delM.error)}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
