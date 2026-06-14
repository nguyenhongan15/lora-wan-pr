// @ts-check
// TrainingBatchesPanel — admin trace-back data đã duyệt vào ts.survey_training.
//
// Flow:
//   1. List batch có ≥1 row trong training (mig 0024+).
//   2. Admin click "Xoá khỏi training" → confirm modal → DELETE batch.
//   3. Sau khi xoá thành công → auto-popup hỏi "Chạy Rebuild + Retrain ngay?"
//      với 4 option: cả 2 / chỉ rebuild / chỉ retrain / để sau.
//
// Backend chi tiết xem services/api-service/.../routers/admin.py
// (`/admin/training/batches`).

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../auth/client.js";
import {
  deleteTrainingBatch,
  enqueueCoverageRebuild,
  enqueueMlRetrain,
  listTrainingBatches,
} from "./client.js";
import { strings } from "../strings.js";

const t = strings.admin.training;
const tErr = strings.admin.errors;

export function TrainingBatchesPanel() {
  const qc = useQueryClient();
  const [pendingDelete, setPendingDelete] = useState(
    /** @type {import("./client.js").TrainingBatchItemT | null} */ (null),
  );
  const [followUp, setFollowUp] = useState(
    /** @type {{ deletedCount: number } | null} */ (null),
  );
  const [toast, setToast] = useState(/** @type {string | null} */ (null));

  const listQ = useQuery({
    queryKey: ["admin", "training", "batches"],
    queryFn: listTrainingBatches,
  });

  const deleteM = useMutation({
    mutationFn: (/** @type {string} */ batchId) => deleteTrainingBatch(batchId),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["admin", "training", "batches"] });
      setPendingDelete(null);
      setFollowUp({ deletedCount: data.deleted_count });
      setToast(t.deletedToast(data.deleted_count));
      window.setTimeout(() => setToast(null), 3500);
    },
  });

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <header className="mb-3">
        <h3 className="text-sm font-semibold text-slate-900">{t.title}</h3>
        <p className="mt-1 text-xs text-slate-500">{t.subtitle}</p>
      </header>

      {toast && (
        <div className="mb-3 rounded bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
          {toast}
        </div>
      )}

      <BatchTable
        query={listQ}
        onDelete={(item) => setPendingDelete(item)}
      />

      <p className="mt-3 text-[11px] text-slate-500">{t.legacyHint}</p>

      {pendingDelete && (
        <ConfirmDeleteModal
          item={pendingDelete}
          isPending={deleteM.isPending}
          error={deleteM.error}
          onCancel={() => {
            setPendingDelete(null);
            deleteM.reset();
          }}
          onConfirm={() => deleteM.mutate(pendingDelete.batch_id)}
        />
      )}

      {followUp && (
        <FollowUpModal
          deletedCount={followUp.deletedCount}
          onClose={() => setFollowUp(null)}
        />
      )}
    </section>
  );
}

/** @param {{ query: import("@tanstack/react-query").UseQueryResult<import("./client.js").TrainingBatchListT>, onDelete: (item: import("./client.js").TrainingBatchItemT) => void }} props */
function BatchTable({ query, onDelete }) {
  if (query.isLoading) {
    return <div className="text-xs text-slate-500">{t.loading}</div>;
  }
  if (query.isError) {
    return <div className="text-xs text-red-700">{t.errorLoad}</div>;
  }
  if (!query.data || query.data.items.length === 0) {
    return <div className="text-xs text-slate-500">{t.empty}</div>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] text-xs">
        <thead className="text-left text-[11px] text-slate-500">
          <tr>
            {t.headers.map((h) => (
              <th key={h} className="py-1 pr-3 font-normal">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {query.data.items.map((item) => (
            <BatchRow key={item.batch_id} item={item} onDelete={onDelete} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** @param {{ item: import("./client.js").TrainingBatchItemT, onDelete: (item: import("./client.js").TrainingBatchItemT) => void }} props */
function BatchRow({ item, onDelete }) {
  const kindLabel = item.kind ? t.kindLabel[item.kind] : t.kindUnknown;
  const uploadedAt = item.uploaded_at
    ? new Date(item.uploaded_at).toLocaleString("vi-VN")
    : "—";
  const approvedAt = new Date(item.latest_approved_at).toLocaleString("vi-VN");
  const deleted = !!item.batch_deleted_at;
  const roleKey = item.uploader_is_super_admin
    ? "super_admin"
    : item.uploader_is_admin
      ? "admin"
      : "user";
  const roleBadgeClass =
    roleKey === "super_admin"
      ? "bg-violet-100 text-violet-800"
      : roleKey === "admin"
        ? "bg-sky-100 text-sky-800"
        : "bg-slate-100 text-slate-700";
  return (
    <tr className="border-t border-slate-200">
      <td className="py-1 pr-3 text-slate-700">{item.uploader_email ?? "—"}</td>
      <td className="py-1 pr-3">
        <span
          className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-medium ${roleBadgeClass}`}
        >
          {t.roleLabel[roleKey]}
        </span>
      </td>
      <td className="py-1 pr-3 text-slate-700">{kindLabel}</td>
      <td className="py-1 pr-3 text-slate-700">
        {item.filename ?? "—"}
        {deleted && (
          <span className="ml-1 rounded bg-amber-100 px-1 text-[10px] text-amber-800">
            batch đã xoá
          </span>
        )}
      </td>
      <td className="py-1 pr-3 text-slate-600">{uploadedAt}</td>
      <td className="py-1 pr-3 text-slate-700">
        {item.promoted_count.toLocaleString("vi-VN")}
      </td>
      <td className="py-1 pr-3 text-slate-600">{approvedAt}</td>
      <td className="py-1 pr-3 text-right">
        <button
          type="button"
          onClick={() => onDelete(item)}
          className="rounded border border-red-300 px-2 py-1 text-[11px] font-medium text-red-700 hover:bg-red-50"
        >
          {t.btnDelete}
        </button>
      </td>
    </tr>
  );
}

/** @param {{ item: import("./client.js").TrainingBatchItemT, isPending: boolean, error: unknown, onCancel: () => void, onConfirm: () => void }} props */
function ConfirmDeleteModal({ item, isPending, error, onCancel, onConfirm }) {
  const who = item.uploader_email ?? "—";
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
      role="dialog"
      aria-modal="true"
      onClick={onCancel}
    >
      <div
        className="w-full max-w-md rounded-lg border border-slate-200 bg-white p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h4 className="text-base font-semibold text-slate-900">
          {t.confirm.title}
        </h4>
        <p className="mt-2 text-sm text-slate-700">
          {t.confirm.message(who, item.promoted_count)}
        </p>

        {error instanceof ApiError && (
          <div className="mt-3 rounded border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-800">
            {tErr.byCode(error.problem.code ?? "") ||
              error.problem.detail ||
              t.errorDelete}
          </div>
        )}

        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={isPending}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-100 disabled:opacity-50"
          >
            {t.confirm.cancel}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={isPending}
            className="rounded-md bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:bg-slate-400"
          >
            {isPending ? t.btnPending : t.confirm.confirm}
          </button>
        </div>
      </div>
    </div>
  );
}

/** @param {{ deletedCount: number, onClose: () => void }} props */
function FollowUpModal({ deletedCount, onClose }) {
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [err, setErr] = useState(/** @type {string | null} */ (null));

  /**
   * @param {{ rebuild: boolean, retrain: boolean }} opts
   */
  async function fire({ rebuild, retrain }) {
    setBusy(true);
    setErr(null);
    try {
      if (rebuild) await enqueueCoverageRebuild();
      if (retrain) await enqueueMlRetrain();
      setDone(true);
      window.setTimeout(onClose, 1800);
    } catch (e) {
      setErr(e instanceof ApiError ? e.problem.detail ?? null : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
      role="dialog"
      aria-modal="true"
      onClick={busy ? undefined : onClose}
    >
      <div
        className="w-full max-w-md rounded-lg border border-slate-200 bg-white p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h4 className="text-base font-semibold text-slate-900">
          {t.followUp.title}
        </h4>
        <p className="mt-2 text-sm text-slate-700">
          {t.followUp.message(deletedCount)}
        </p>

        {done && (
          <div className="mt-3 rounded bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
            {t.followUp.enqueuedToast}
          </div>
        )}
        {err && (
          <div className="mt-3 rounded border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-800">
            {err}
          </div>
        )}

        <div className="mt-5 flex flex-wrap justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-100 disabled:opacity-50"
          >
            {t.followUp.skip}
          </button>
          <button
            type="button"
            onClick={() => fire({ rebuild: true, retrain: false })}
            disabled={busy || done}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-100 disabled:opacity-50"
          >
            {t.followUp.runRebuildOnly}
          </button>
          <button
            type="button"
            onClick={() => fire({ rebuild: false, retrain: true })}
            disabled={busy || done}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-100 disabled:opacity-50"
          >
            {t.followUp.runRetrainOnly}
          </button>
          <button
            type="button"
            onClick={() => fire({ rebuild: true, retrain: true })}
            disabled={busy || done}
            className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
          >
            {t.followUp.runBoth}
          </button>
        </div>
      </div>
    </div>
  );
}
