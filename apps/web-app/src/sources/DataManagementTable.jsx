// @ts-check
// Bảng "Quản lý dữ liệu" — list batch còn sống (chưa xoá), 2 nút Đóng góp + Xoá.
// Email-verification gate cho nút Đóng góp: mở EmailVerifyModal nếu user chưa verify.

import { useState, useSyncExternalStore } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../auth/client.js";
import { EmailVerifyModal } from "../auth/EmailVerifyModal.jsx";
import { getUser, subscribe } from "../auth/store.js";
import {
  deleteUploadBatch,
  listUploadBatches,
  submitUploadBatch,
} from "./client.js";
import { ConfirmModal } from "../components/Modal.jsx";
import { strings } from "../strings.js";

const t = strings.dataManagementTable;
const tKind = strings.uploadKindLabel;
const tStatus = strings.batchStatusLabel;

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

export function DataManagementTable() {
  const qc = useQueryClient();
  const user = useSyncExternalStore(subscribe, getUser);
  const [verifyOpen, setVerifyOpen] = useState(false);
  // Confirm modal cho xoá batch — lưu cả id + points_count để hiển thị
  // nội dung "Xoá batch này (N điểm)?".
  const [confirmDel, setConfirmDel] = useState(
    /** @type {{ id: string, points: number } | null} */ (null),
  );

  const qBatches = useQuery({
    queryKey: ["upload-batches", "active"],
    queryFn: () => listUploadBatches({ includeDeleted: false }),
  });

  const invalidateAll = () => {
    qc.invalidateQueries({ queryKey: ["upload-batches"] });
    qc.invalidateQueries({ queryKey: ["upload-overview"] });
    qc.invalidateQueries({ queryKey: ["surveys"] });
  };

  const submitM = useMutation({
    mutationFn: submitUploadBatch,
    onSuccess: invalidateAll,
  });

  const delM = useMutation({
    mutationFn: deleteUploadBatch,
    onSuccess: invalidateAll,
  });

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <h3 className="text-base font-semibold text-slate-900">{t.title}</h3>
      <p className="mt-1 text-sm text-slate-600">{t.subtitle}</p>

      {submitM.isSuccess && submitM.data && (
        <div
          role="status"
          className="mt-3 rounded-md border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-900"
        >
          <div className="font-semibold">{t.successTitle}</div>
          <div className="mt-1">{t.successLine(submitM.data.queued)}</div>
        </div>
      )}

      {submitM.isError && (
        <div
          role="alert"
          className="mt-3 rounded-md border border-red-300 bg-red-50 p-3 text-xs text-red-800"
        >
          <div className="font-semibold">{t.errorTitle}</div>
          <div className="mt-1">
            {submitM.error instanceof ApiError
              ? submitM.error.problem.detail || submitM.error.problem.title
              : String(submitM.error)}
          </div>
          {submitM.error instanceof ApiError &&
            submitM.error.problem.code === "email_not_verified" && (
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

      {confirmDel && (
        <ConfirmModal
          title={t.btnDelete}
          body={t.confirmDelete(confirmDel.points)}
          confirmLabel={t.btnDelete}
          danger
          onConfirm={() => {
            const id = confirmDel.id;
            setConfirmDel(null);
            delM.mutate(id);
          }}
          onCancel={() => setConfirmDel(null)}
        />
      )}

      {qBatches.isPending && (
        <p className="mt-3 text-xs text-slate-500">{t.loading}</p>
      )}

      {qBatches.isError && (
        <p className="mt-3 text-xs text-red-700">{t.errorLoad}</p>
      )}

      {qBatches.data && qBatches.data.length === 0 && (
        <p className="mt-3 text-xs text-slate-500">{t.empty}</p>
      )}

      {qBatches.data && qBatches.data.length > 0 && (
        <div className="mt-3 overflow-x-auto">
          <table className="min-w-full text-xs">
            <thead>
              <tr className="border-b border-slate-200 text-left text-slate-600">
                <th className="py-1.5 pr-3 font-medium">{t.headers[0]}</th>
                <th className="py-1.5 pr-3 font-medium">{t.headers[1]}</th>
                <th className="py-1.5 pr-3 text-right font-medium">
                  {t.headers[2]}
                </th>
                <th className="py-1.5 pr-3 font-medium">{t.headers[3]}</th>
                <th className="py-1.5 pr-3 font-medium">{t.headers[4]}</th>
                <th className="py-1.5 text-right font-medium">
                  {t.headers[5]}
                </th>
              </tr>
            </thead>
            <tbody>
              {qBatches.data.map((batch) => {
                const isSubmittingThis =
                  submitM.isPending && submitM.variables === batch.id;
                const isDeletingThis =
                  delM.isPending && delM.variables === batch.id;
                const canSubmit = batch.status === "private";
                return (
                  <tr
                    key={batch.id}
                    className="border-b border-slate-100 text-slate-700"
                  >
                    <td className="py-1.5 pr-3 whitespace-nowrap">
                      {formatTs(batch.uploaded_at)}
                    </td>
                    <td className="py-1.5 pr-3 max-w-[200px] truncate" title={batch.filename}>
                      {batch.filename}
                    </td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">
                      {batch.points_count}
                    </td>
                    <td className="py-1.5 pr-3">{tKind[batch.kind]}</td>
                    <td className="py-1.5 pr-3">
                      <span className={_statusClass(batch.status)}>
                        {tStatus[batch.status]}
                      </span>
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
                            submitM.mutate(batch.id);
                          }}
                          disabled={!canSubmit || isSubmittingThis}
                          className={
                            canSubmit
                              ? "rounded-md bg-emerald-700 px-2 py-1 text-white hover:bg-emerald-800 disabled:bg-slate-300 disabled:text-slate-600"
                              : "rounded-md border border-slate-200 px-2 py-1 text-slate-400"
                          }
                        >
                          {isSubmittingThis
                            ? t.btnContributePending
                            : t.btnContribute}
                        </button>
                        <button
                          type="button"
                          onClick={() =>
                            setConfirmDel({
                              id: batch.id,
                              points: batch.points_count,
                            })
                          }
                          disabled={isDeletingThis}
                          className="rounded-md border border-rose-300 px-2 py-1 text-rose-700 hover:bg-rose-50 disabled:opacity-50"
                        >
                          {isDeletingThis ? t.btnDeletePending : t.btnDelete}
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
          <div className="font-semibold">{t.deleteErrorTitle}</div>
          <div className="mt-1">
            {delM.error instanceof ApiError
              ? delM.error.problem.detail || delM.error.problem.title
              : String(delM.error)}
          </div>
        </div>
      )}
    </section>
  );
}

/** @param {"private"|"pending"|"public"|"rejected"|"deleted"} status */
function _statusClass(status) {
  switch (status) {
    case "private":
      return "rounded-full bg-slate-100 px-2 py-0.5 text-slate-700";
    case "pending":
      return "rounded-full bg-sky-100 px-2 py-0.5 text-sky-800";
    case "public":
      return "rounded-full bg-emerald-100 px-2 py-0.5 text-emerald-800";
    case "rejected":
      return "rounded-full bg-rose-100 px-2 py-0.5 text-rose-800";
    case "deleted":
      return "rounded-full bg-slate-100 px-2 py-0.5 text-slate-500 line-through";
    default:
      return "";
  }
}
