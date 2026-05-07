// @ts-check
// Register page — gần giống LoginPage nhưng:
//   - autoComplete="new-password" (browser sẽ gợi ý mật khẩu mạnh)
//   - minLength=8 attr (HTML validation) + Zod check ở client.js (server cũng
//     enforce min 8 — plan §3.1).
//   - Sau register thành công KHÔNG auto-login (plan-auth-v1 §3.1: register
//     trả UserResponse, không token). Show successHint → user bấm "Đăng nhập".

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { ApiError, register } from "./client.js";
import { strings } from "../strings.js";

const t = strings.auth.register;
const tErr = strings.auth.errors;

/**
 * @param {{ onSwitchToLogin: () => void }} props
 */
export function RegisterPage({ onSwitchToLogin }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const m = useMutation({
    mutationFn: register,
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
            htmlFor="auth-register-email"
            className="block text-sm font-medium text-slate-700"
          >
            {t.emailLabel}
          </label>
          <input
            id="auth-register-email"
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
            htmlFor="auth-register-password"
            className="block text-sm font-medium text-slate-700"
          >
            {t.passwordLabel}
          </label>
          <input
            id="auth-register-password"
            type="password"
            autoComplete="new-password"
            minLength={8}
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

      {m.isSuccess && (
        <div
          role="status"
          className="rounded-md border border-green-300 bg-green-50 p-3 text-sm text-green-800"
        >
          {t.successHint}
        </div>
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

      <button
        type="button"
        onClick={onSwitchToLogin}
        className="block w-full text-center text-sm text-slate-600 underline hover:text-slate-900"
      >
        {t.switchToLogin}
      </button>
    </div>
  );
}
