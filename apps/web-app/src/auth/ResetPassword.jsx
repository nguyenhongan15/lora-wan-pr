// @ts-check
// Reset-password form — mở khi URL chứa `?reset=<token>`.
//
// Render full-screen (không trong modal) vì user vào từ email link, không phải
// click-from-app — UX dạng landing page rõ hơn. Sau khi reset thành công, user
// click "Đăng nhập" → onDone clears query string + về app gốc.
//
// Backend response codes:
//   * 400 password_reset_invalid: token sai/không tồn tại.
//   * 400 password_reset_expired: quá 30 phút.
//   * 400 password_reset_used:    đã consume single-use.
//   * 400 user_disabled:          admin disable user sau khi request token.
// Tất cả render qua ApiError block — title + code đủ cho user hiểu vấn đề.

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { ApiError, confirmPasswordReset } from "./client.js";
import { strings } from "../strings.js";

const t = strings.auth.reset;
const tErr = strings.auth.errors;

/**
 * @param {{ token: string | null, onDone: () => void }} props
 *   token = null → URL có `?reset=` nhưng giá trị rỗng. Render fallback.
 */
export function ResetPassword({ token, onDone }) {
  const [newPassword, setNewPassword] = useState("");

  const m = useMutation({
    mutationFn: confirmPasswordReset,
  });

  /** @param {import("react").FormEvent} e */
  function onSubmit(e) {
    e.preventDefault();
    if (!token) return;
    m.mutate({ token, new_password: newPassword });
  }

  return (
    <div className="mx-auto mt-16 max-w-sm rounded-lg bg-white p-6 shadow-xl">
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">{t.title}</h1>
          <p className="mt-1 text-sm text-slate-600">{t.subtitle}</p>
        </div>

        {!token ? (
          <div
            role="alert"
            className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-800"
          >
            <div className="font-semibold">{t.missingTokenTitle}</div>
            <div className="mt-1 text-red-700">{t.missingTokenDetail}</div>
          </div>
        ) : m.isSuccess ? (
          <>
            <div
              role="status"
              className="rounded-md border border-emerald-300 bg-emerald-50 p-3 text-sm text-emerald-800"
            >
              {t.successHint}
            </div>
            <button
              type="button"
              onClick={onDone}
              className="w-full rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-slate-800"
            >
              {t.goToLogin}
            </button>
          </>
        ) : (
          <form onSubmit={onSubmit} className="space-y-4">
            <div>
              <label
                htmlFor="auth-reset-newpw"
                className="block text-sm font-medium text-slate-700"
              >
                {t.newPasswordLabel}
              </label>
              <input
                id="auth-reset-newpw"
                type="password"
                autoComplete="new-password"
                required
                minLength={8}
                maxLength={128}
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                className="mt-1 w-full rounded-md border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-slate-500 focus:ring-slate-500"
              />
            </div>

            <button
              type="submit"
              disabled={m.isPending}
              className="w-full rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-slate-800 disabled:opacity-50"
            >
              {m.isPending ? t.submitPending : t.submit}
            </button>
          </form>
        )}

        {m.isError && (
          <div
            role="alert"
            className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-800"
          >
            {m.error instanceof ApiError ? (
              <>
                <div className="font-semibold">{m.error.problem.title}</div>
                {m.error.problem.detail && (
                  <div className="mt-1 text-red-700">{m.error.problem.detail}</div>
                )}
                {m.error.problem.code && (
                  <div className="mt-1 text-xs text-red-600">
                    {tErr.errorCodeLabel}: {m.error.problem.code}
                  </div>
                )}
              </>
            ) : (
              <div>{String(m.error)}</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
