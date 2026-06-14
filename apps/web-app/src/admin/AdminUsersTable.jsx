// @ts-check
// AdminUsersTable — list user + 3 action: toggle is_admin, toggle disabled,
// hard-delete. Mỗi action confirm dialog.
//
// Self-protection (plan §3.5): backend trả 400 admin_self_modification cho
// patch + delete khi admin sửa chính mình. UI chặn sớm — ẩn mọi nút trên row
// của self (UX > error message).
//
// "Khoá" (disable) vs "Xoá" (delete):
//   * Khoá = soft, ẩn data khỏi map, reversible. Default cho ban user.
//   * Xoá = hard, DELETE auth.users; CASCADE xoá tokens/linked_sources, SET
//     NULL giữ contribution rows (data còn trên map nhưng mất link tới user).
//     Irreversible. Chỉ super admin gọi được.

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../auth/client.js";
import { deleteUser, listUsers, patchUser } from "./client.js";
import { strings } from "../strings.js";

const t = strings.admin.users;
const tErr = strings.admin.errors;

/** @typedef {import("./client.js").UserAdminT} UserAdminT */

/**
 * Field "delete" → hard-delete, nextValue ignore. Tách khỏi patch field để
 * confirm modal hiển thị message cảnh báo riêng + button đỏ destructive.
 *
 * @typedef {{
 *   user: UserAdminT,
 *   field: "disabled" | "is_admin" | "delete",
 *   nextValue: boolean,
 * }} PendingAction
 */

/**
 * @param {{ currentUserId: string, canManageAdmin?: boolean }} props
 */
export function AdminUsersTable({ currentUserId, canManageAdmin = false }) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["admin", "users"],
    queryFn: listUsers,
  });

  const [pending, setPending] = useState(/** @type {PendingAction | null} */ (null));
  const [search, setSearch] = useState("");

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

  // Delete dùng mutation riêng — response 204 (void), không reuse shape của
  // patchM. Tách ra cũng tránh lẫn error state giữa 2 thao tác khác nature.
  const deleteM = useMutation({
    mutationFn: (/** @type {string} */ userId) => deleteUser(userId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "users"] });
      qc.invalidateQueries({ queryKey: ["admin", "stats"] });
      setPending(null);
    },
  });

  const activeM = pending?.field === "delete" ? deleteM : patchM;

  function onConfirm() {
    if (!pending) return;
    if (pending.field === "delete") {
      deleteM.mutate(pending.user.id);
    } else {
      patchM.mutate({
        userId: pending.user.id,
        body: { [pending.field]: pending.nextValue },
      });
    }
  }

  function onCancel() {
    if (activeM.isPending) return;
    setPending(null);
    patchM.reset();
    deleteM.reset();
  }

  if (q.isPending) {
    return <div className="text-sm text-slate-500">{t.loading}</div>;
  }
  if (q.isError) {
    return <ListError error={q.error} />;
  }
  if (q.data.items.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-slate-300 bg-slate-50 p-4 text-center text-sm text-slate-600 md:p-6">
        {t.empty}
      </div>
    );
  }

  const needle = search.trim().toLowerCase();
  const filteredItems = needle
    ? q.data.items.filter((u) => u.email.toLowerCase().includes(needle))
    : q.data.items;

  return (
    <>
      <div className="mb-3">
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t.searchPlaceholder}
          className="w-full max-w-xs rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm shadow-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
        />
      </div>

      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white shadow-sm">
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
            {filteredItems.length === 0 ? (
              <tr>
                <td
                  colSpan={t.headers.length}
                  className="px-3 py-4 text-center text-sm text-slate-500"
                >
                  {t.searchEmpty}
                </td>
              </tr>
            ) : (
              filteredItems.map((u) => (
                <UserRow
                  key={u.id}
                  user={u}
                  isSelf={u.id === currentUserId}
                  canManageAdmin={canManageAdmin}
                  onAction={(field, nextValue) =>
                    setPending({ user: u, field, nextValue })
                  }
                />
              ))
            )}
          </tbody>
        </table>
      </div>

      {pending && (
        <ConfirmModal
          pending={pending}
          isPending={activeM.isPending}
          error={activeM.error}
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
 *   canManageAdmin: boolean,
 *   onAction: (field: "disabled" | "is_admin" | "delete", nextValue: boolean) => void,
 * }} props
 */
function UserRow({ user, isSelf, canManageAdmin, onAction }) {
  // Admin thường (không phải super admin) chỉ xem được — mọi nút mutation
  // chỉ super admin có quyền (cấp/thu hồi admin + khoá tài khoản).
  const showActions = !isSelf && canManageAdmin;
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
        ) : showActions ? (
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
            <button
              type="button"
              onClick={() => onAction("delete", true)}
              className="rounded-md border border-red-400 bg-red-50 px-2 py-1 text-xs font-medium text-red-800 hover:bg-red-100"
            >
              {t.btnDelete}
            </button>
          </div>
        ) : (
          <span className="text-xs text-slate-400">—</span>
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
  /** @type {string} */
  let message;
  /** @type {string} */
  let confirmLabel;
  if (field === "delete") {
    message = t.confirm.delete(user.email);
    confirmLabel = t.btnDelete;
  } else if (field === "disabled") {
    message = nextValue ? t.confirm.disable(user.email) : t.confirm.enable(user.email);
    confirmLabel = nextValue ? t.btnDisable : t.btnEnable;
  } else {
    message = nextValue ? t.confirm.promote(user.email) : t.confirm.demote(user.email);
    confirmLabel = nextValue ? t.btnPromote : t.btnDemote;
  }

  const isDestructive =
    field === "delete" ||
    (field === "disabled" && nextValue) ||
    (field === "is_admin" && nextValue);

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
