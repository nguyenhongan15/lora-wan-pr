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

import { useEffect, useRef } from "react";
import { useMutation } from "@tanstack/react-query";
import { ApiError, confirmEmailVerification, fetchMe } from "./client.js";
import { getToken, setSession } from "./store.js";
import { strings } from "../strings.js";

const t = strings.auth.verifyEmail;
const tErr = strings.auth.errors;

/**
 * @param {{ token: string | null, onDone: () => void }} props
 *   token = null → URL có `?verify_email=` nhưng giá trị rỗng → fallback.
 */
export function EmailVerifyConfirmPage({ token, onDone }) {
  const m = useMutation({ mutationFn: confirmEmailVerification });
  // useRef gate để StrictMode double-mount không gọi mutate 2 lần — server
  // backend đã single-use enforce, nhưng client tránh gọi thừa cho UX sạch.
  const triggered = useRef(false);

  useEffect(() => {
    if (!token) return;
    if (triggered.current) return;
    triggered.current = true;
    m.mutate({ token });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  // Sau khi backend xác thực thành công, refresh user payload (nếu đang đăng
  // nhập) để dropdown trên header pick up email_verified=true. Tách ra effect
  // riêng — KHÔNG block mutation success state — để UI hiện "Đã xác thực
  // thành công" ngay sau POST 204, không chờ /auth/me round-trip.
  useEffect(() => {
    if (!m.isSuccess) return;
    if (!getToken()) return;
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
  }, [m.isSuccess]);

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
        ) : m.isPending || m.isIdle ? (
          <div
            role="status"
            className="rounded-md border border-slate-300 bg-slate-50 p-3 text-sm text-slate-700"
          >
            {t.confirmPending}
          </div>
        ) : m.isSuccess ? (
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
        ) : null}

        {m.isError && (
          <div
            role="alert"
            className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-800"
          >
            {m.error instanceof ApiError ? (
              <>
                <div className="font-semibold">{m.error.problem.title}</div>
                {m.error.problem.detail && (
                  <div className="mt-1 text-red-700">
                    {m.error.problem.detail}
                  </div>
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
