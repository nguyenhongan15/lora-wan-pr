// @ts-check
// Picker chọn cách hiển thị data trên tab "Bản đồ điểm đo": circle theo RSSI
// hoặc heatmap mật độ. Đặt ở top-right dưới NavigationControl của MapLibre.
//
// Interface tối thiểu (deep module): mode + onChange + danh sách options
// {value,label}. Component tự quản dropdown open/close + click-outside-to-close
// để parent (CoverageMap) không cần biết trạng thái mở/đóng.

import { useEffect, useRef, useState } from "react";
import { strings } from "../strings.js";

const t = strings.coverageMap.viewModePicker;

/**
 * Generic view-mode toggle — value typed string. Tab "Bản đồ điểm đo"
 * hiện dùng "points" | "heatmap"; component không quan tâm semantic
 * value, chỉ render label.
 */

/**
 * @param {{
 *   mode: string,
 *   onChange: (next: string) => void,
 *   options: ReadonlyArray<{ value: string, label: string }>,
 * }} props
 */
export function MapViewModeToggle({ mode, onChange, options }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef(/** @type {HTMLDivElement | null} */ (null));

  // Click-outside đóng dropdown. Chỉ attach khi đang mở để không leak listener.
  useEffect(() => {
    if (!open) return;
    /** @param {MouseEvent} e */
    function onDocClick(e) {
      if (!rootRef.current) return;
      if (!rootRef.current.contains(/** @type {Node} */ (e.target))) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  return (
    <div
      ref={rootRef}
      className="pointer-events-auto absolute top-2.5 right-2.5 z-10"
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label={t.ariaLabel}
        aria-haspopup="menu"
        aria-expanded={open}
        title={t.title}
        className="flex h-[29px] w-[29px] items-center justify-center rounded-[4px] border border-slate-200 bg-white text-slate-700 shadow-sm hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-slate-400"
      >
        {/* Lucide "layers" icon — inline để không thêm dep, currentColor follow text. */}
        <svg
          viewBox="0 0 24 24"
          width="18"
          height="18"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M12 2 2 7l10 5 10-5-10-5z" />
          <path d="M2 17l10 5 10-5" />
          <path d="M2 12l10 5 10-5" />
        </svg>
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 top-full mt-1 w-44 rounded-md border border-slate-200 bg-white py-1 shadow-md"
        >
          <div className="px-3 py-1 text-[11px] font-medium uppercase tracking-wide text-slate-500">
            {t.title}
          </div>
          {options.map((opt) => {
            const selected = opt.value === mode;
            return (
              <button
                key={opt.value}
                type="button"
                role="menuitemradio"
                aria-checked={selected}
                onClick={() => {
                  onChange(opt.value);
                  setOpen(false);
                }}
                className={
                  "flex w-full items-center justify-between px-3 py-1.5 text-left text-xs " +
                  (selected
                    ? "bg-slate-100 font-medium text-slate-900"
                    : "text-slate-700 hover:bg-slate-50")
                }
              >
                <span>{opt.label}</span>
                {selected && (
                  <svg
                    viewBox="0 0 24 24"
                    width="14"
                    height="14"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden="true"
                  >
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
