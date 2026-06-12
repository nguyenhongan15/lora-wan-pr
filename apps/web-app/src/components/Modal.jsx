// @ts-check
// Modal — centered overlay dùng chung thay window.alert / window.confirm.
//
// Pattern theo AuthModal: backdrop `fixed inset-0` + click-out đóng + Esc đóng.
// Có 2 preset gọn:
//   - <AlertModal title body dismissLabel onClose />
//   - <ConfirmModal title body confirmLabel cancelLabel danger onConfirm onCancel />
// Caller tự quản state mở/đóng (boolean) — modal chỉ render khi state truthy,
// không tự giấu. Tránh portal vì single-tree app + Tailwind z-50 đủ.

import { useEffect } from "react";

/**
 * @param {{
 *   title: string,
 *   children: import("react").ReactNode,
 *   onClose: () => void,
 *   widthClass?: string,
 * }} props
 */
function ModalShell({ title, children, onClose, widthClass = "max-w-md" }) {
  useEffect(() => {
    function onKey(/** @type {KeyboardEvent} */ e) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby="modal-title"
    >
      <div
        className={`relative w-full ${widthClass} rounded-lg bg-white p-6 shadow-xl`}
        onClick={(e) => e.stopPropagation()}
      >
        <h3 id="modal-title" className="text-base font-semibold text-slate-900">
          {title}
        </h3>
        {children}
      </div>
    </div>
  );
}

/**
 * Modal 1 nút — thay window.alert.
 * @param {{
 *   title: string,
 *   body: import("react").ReactNode,
 *   dismissLabel?: string,
 *   onClose: () => void,
 * }} props
 */
export function AlertModal({ title, body, dismissLabel = "Đã hiểu", onClose }) {
  return (
    <ModalShell title={title} onClose={onClose}>
      <div className="mt-3 whitespace-pre-line text-sm leading-relaxed text-slate-700">
        {body}
      </div>
      <div className="mt-5 flex justify-end">
        <button
          type="button"
          onClick={onClose}
          className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-slate-800"
        >
          {dismissLabel}
        </button>
      </div>
    </ModalShell>
  );
}

/**
 * Modal 2 nút — thay window.confirm. `danger=true` → nút xác nhận màu đỏ
 * (dùng cho xoá/rotate webhook).
 * @param {{
 *   title: string,
 *   body: import("react").ReactNode,
 *   confirmLabel?: string,
 *   cancelLabel?: string,
 *   danger?: boolean,
 *   onConfirm: () => void,
 *   onCancel: () => void,
 * }} props
 */
export function ConfirmModal({
  title,
  body,
  confirmLabel = "Xác nhận",
  cancelLabel = "Huỷ",
  danger = false,
  onConfirm,
  onCancel,
}) {
  const confirmCls = danger
    ? "rounded-md bg-rose-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-rose-700"
    : "rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-slate-800";
  return (
    <ModalShell title={title} onClose={onCancel}>
      <div className="mt-3 whitespace-pre-line text-sm leading-relaxed text-slate-700">
        {body}
      </div>
      <div className="mt-5 flex justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50"
        >
          {cancelLabel}
        </button>
        <button type="button" onClick={onConfirm} className={confirmCls}>
          {confirmLabel}
        </button>
      </div>
    </ModalShell>
  );
}
