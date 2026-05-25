// @ts-check
// Card "Dữ liệu CSV của tôi" — hiển thị backlog CSV upload của user + nút
// "Đóng góp" theo TỪNG file (1 batch = 1 lần upload). Mỗi row trong bảng
// có nút riêng để chạy TrustValidator chỉ trên rows của file đó — KHÔNG còn
// nút global gom mọi file lại.

import { useState, useSyncExternalStore } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../auth/client.js";
import { EmailVerifyModal } from "../auth/EmailVerifyModal.jsx";
import { getUser, subscribe } from "../auth/store.js";
import {
  deleteCsvUploadBatch,
  fetchCsvUploadStats,
  listCsvUploadBatches,
  promoteCsvBatch,
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
  const user = useSyncExternalStore(subscribe, getUser);
  const [verifyOpen, setVerifyOpen] = useState(false);
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

  // Mutation theo batch: variables = uploaded_at string (cùng key dùng để
  // disable nút đúng row đang chạy).
  const promoteM = useMutation({
    mutationFn: (/** @type {string} */ uploadedAt) => promoteCsvBatch(uploadedAt),
    onSuccess: invalidateAll,
  });

  const delM = useMutation({
    mutationFn: deleteCsvUploadBatch,
    onSuccess: invalidateAll,
  });

  const stats = q.data;
  const hasUpload = stats !== undefined && stats.total > 0;

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
          {stats.pending_review > 0 && (
            <li className="text-sky-700">
              • {t.stats.pendingReview(stats.pending_review)}
            </li>
          )}
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

      {promoteM.isSuccess && promoteM.data && (
        <div
          role="status"
          className="mt-3 rounded-md border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-900"
        >
          <div className="font-semibold">{t.successTitle}</div>
          <div className="mt-1">
            {t.successLine(
              promoteM.data.promoted_count,
              promoteM.data.promote_rejected_count,
            )}
          </div>
          {Object.keys(promoteM.data.promote_rejected_by_reason).length > 0 && (
            <>
              <div className="mt-2 font-semibold">{t.rejectBreakdownTitle}</div>
              <ul className="mt-1 list-disc pl-4">
                {Object.entries(promoteM.data.promote_rejected_by_reason).map(
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

      {promoteM.isError && (
        <div
          role="alert"
          className="mt-3 rounded-md border border-red-300 bg-red-50 p-3 text-xs text-red-800"
        >
          <div className="font-semibold">{t.errorTitle}</div>
          <div className="mt-1">
            {promoteM.error instanceof ApiError
              ? promoteM.error.problem.detail || promoteM.error.problem.title
              : String(promoteM.error)}
          </div>
          {promoteM.error instanceof ApiError &&
            promoteM.error.problem.code === "email_not_verified" && (
              <button
                type="button"
                onClick={() => setVerifyOpen(true)}
                className="mt-2 rounded-md border border-sky-300 bg-sky-50 px-3 py-1.5 text-xs font-medium text-sky-800 hover:bg-sky-100"
              >
                {strings.auth.header.verifyEmailButton}
              </button>
            )}
        </div>
      )}

      {user && (
        <EmailVerifyModal
          isOpen={verifyOpen}
          email={user.email}
          onClose={() => setVerifyOpen(false)}
          notice={strings.auth.errors.byCode("email_not_verified")}
        />
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
                    {tBatch.header.pendingReview}
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
                  const isPromotingThis =
                    promoteM.isPending &&
                    promoteM.variables === batch.uploaded_at;
                  const promoteState = _batchPromoteState(batch);
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
                      <td className="py-1.5 pr-3 text-right tabular-nums text-sky-700">
                        {batch.pending_review}
                      </td>
                      <td className="py-1.5 pr-3 text-right tabular-nums text-emerald-700">
                        {batch.promoted}
                      </td>
                      <td className="py-1.5 pr-3 text-right tabular-nums text-rose-700">
                        {batch.rejected}
                      </td>
                      <td className="py-1.5 text-right">
                        <div className="flex justify-end gap-1.5">
                          <button
                            type="button"
                            onClick={() => {
                              if (user && !user.email_verified) {
                                setVerifyOpen(true);
                                return;
                              }
                              promoteM.mutate(batch.uploaded_at);
                            }}
                            disabled={
                              promoteState.kind !== "active" || isPromotingThis
                            }
                            className={`rounded-md px-2 py-1 ${promoteState.className}`}
                          >
                            {isPromotingThis
                              ? tBatch.btnPromotePending
                              : promoteState.label}
                          </button>
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
                        </div>
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

/**
 * Quyết định label + style cho nút "Đóng góp" của 1 batch dựa trên status
 * tổng hợp các row. Thứ tự ưu tiên:
 *   1. Còn row pending (chưa qua auto-validate) → active emerald.
 *   2. Có row đang chờ admin duyệt → sky disabled.
 *   3. Có row đã được admin duyệt vào training → emerald nhạt disabled.
 *   4. Còn lại = mọi row đã bị loại (auto-reject hoặc admin reject) → rose.
 *
 * @param {{ pending: number, pending_review: number, promoted: number, rejected: number }} batch
 * @returns {{ kind: "active" | "pending_review" | "approved" | "rejected", label: string, className: string }}
 */
function _batchPromoteState(batch) {
  if (batch.pending > 0) {
    return {
      kind: "active",
      label: tBatch.btnPromote,
      className:
        "bg-emerald-700 text-white hover:bg-emerald-800 disabled:bg-slate-300 disabled:text-slate-600",
    };
  }
  if (batch.pending_review > 0) {
    return {
      kind: "pending_review",
      label: tBatch.btnPromotePendingReview,
      className: "bg-sky-100 text-sky-800 border border-sky-200",
    };
  }
  if (batch.promoted > 0) {
    return {
      kind: "approved",
      label: tBatch.btnPromoteApproved,
      className: "bg-emerald-50 text-emerald-800 border border-emerald-200",
    };
  }
  return {
    kind: "rejected",
    label: tBatch.btnPromoteRejected,
    className: "bg-rose-50 text-rose-800 border border-rose-200",
  };
}
