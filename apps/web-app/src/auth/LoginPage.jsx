// @ts-check
// Login form — dùng inside AuthModal (popup), không phải page độc lập.
//
// Plan §11 step 9 + accessibility guideline:
//   - autoComplete: email / current-password (browser password manager)
//   - role="alert" cho error banner (screen reader announce)
//   - htmlFor / id pair (label-input)
//   - disabled khi pending → tránh double-submit
//
// Sau login thành công: store set bên trong client.login() → onSuccess
// callback (App) đóng modal; subscribe ở App tự re-render.

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { ApiError, login } from "./client.js";
import { strings } from "../strings.js";

const t = strings.auth.login;
const tErr = strings.auth.errors;

/**
 * @param {{ onSwitchToRegister: () => void, onSuccess?: () => void }} props
 */
export function LoginPage({ onSwitchToRegister, onSuccess }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const m = useMutation({
    mutationFn: login,
    onSuccess: () => onSuccess?.(),
  });

  /** @param {import("react").FormEvent} e */
  function onSubmit(e) {
    e.preventDefault();
    m.mutate({ email: email.trim(), password });
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">{t.title}</h1>
        <p className="mt-1 text-sm text-slate-600">{t.subtitle}</p>
      </div>

      <form onSubmit={onSubmit} className="space-y-4">
        <div>
          <label
            htmlFor="auth-login-email"
            className="block text-sm font-medium text-slate-700"
          >
            {t.emailLabel}
          </label>
          <input
            id="auth-login-email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="mt-1 w-full rounded-md border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-slate-500 focus:ring-slate-500"
          />
        </div>

        <div>
          <label
            htmlFor="auth-login-password"
            className="block text-sm font-medium text-slate-700"
          >
            {t.passwordLabel}
          </label>
          <input
            id="auth-login-password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
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

      <button
        type="button"
        onClick={onSwitchToRegister}
        className="block w-full text-center text-sm text-slate-600 underline hover:text-slate-900"
      >
        {t.switchToRegister}
      </button>
    </div>
  );
}
