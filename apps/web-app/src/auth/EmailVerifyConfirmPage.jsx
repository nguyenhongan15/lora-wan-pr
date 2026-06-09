// @ts-check
// Email verify confirm — render khi URL có `?verify_email=<token>`.
//
// Mirror ResetPassword.jsx pattern: full-screen page (không trong modal) vì
// user vào từ email link, không phải click-from-app. Khác ở chỗ: KHÔNG cần
// nhập password mới — token IS identity, mount → POST confirm ngay.
//
// Backend response codes (giống password reset):
//   * 400 email_verification_invalid: token sai/không tồn tại.
//   * 400 email_verification_expired: quá 60 phút.
//   * 400 email_verification_used:    đã consume single-use.
//   * 403 user_disabled:              admin disable user sau khi request.
//
// KHÔNG dùng useMutation ở đây: trong React 18 StrictMode dev, observer
// subscription cycle có thể làm state chuyển sang isSuccess/isError không
// propagate được vào UI → kẹt mãi "Đang xác thực…". Giải pháp: useState +
// module-level cache keyed theo token. Cache dedupe StrictMode double-effect
// đồng thời bảo toàn result qua cleanup/re-mount.

import { useEffect, useState } from "react";
import { ApiError, confirmEmailVerification, fetchMe } from "./client.js";
import { getToken, setSession } from "./store.js";
import { strings } from "../strings.js";

const t = strings.auth.verifyEmail;
const tErr = strings.auth.errors;

/**
 * @typedef {{ status: "pending" } | { status: "success" } | { status: "error", error: unknown }} VerifyState
 */

/**
 * Module-level cache: 1 token → 1 promise/result. Survive StrictMode
 * unmount-remount; reset chỉ khi full page reload.
 *
 * @type {Map<string, Promise<void> | { ok: true } | { ok: false, error: unknown }>}
 */
const _verifyCache = new Map();

/**
 * @param {string} token
 * @returns {Promise<void>}
 */
function _runVerify(token) {
  const cached = _verifyCache.get(token);
  if (cached instanceof Promise) return cached;
  if (cached && "ok" in cached) {
    if (cached.ok) return Promise.resolve();
    if ("error" in cached) return Promise.reject(cached.error);
  }
  const p = confirmEmailVerification({ token }).then(
    () => {
      _verifyCache.set(token, { ok: true });
    },
    (err) => {
      _verifyCache.set(token, { ok: false, error: err });
      throw err;
    },
  );
  _verifyCache.set(token, p);
  return p;
}

/**
 * @param {{ token: string | null, onDone: () => void }} props
 *   token = null → URL có `?verify_email=` nhưng giá trị rỗng → fallback.
 */
export function EmailVerifyConfirmPage({ token, onDone }) {
  const [state, setState] = useState(
    /** @type {VerifyState} */ ({ status: "pending" }),
  );

  useEffect(() => {
    if (!token) return undefined;
    let cancelled = false;
    _runVerify(token).then(
      () => {
        if (!cancelled) setState({ status: "success" });
      },
      (err) => {
        if (!cancelled) setState({ status: "error", error: err });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [token]);

  // Sau khi backend xác thực thành công, refresh user payload (nếu đang đăng
  // nhập) để dropdown trên header pick up email_verified=true. Tách ra effect
  // riêng — KHÔNG block success UI — để hiển thị "Đã xác thực thành công" ngay
  // sau POST 204, không chờ /auth/me round-trip.
  useEffect(() => {
    if (state.status !== "success") return undefined;
    if (!getToken()) return undefined;
    let cancelled = false;
    fetchMe()
      .then((u) => {
        if (cancelled || !u) return;
        const tk = getToken();
        if (tk) setSession(tk, u);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [state.status]);

  return (
    <div className="mx-auto mt-16 max-w-sm rounded-lg bg-white p-6 shadow-xl">
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">{t.confirmTitle}</h1>
        </div>

        {!token ? (
          <div
            role="alert"
            className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-800"
          >
            <div className="font-semibold">{t.missingTokenTitle}</div>
            <div className="mt-1 text-red-700">{t.missingTokenDetail}</div>
          </div>
        ) : state.status === "pending" ? (
          <div
            role="status"
            className="rounded-md border border-slate-300 bg-slate-50 p-3 text-sm text-slate-700"
          >
            {t.confirmPending}
          </div>
        ) : state.status === "success" ? (
          <>
            <div
              role="status"
              className="rounded-md border border-emerald-300 bg-emerald-50 p-3 text-sm text-emerald-800"
            >
              {t.confirmSuccess}
            </div>
            <button
              type="button"
              onClick={onDone}
              className="w-full rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-slate-800"
            >
              {t.confirmGoHome}
            </button>
          </>
        ) : (
          <div
            role="alert"
            className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-800"
          >
            {state.error instanceof ApiError ? (
              <>
                <div className="font-semibold">{state.error.problem.title}</div>
                {state.error.problem.detail && (
                  <div className="mt-1 text-red-700">
                    {state.error.problem.detail}
                  </div>
                )}
                {state.error.problem.code && (
                  <div className="mt-1 text-xs text-red-600">
                    {tErr.errorCodeLabel}: {state.error.problem.code}
                  </div>
                )}
              </>
            ) : (
              <div>{String(state.error)}</div>
            )}
            <button
              type="button"
              onClick={onDone}
              className="mt-3 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-100"
            >
              {t.confirmGoHome}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
