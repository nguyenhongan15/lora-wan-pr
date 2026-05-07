// @ts-check
// LinkedSourceCard — 1 card per linked source.
//
// 2 toggle ĐỘC LẬP (plan §3.3):
//   - status (active/paused) — kỹ thuật, có pull data về DB hay không
//   - contribute_to_community — chính sách, data có lên bản đồ cộng đồng
//
// Mặc định sau link: status='active', contribute=false (privacy opt-in).
// Nút "Đóng góp cộng đồng" highlight (indigo) để hướng user opt-in.
//
// Auto-sync sau bật contribute (option (a), confirmed):
//   plan §5 Flow B step 8 yêu cầu BE trigger sync khi set_contribution(true)
//   nhưng implementation hiện tại chưa wire (LinkingService docstring nói
//   Step 7 sẽ thêm — chưa làm). Frontend tự gọi /sync sau PATCH success để
//   end-to-end Flow B làm việc, không cần sửa BE. Sync error không revert
//   toggle (toggle là chính sách, sync là kỹ thuật — 2 việc tách biệt).

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../auth/client.js";
import { patchSource, syncSource, unlinkSource } from "./client.js";
import { strings } from "../strings.js";

const tCard = strings.sources.card;
const tErr = strings.sources.errors;

/**
 * @param {{ source: import("./client.js").LinkedSourceT }} props
 */
export function LinkedSourceCard({ source }) {
  const qc = useQueryClient();
  const invalidate = () =>
    qc.invalidateQueries({ queryKey: ["sources"] });

  const contributeM = useMutation({
    mutationFn: async (/** @type {boolean} */ enabled) => {
      const updated = await patchSource(source.id, {
        contribute_to_community: enabled,
      });
      // Option (a): vừa bật contribute → tự sync để dữ liệu lên map ngay.
      // Sync error trả qua field `error` (HTTP 200 — plan §3.4) → caller
      // đọc trong syncM.data.error nếu cần. KHÔNG await để tránh block UI;
      // useMutation sync chạy sau khi invalidate xong.
      return { updated, autoSync: enabled };
    },
    onSuccess: ({ autoSync }) => {
      invalidate();
      if (autoSync) syncM.mutate();
    },
  });

  const statusM = useMutation({
    mutationFn: (/** @type {"active" | "paused"} */ status) =>
      patchSource(source.id, { status }),
    onSuccess: invalidate,
  });

  const syncM = useMutation({
    mutationFn: () => syncSource(source.id),
    onSuccess: invalidate,
  });

  const deleteM = useMutation({
    mutationFn: () => unlinkSource(source.id),
    onSuccess: invalidate,
  });

  function onDelete() {
    if (window.confirm(tCard.confirmDelete)) deleteM.mutate();
  }

  const lastSyncErr = source.last_sync_error;
  const anyPending =
    contributeM.isPending ||
    statusM.isPending ||
    syncM.isPending ||
    deleteM.isPending;

  return (
    <article className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <header className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold text-slate-900">
            {source.label}
          </h3>
          <p className="text-xs text-slate-500">{source.source_type}</p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <StatusBadge status={source.status} />
          <ContributeBadge on={source.contribute_to_community} />
        </div>
      </header>

      <dl className="mt-3 text-sm text-slate-600">
        <SyncMeta
          lastSyncAt={source.last_sync_at}
          lastSyncError={lastSyncErr}
        />
        {syncM.isSuccess && syncM.data?.error == null && (
          <div className="mt-2 rounded bg-green-50 px-2 py-1 text-xs text-green-700">
            {tCard.syncOk(
              syncM.data.gateways_inserted + syncM.data.gateways_updated,
              syncM.data.measurements_inserted,
            )}
          </div>
        )}
        {syncM.isSuccess && syncM.data?.error != null && (
          <div className="mt-2 rounded bg-red-50 px-2 py-1 text-xs text-red-700">
            {syncM.data.error}
          </div>
        )}
      </dl>

      <div className="mt-4 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => contributeM.mutate(!source.contribute_to_community)}
          disabled={anyPending}
          className={
            "rounded-md px-3 py-1.5 text-xs font-medium shadow-sm disabled:opacity-50 " +
            (source.contribute_to_community
              ? "border border-slate-300 text-slate-700 hover:bg-slate-100"
              : "bg-indigo-600 text-white hover:bg-indigo-500")
          }
        >
          {source.contribute_to_community
            ? tCard.btnContributeOff
            : tCard.btnContributeOn}
        </button>

        <button
          type="button"
          onClick={() =>
            statusM.mutate(source.status === "active" ? "paused" : "active")
          }
          disabled={anyPending || source.status === "failed"}
          className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 shadow-sm hover:bg-slate-100 disabled:opacity-50"
        >
          {source.status === "active" ? tCard.btnPause : tCard.btnResume}
        </button>

        <button
          type="button"
          onClick={() => syncM.mutate()}
          disabled={anyPending}
          className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 shadow-sm hover:bg-slate-100 disabled:opacity-50"
        >
          {syncM.isPending ? tCard.btnSyncPending : tCard.btnSyncNow}
        </button>

        <button
          type="button"
          onClick={onDelete}
          disabled={anyPending}
          className="ml-auto rounded-md border border-red-300 px-3 py-1.5 text-xs font-medium text-red-700 shadow-sm hover:bg-red-50 disabled:opacity-50"
        >
          {tCard.btnDelete}
        </button>
      </div>

      <CardError error={contributeM.error || statusM.error || deleteM.error} />
    </article>
  );
}

/** @param {{ status: "active" | "paused" | "failed" }} props */
function StatusBadge({ status }) {
  const map = {
    active: { cls: "bg-green-100 text-green-800", label: strings.sources.card.statusActive },
    paused: { cls: "bg-slate-100 text-slate-700", label: strings.sources.card.statusPaused },
    failed: { cls: "bg-red-100 text-red-800", label: strings.sources.card.statusFailed },
  };
  const { cls, label } = map[status];
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>
      {label}
    </span>
  );
}

/** @param {{ on: boolean }} props */
function ContributeBadge({ on }) {
  return (
    <span
      className={
        "rounded-full px-2 py-0.5 text-xs font-medium " +
        (on
          ? "bg-indigo-100 text-indigo-800"
          : "bg-amber-100 text-amber-800")
      }
    >
      {on ? tCard.contributeOn : tCard.contributeOff}
    </span>
  );
}

/** @param {{ lastSyncAt: string | null, lastSyncError: string | null }} props */
function SyncMeta({ lastSyncAt, lastSyncError }) {
  return (
    <div className="space-y-1">
      <div className="text-xs text-slate-500">
        {lastSyncAt
          ? tCard.lastSyncAt(formatRelative(lastSyncAt))
          : tCard.lastSyncNever}
      </div>
      {lastSyncError && (
        <div className="text-xs text-red-700">
          <span className="font-medium">{tCard.lastSyncError}</span>{" "}
          {lastSyncError}
        </div>
      )}
    </div>
  );
}

/** @param {{ error: unknown }} props */
function CardError({ error }) {
  if (!error) return null;
  if (error instanceof ApiError) {
    const code = error.problem.code ?? "";
    const localized = tErr.byCode(code);
    const msg = localized || error.problem.detail || error.problem.title;
    return (
      <div
        role="alert"
        className="mt-3 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-800"
      >
        {msg}
        {code && <span className="ml-2 text-red-600">({code})</span>}
      </div>
    );
  }
  return (
    <div
      role="alert"
      className="mt-3 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-800"
    >
      {String(error)}
    </div>
  );
}

// Relative time đơn giản — không kéo dayjs/luxon vì chỉ dùng 1 chỗ.
/** @param {string} iso */
function formatRelative(iso) {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return iso;
  const diffSec = Math.round((Date.now() - t) / 1000);
  if (diffSec < 60) return `${diffSec}s trước`;
  if (diffSec < 3600) return `${Math.round(diffSec / 60)} phút trước`;
  if (diffSec < 86400) return `${Math.round(diffSec / 3600)} giờ trước`;
  return new Date(iso).toLocaleString("vi-VN");
}
