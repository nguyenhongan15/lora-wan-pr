// @ts-check
// EmailVerifyModal — popup gửi link xác thực email.
//
// Email pre-filled từ user.email, disabled (per UX quyết định: 1 user = 1
// email, không cho đổi qua flow này — đổi email là 1 feature riêng).
//
// Trigger từ profile dropdown (button "Xác thực email") hoặc khi user click
// "Đóng góp" mà chưa verify (App layer pass `initialNotice` để hiển thị lý
// do mở modal).

import { useEffect, useRef } from "react";
import { useMutation } from "@tanstack/react-query";
import { ApiError, requestEmailVerification } from "./client.js";
import { strings } from "../strings.js";

const t = strings.auth.verifyEmail;
const tErr = strings.auth.errors;

/**
 * @param {{
 *   isOpen: boolean,
 *   email: string,
 *   onClose: () => void,
 *   notice?: string,
 * }} props
 */
export function EmailVerifyModal({ isOpen, email, onClose, notice }) {
  const tHeader = strings.auth.header;
  const m = useMutation({ mutationFn: requestEmailVerification });

  // Stable ref cho onClose: parent App re-render (vd bootstrap setSession qua
  // useSyncExternalStore) tạo arrow function `() => setVerifyOpen(false)` mới
  // mỗi render. Nếu bỏ `onClose` vào deps useEffect → effect re-run giữa lúc
  // SMTP đang gửi (~1.8s) → m.reset() xoá pending state → UI nhảy về form →
  // user tưởng chưa gửi, click lần 2.
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  // Esc → close. Reset mutation khi mở (để successHint không persist từ lần trước).
  useEffect(() => {
    if (!isOpen) return undefined;
    m.reset();
    /** @param {KeyboardEvent} e */
    const onKey = (e) => {
      if (e.key === "Escape") onCloseRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  if (!isOpen) return null;

  /** @param {import("react").FormEvent} e */
  function onSubmit(e) {
    e.preventDefault();
    m.mutate();
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="relative w-full max-w-sm rounded-lg bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          onClick={onClose}
          aria-label={tHeader.modalClose}
          className="absolute right-3 top-3 rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 20 20"
            fill="currentColor"
            className="h-5 w-5"
          >
            <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
          </svg>
        </button>

        <div className="space-y-6">
          <div>
            <h1 className="text-2xl font-semibold text-slate-900">
              {t.modalTitle}
            </h1>
            <p className="mt-1 text-sm text-slate-600">{t.modalSubtitle}</p>
          </div>

          {notice && (
            <div
              role="status"
              className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900"
            >
              {notice}
            </div>
          )}

          {m.isSuccess ? (
            <div
              role="status"
              className="rounded-md border border-emerald-300 bg-emerald-50 p-3 text-sm text-emerald-800"
            >
              {t.successHint}
            </div>
          ) : (
            <form onSubmit={onSubmit} className="space-y-4">
              <div>
                <label
                  htmlFor="auth-verify-email"
                  className="block text-sm font-medium text-slate-700"
                >
                  {t.emailLabel}
                </label>
                <input
                  id="auth-verify-email"
                  type="email"
                  value={email}
                  disabled
                  className="mt-1 w-full cursor-not-allowed rounded-md border-slate-300 bg-slate-50 px-3 py-2 text-sm text-slate-600 shadow-sm"
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
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
