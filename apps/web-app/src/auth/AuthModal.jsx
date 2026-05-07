// @ts-check
// AuthModal — popup chứa LoginPage hoặc RegisterPage, mở khi click avatar.
//
// UX:
//   - Mặc định mở vào "login" (case phổ biến nhất).
//   - Toggle login ↔ register qua link nội bộ (state mode).
//   - Đóng: nút X, click backdrop, hoặc Escape.
//   - Login success → onClose tự động (LoginPage gọi onSuccess).
//   - Register success → KHÔNG đóng (user cần thấy successHint), đồng thời
//     KHÔNG auto-switch sang login: plan-auth-v1 §3.1 register không trả
//     token nên user phải nhập lại password ở tab Login → ép switch sẽ làm
//     mất successHint. User tự click link "Đã có tài khoản? Đăng nhập".

import { useEffect, useState } from "react";
import { LoginPage } from "./LoginPage.jsx";
import { RegisterPage } from "./RegisterPage.jsx";
import { strings } from "../strings.js";

/**
 * @param {{ isOpen: boolean, onClose: () => void, initialMode?: "login" | "register" }} props
 */
export function AuthModal({ isOpen, onClose, initialMode = "login" }) {
  const [mode, setMode] = useState(/** @type {"login" | "register"} */ (initialMode));
  const tHeader = strings.auth.header;

  // Reset mode mỗi lần mở (không giữ state cũ giữa các lần mở/đóng).
  useEffect(() => {
    if (isOpen) setMode(initialMode);
  }, [isOpen, initialMode]);

  // Esc → close.
  useEffect(() => {
    if (!isOpen) return undefined;
    /** @param {KeyboardEvent} e */
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

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

        {mode === "login" ? (
          <LoginPage
            onSwitchToRegister={() => setMode("register")}
            onSuccess={onClose}
          />
        ) : (
          <RegisterPage onSwitchToLogin={() => setMode("login")} />
        )}
      </div>
    </div>
  );
}
