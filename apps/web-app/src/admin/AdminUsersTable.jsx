// @ts-check
// AdminUsersTable — list user + 2 toggle (is_admin, disabled) + confirm
// dialog cho cả hai.
//
// Self-protection (plan §3.5): backend trả 400 admin_self_modification nếu
// admin sửa chính mình. UI chặn sớm hơn — ẩn nút trên row của self thay vì
// dựa vào error recovery (UX > error message).
//
// Disabled = ẩn data thay vì xoá (plan §13 risk #11). UI dùng từ "Khoá" /
// "Mở khoá", KHÔNG dùng "Xoá".

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../auth/client.js";
import { listUsers, patchUser } from "./client.js";
import { strings } from "../strings.js";

const t = strings.admin.users;
const tErr = strings.admin.errors;

/** @typedef {import("./client.js").UserAdminT} UserAdminT */

/**
 * @typedef {{
 *   user: UserAdminT,
 *   field: "disabled" | "is_admin",
 *   nextValue: boolean,
 * }} PendingAction
 */

/**
 * @param {{ currentUserId: string }} props
 */
export function AdminUsersTable({ currentUserId }) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["admin", "users"],
    queryFn: listUsers,
  });

  const [pending, setPending] = useState(/** @type {PendingAction | null} */ (null));

  const patchM = useMutation({
    mutationFn: (
      /** @type {{ userId: string, body: import("./client.js").UserPatchRequestT }} */ args,
    ) => patchUser(args.userId, args.body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "users"] });
      qc.invalidateQueries({ queryKey: ["admin", "stats"] });
      setPending(null);
    },
  });

  function onConfirm() {
    if (!pending) return;
    patchM.mutate({
      userId: pending.user.id,
      body: { [pending.field]: pending.nextValue },
    });
  }

  function onCancel() {
    if (patchM.isPending) return;
    setPending(null);
    patchM.reset();
  }

  if (q.isPending) {
    return <div className="text-sm text-slate-500">{t.loading}</div>;
  }
  if (q.isError) {
    return <ListError error={q.error} />;
  }
  if (q.data.items.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-slate-300 bg-slate-50 p-6 text-center text-sm text-slate-600">
        {t.empty}
      </div>
    );
  }

  return (
    <>
      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
        <table className="min-w-full divide-y divide-slate-200 text-sm">
          <thead className="bg-slate-50">
            <tr>
              {t.headers.map((h) => (
                <th
                  key={h}
                  className="px-3 py-2 text-left text-xs font-medium uppercase tracking-wider text-slate-500"
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200">
            {q.data.items.map((u) => (
              <UserRow
                key={u.id}
                user={u}
                isSelf={u.id === currentUserId}
                onAction={(field, nextValue) =>
                  setPending({ user: u, field, nextValue })
                }
              />
            ))}
          </tbody>
        </table>
      </div>

      {pending && (
        <ConfirmModal
          pending={pending}
          isPending={patchM.isPending}
          error={patchM.error}
          onConfirm={onConfirm}
          onCancel={onCancel}
        />
      )}
    </>
  );
}

/**
 * @param {{
 *   user: UserAdminT,
 *   isSelf: boolean,
 *   onAction: (field: "disabled" | "is_admin", nextValue: boolean) => void,
 * }} props
 */
function UserRow({ user, isSelf, onAction }) {
  return (
    <tr className={user.disabled ? "bg-slate-50" : undefined}>
      <td className="px-3 py-2">
        <div className="flex items-center gap-2">
          <span className="font-medium text-slate-900">{user.email}</span>
          {isSelf && (
            <span className="rounded bg-slate-200 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-slate-700">
              {t.selfBadge}
            </span>
          )}
        </div>
      </td>
      <td className="px-3 py-2 text-right font-mono text-xs">
        {user.contribution_count}
      </td>
      <td className="px-3 py-2">
        {user.is_admin ? <AdminBadge /> : <span className="text-xs text-slate-400">—</span>}
      </td>
      <td className="px-3 py-2">
        {user.disabled ? <DisabledBadge /> : <ActiveBadge />}
      </td>
      <td className="px-3 py-2 font-mono text-xs text-slate-500">
        {formatDate(user.created_at)}
      </td>
      <td className="px-3 py-2 text-right">
        {isSelf ? (
          <span className="text-xs text-slate-400">{t.actionsSelfNote}</span>
        ) : (
          <div className="flex justify-end gap-1.5">
            <button
              type="button"
              onClick={() => onAction("is_admin", !user.is_admin)}
              className="rounded-md border border-slate-300 px-2 py-1 text-xs hover:bg-slate-100"
            >
              {user.is_admin ? t.btnDemote : t.btnPromote}
            </button>
            <button
              type="button"
              onClick={() => onAction("disabled", !user.disabled)}
              className={
                "rounded-md px-2 py-1 text-xs " +
                (user.disabled
                  ? "border border-emerald-300 text-emerald-700 hover:bg-emerald-50"
                  : "border border-red-300 text-red-700 hover:bg-red-50")
              }
            >
              {user.disabled ? t.btnEnable : t.btnDisable}
            </button>
          </div>
        )}
      </td>
    </tr>
  );
}

function AdminBadge() {
  return (
    <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-800">
      {t.adminBadge}
    </span>
  );
}

function ActiveBadge() {
  return (
    <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-800">
      {t.activeBadge}
    </span>
  );
}

function DisabledBadge() {
  return (
    <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-800">
      {t.disabledBadge}
    </span>
  );
}

/**
 * @param {{
 *   pending: PendingAction,
 *   isPending: boolean,
 *   error: unknown,
 *   onConfirm: () => void,
 *   onCancel: () => void,
 * }} props
 */
function ConfirmModal({ pending, isPending, error, onConfirm, onCancel }) {
  const { user, field, nextValue } = pending;
  const message =
    field === "disabled"
      ? nextValue
        ? t.confirm.disable(user.email)
        : t.confirm.enable(user.email)
      : nextValue
        ? t.confirm.promote(user.email)
        : t.confirm.demote(user.email);

  const confirmLabel =
    field === "disabled"
      ? nextValue
        ? t.btnDisable
        : t.btnEnable
      : nextValue
        ? t.btnPromote
        : t.btnDemote;

  const isDestructive =
    (field === "disabled" && nextValue) || (field === "is_admin" && nextValue);

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
        <h4 className="text-base font-semibold text-slate-900">{t.confirm.title}</h4>
        <p className="mt-2 text-sm text-slate-700">{message}</p>

        {error && <ConfirmError error={error} />}

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
            className={
              "rounded-md px-3 py-1.5 text-sm font-medium text-white shadow-sm disabled:opacity-50 " +
              (isDestructive
                ? "bg-red-600 hover:bg-red-500"
                : "bg-slate-900 hover:bg-slate-800")
            }
          >
            {isPending ? t.confirm.pending : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

/** @param {{ error: unknown }} props */
function ConfirmError({ error }) {
  let msg = t.confirm.errorGeneric;
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

/** @param {{ error: unknown }} props */
function ListError({ error }) {
  let msg = t.errorLoad;
  let code = "";
  if (error instanceof ApiError) {
    code = error.problem.code ?? "";
    const localized = tErr.byCode(code);
    msg = localized || error.problem.detail || error.problem.title || msg;
  }
  return (
    <div
      role="alert"
      className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800"
    >
      <div className="font-semibold">{msg}</div>
      {code && (
        <div className="mt-1 text-xs text-red-600">
          {tErr.errorCodeLabel}: {code}
        </div>
      )}
    </div>
  );
}

/** @param {string} iso */
function formatDate(iso) {
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) return iso;
  return dt.toLocaleDateString("vi-VN");
}
