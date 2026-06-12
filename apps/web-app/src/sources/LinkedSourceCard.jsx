// @ts-check
// LinkedSourceCard — 1 card per linked source.
//
// Refactor 2026-06-11: contribute_to_community bỏ hẳn. Sync luôn vào batch
// private; user opt-in cộng đồng từ bảng "Quản lý dữ liệu" cho từng batch.
//
// Toggle còn lại: status (active/paused) — kỹ thuật, có pull data về DB không.
// Invalidate ["surveys"] sau sync vì batch mới có thể đã được pre-submit từ
// trước (admin-approved → public) → map cần refresh.

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../auth/client.js";
import {
  patchSource,
  rotateWebhook,
  syncSource,
  unlinkSource,
} from "./client.js";
import { DevicesPanel } from "./DevicesPanel.jsx";
import { WebhookSetupInstructions } from "./WebhookSetupInstructions.jsx";
import { AlertModal, ConfirmModal } from "../components/Modal.jsx";
import { strings } from "../strings.js";

const tCard = strings.sources.card;
const tErr = strings.sources.errors;

// Mirror của `_CONFLICTING_SOURCE_PAIRS` ở backend
// (services/api-service/.../linking/service.py). ChirpStack ↔ LPWANMapper
// chung 1 uplink physic, mở song song = double-insert quarantine.
// Thêm pair mới ở đây phải sync cả hai phía.
/** @type {Record<string, ReadonlyArray<string>>} */
const SYNC_CONFLICT_PAIRS = {
  chirpstack: ["lpwanmapper"],
  lpwanmapper: ["chirpstack"],
};

/**
 * Tìm nguồn khác đang active mà conflict với `source`. Trả null nếu không có.
 * @param {import("./client.js").LinkedSourceT} source
 * @param {ReadonlyArray<import("./client.js").LinkedSourceT>} allSources
 */
function findActiveConflict(source, allSources) {
  const conflicts = SYNC_CONFLICT_PAIRS[source.source_type];
  if (!conflicts || conflicts.length === 0) return null;
  for (const other of allSources) {
    if (other.id === source.id) continue;
    if (other.status !== "active") continue;
    if (conflicts.includes(other.source_type)) return other;
  }
  return null;
}

/**
 * @param {{
 *   source: import("./client.js").LinkedSourceT,
 *   allSources?: ReadonlyArray<import("./client.js").LinkedSourceT>,
 * }} props
 */
export function LinkedSourceCard({ source, allSources = [] }) {
  const qc = useQueryClient();
  const invalidate = () =>
    qc.invalidateQueries({ queryKey: ["sources"] });
  const invalidateSurveys = () =>
    qc.invalidateQueries({ queryKey: ["surveys"] });
  const invalidateDevices = () =>
    qc.invalidateQueries({ queryKey: ["devices", source.id] });
  const invalidateBatches = () =>
    qc.invalidateQueries({ queryKey: ["upload-batches"] });

  const [showDevices, setShowDevices] = useState(false);
  // Plaintext webhook token sau rotate — show-once. State scope = card,
  // dismiss → biến mất, không persist.
  const [rotatedSecret, setRotatedSecret] = useState(
    /** @type {{ url: string, token: string } | null} */ (null),
  );
  // Modal warning khi user bấm "Tải dữ liệu" mà có conflict pair active.
  // Lưu label + type của nguồn đối thủ để hiển thị trong nội dung modal.
  const [conflictModal, setConflictModal] = useState(
    /** @type {{ label: string, type: string } | null} */ (null),
  );
  // Confirm modals (thay window.confirm).
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [confirmRotateOpen, setConfirmRotateOpen] = useState(false);

  const isChirpstack = source.source_type === "chirpstack";

  const statusM = useMutation({
    mutationFn: (/** @type {"active" | "paused"} */ status) =>
      patchSource(source.id, { status }),
    onSuccess: invalidate,
  });

  const syncM = useMutation({
    mutationFn: () => syncSource(source.id),
    onSuccess: () => {
      invalidate();
      invalidateSurveys();
      invalidateDevices();
      invalidateBatches();
    },
  });

  const deleteM = useMutation({
    mutationFn: () => unlinkSource(source.id),
    onSuccess: invalidate,
  });

  const rotateM = useMutation({
    mutationFn: () => rotateWebhook(source.id),
    onSuccess: (resp) => {
      setRotatedSecret({ url: resp.webhook_url, token: resp.webhook_token });
      invalidate();
    },
  });

  function onDelete() {
    setConfirmDeleteOpen(true);
  }

  function onRotate() {
    setConfirmRotateOpen(true);
  }

  function onSync() {
    const other = findActiveConflict(source, allSources);
    if (other) {
      setConflictModal({ label: other.label, type: other.source_type });
      return;
    }
    syncM.mutate();
  }

  const lastSyncErr = source.last_sync_error;
  const anyPending =
    statusM.isPending ||
    syncM.isPending ||
    deleteM.isPending ||
    rotateM.isPending;

  return (
    <article className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <header className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold text-slate-900">
            {source.label}
          </h3>
          <p className="text-xs text-slate-500">{source.source_type}</p>
        </div>
        <StatusBadge status={source.status} />
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
              syncM.data.devices_inserted + syncM.data.devices_updated,
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
          onClick={onSync}
          disabled={anyPending || source.status !== "active"}
          title={
            source.status === "paused"
              ? tCard.btnSyncDisabledPaused
              : source.status === "failed"
                ? tCard.btnSyncDisabledFailed
                : undefined
          }
          className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 shadow-sm hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {syncM.isPending ? tCard.btnSyncPending : tCard.btnSyncNow}
        </button>

        {isChirpstack && (
          <>
            <button
              type="button"
              onClick={onRotate}
              disabled={anyPending}
              className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 shadow-sm hover:bg-slate-100 disabled:opacity-50"
            >
              {rotateM.isPending
                ? tCard.btnRotateWebhookPending
                : tCard.btnRotateWebhook}
            </button>
            <button
              type="button"
              onClick={() => setShowDevices((v) => !v)}
              disabled={anyPending}
              className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 shadow-sm hover:bg-slate-100 disabled:opacity-50"
            >
              {showDevices ? tCard.btnHideDevices : tCard.btnShowDevices}
            </button>
          </>
        )}

        <button
          type="button"
          onClick={onDelete}
          disabled={anyPending}
          className="ml-auto rounded-md border border-red-300 px-3 py-1.5 text-xs font-medium text-red-700 shadow-sm hover:bg-red-50 disabled:opacity-50"
        >
          {tCard.btnDelete}
        </button>
      </div>

      {rotatedSecret && (
        <div className="mt-4">
          <WebhookSetupInstructions
            webhookUrl={rotatedSecret.url}
            webhookToken={rotatedSecret.token}
            onDismiss={() => setRotatedSecret(null)}
          />
        </div>
      )}

      {showDevices && isChirpstack && (
        <div className="mt-4">
          <DevicesPanel linkedSourceId={source.id} />
        </div>
      )}

      <CardError
        error={statusM.error || deleteM.error || rotateM.error}
      />

      {conflictModal && (
        <AlertModal
          title={tCard.syncConflictTitle}
          body={tCard.syncConflictBody(conflictModal.label, conflictModal.type)}
          dismissLabel={tCard.syncConflictDismiss}
          onClose={() => setConflictModal(null)}
        />
      )}

      {confirmDeleteOpen && (
        <ConfirmModal
          title={tCard.btnDelete}
          body={tCard.confirmDelete}
          confirmLabel={tCard.btnDelete}
          danger
          onConfirm={() => {
            setConfirmDeleteOpen(false);
            deleteM.mutate();
          }}
          onCancel={() => setConfirmDeleteOpen(false)}
        />
      )}

      {confirmRotateOpen && (
        <ConfirmModal
          title={tCard.btnRotateWebhook}
          body={tCard.confirmRotateWebhook}
          confirmLabel={tCard.btnRotateWebhook}
          danger
          onConfirm={() => {
            setConfirmRotateOpen(false);
            rotateM.mutate();
          }}
          onCancel={() => setConfirmRotateOpen(false)}
        />
      )}
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
    const localized =
      tErr.byCode(code) || strings.auth.errors.byCode(code);
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
