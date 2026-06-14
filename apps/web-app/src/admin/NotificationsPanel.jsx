// @ts-check
// NotificationsPanel — nhắc admin chạy rebuild / retrain khi số điểm đo
// mới trong ts.survey_training vượt ngưỡng (mặc định backend = 100).
//
// Source-of-truth: GET /admin/notifications/data-freshness.
// 2 card song song (rebuild + retrain), mỗi card có nút enqueue tái dùng
// chính endpoint của tab "Bản đồ ước lượng" / "Mô hình ML". Sau khi enqueue
// thành công → invalidate query freshness + history để counts cập nhật.

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../auth/client.js";
import {
  enqueueCoverageRebuild,
  enqueueMlRetrain,
  getDataFreshness,
} from "./client.js";
import { strings } from "../strings.js";

const t = strings.admin.notifications;
const tErr = strings.admin.errors;

export function NotificationsPanel() {
  const qc = useQueryClient();
  const [toast, setToast] = useState(/** @type {string | null} */ (null));

  const q = useQuery({
    queryKey: ["admin", "notifications", "data-freshness"],
    queryFn: getDataFreshness,
    refetchInterval: 60000,
  });

  const rebuildM = useMutation({
    mutationFn: enqueueCoverageRebuild,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "notifications", "data-freshness"] });
      qc.invalidateQueries({ queryKey: ["admin", "coverage", "rebuild", "history"] });
      flashToast(t.enqueuedToast);
    },
  });

  const retrainM = useMutation({
    mutationFn: enqueueMlRetrain,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "notifications", "data-freshness"] });
      qc.invalidateQueries({ queryKey: ["admin", "ml", "retrain", "history"] });
      flashToast(t.enqueuedToast);
    },
  });

  /** @param {string} msg */
  function flashToast(msg) {
    setToast(msg);
    window.setTimeout(() => setToast(null), 3500);
  }

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

      {q.isPending && <div className="text-xs text-slate-500">{t.loading}</div>}
      {q.isError && <ErrorBox error={q.error} fallback={t.errorLoad} />}

      {q.data && (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <FreshnessCard
            title={t.rebuildCardTitle}
            newPoints={q.data.new_points_since_rebuild}
            threshold={q.data.threshold}
            lastRunAt={q.data.last_rebuild_finished_at}
            needsAction={q.data.needs_rebuild}
            buttonLabel={t.btnRebuild}
            isPending={rebuildM.isPending}
            error={rebuildM.error}
            onAction={() => rebuildM.mutate()}
          />
          <FreshnessCard
            title={t.retrainCardTitle}
            newPoints={q.data.new_points_since_retrain}
            threshold={q.data.threshold}
            lastRunAt={q.data.last_retrain_finished_at}
            needsAction={q.data.needs_retrain}
            buttonLabel={t.btnRetrain}
            isPending={retrainM.isPending}
            error={retrainM.error}
            onAction={() => retrainM.mutate()}
          />
        </div>
      )}
    </section>
  );
}

/**
 * @param {{
 *   title: string,
 *   newPoints: number,
 *   threshold: number,
 *   lastRunAt: string | null,
 *   needsAction: boolean,
 *   buttonLabel: string,
 *   isPending: boolean,
 *   error: unknown,
 *   onAction: () => void,
 * }} props
 */
function FreshnessCard({
  title,
  newPoints,
  threshold,
  lastRunAt,
  needsAction,
  buttonLabel,
  isPending,
  error,
  onAction,
}) {
  const tone = needsAction
    ? "border-amber-300 bg-amber-50"
    : "border-slate-200 bg-slate-50";
  return (
    <div className={`rounded-md border p-3 ${tone}`}>
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-600">
        {title}
      </div>
      <div className="mt-1 text-2xl font-bold text-slate-900">
        {newPoints.toLocaleString("vi-VN")}
      </div>
      <div className="text-[11px] text-slate-600">{t.newPoints(newPoints, threshold)}</div>
      <div className="mt-1 text-[11px] text-slate-500">
        {lastRunAt ? t.lastRunAt(lastRunAt) : t.lastRunNever}
      </div>
      <div
        className={`mt-2 rounded px-2 py-1 text-[11px] ${
          needsAction ? "bg-amber-100 text-amber-900" : "bg-slate-100 text-slate-700"
        }`}
      >
        {needsAction ? t.warnMessage : t.okMessage}
      </div>

      {error && <ErrorBox error={error} fallback={t.errorEnqueue} />}

      <div className="mt-3 text-right">
        <button
          type="button"
          onClick={onAction}
          disabled={isPending}
          className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white shadow-sm hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
        >
          {isPending ? t.btnPending : buttonLabel}
        </button>
      </div>
    </div>
  );
}

/** @param {{ error: unknown, fallback: string }} props */
function ErrorBox({ error, fallback }) {
  let msg = fallback;
  let code = "";
  if (error instanceof ApiError) {
    code = error.problem.code ?? "";
    const localized = tErr.byCode(code);
    msg = localized || error.problem.detail || error.problem.title || msg;
  }
  return (
    <div
      role="alert"
      className="mt-2 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-800"
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
