// @ts-check
// Panel góc trái cho tab "Bản đồ phủ sóng" + viewMode "estimate":
// dropdown chọn gateway (default = tất cả → composite) + legend màu RSSI tổng
// hợp.
//
// Composite RSSI heatmap: 1 grid duy nhất cho 11+ gateway, mỗi ô tô màu theo
// max(RSSI) ước lượng nhận được. Chọn 1 gateway cụ thể → load per_gw/{code}.
//
// Collapse pattern khớp với PointsFilterPanel: default closed (chỉ 1 icon
// button 36px) để không che map. Click → mở panel với header sticky + nút X.

import { useState } from "react";
import { strings } from "../strings.js";
import { ESTIMATE_RSSI_BAND_COLORS } from "./legend.js";

const t = strings.coverageMap.estimate;
const RSSI_BIN_IDS = /** @type {const} */ ([1, 2, 3, 4, 5, 6]);

/**
 * @param {{
 *   gateways: ReadonlyArray<{ id?: string, code?: string, name?: string }>,
 *   selectedCode: string | null,
 *   onChange: (code: string | null) => void,
 *   loadingError: string | null,
 * }} props
 */
export function EstimatePanel({
  gateways,
  selectedCode,
  onChange,
  loadingError,
}) {
  const [open, setOpen] = useState(false);

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={t.toggle.open}
        title={t.toggle.open}
        className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-slate-200 bg-white text-slate-700 shadow-sm hover:bg-slate-50 hover:text-slate-900 focus:outline-none focus:ring-1 focus:ring-slate-500"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 20 20"
          fill="currentColor"
          className="h-5 w-5"
          aria-hidden
        >
          <path d="M2 4.25A2.25 2.25 0 014.25 2h2.5A2.25 2.25 0 019 4.25v2.5A2.25 2.25 0 016.75 9h-2.5A2.25 2.25 0 012 6.75v-2.5zM2 13.25A2.25 2.25 0 014.25 11h2.5A2.25 2.25 0 019 13.25v2.5A2.25 2.25 0 016.75 18h-2.5A2.25 2.25 0 012 15.75v-2.5zM11 4.25A2.25 2.25 0 0113.25 2h2.5A2.25 2.25 0 0118 4.25v2.5A2.25 2.25 0 0115.75 9h-2.5A2.25 2.25 0 0111 6.75v-2.5zM11 13.25A2.25 2.25 0 0113.25 11h2.5A2.25 2.25 0 0118 13.25v2.5A2.25 2.25 0 0115.75 18h-2.5A2.25 2.25 0 0111 15.75v-2.5z" />
        </svg>
      </button>
    );
  }

  return (
    <div className="flex max-h-full min-h-0 w-full flex-col overflow-y-auto rounded-md border border-slate-200 bg-white text-xs text-slate-700 shadow-sm md:w-64">
      <div className="sticky top-0 z-10 flex items-center justify-between border-b border-slate-200 bg-white px-3 py-2">
        <span className="text-sm font-semibold text-slate-900">
          {t.panelTitle}
        </span>
        <button
          type="button"
          onClick={() => setOpen(false)}
          aria-label={t.toggle.close}
          className="rounded p-1 text-slate-500 hover:bg-slate-100 hover:text-slate-900 focus:outline-none focus:ring-1 focus:ring-slate-500"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 20 20"
            fill="currentColor"
            className="h-4 w-4"
            aria-hidden
          >
            <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
          </svg>
        </button>
      </div>
      <div className="space-y-2.5 px-3 py-2">
        <div>
          <label
            className="block text-xs font-medium text-slate-700"
            htmlFor="estimate-gw-selector"
          >
            {t.selector.label}
          </label>
          <select
            id="estimate-gw-selector"
            value={selectedCode ?? ""}
            onChange={(e) => {
              const v = e.target.value;
              onChange(v === "" ? null : v);
            }}
            className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1 text-xs shadow-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
          >
            <option value="">{t.selector.placeholder}</option>
            {gateways.length === 0 ? (
              <option disabled>{t.selector.empty}</option>
            ) : (
              gateways.map((g) => (
                <option key={g.id ?? g.code} value={g.code ?? ""}>
                  {g.code} — {g.name}
                </option>
              ))
            )}
          </select>
        </div>

        {loadingError && (
          <div className="rounded-md border border-amber-300 bg-amber-50 px-2 py-1 text-[11px] text-amber-900">
            {loadingError}
          </div>
        )}

        <div className="border-t border-slate-200 pt-2">
          <div className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
            {t.legendTitle}
          </div>
          <div className="mt-1 flex flex-col gap-1">
            {RSSI_BIN_IDS.map((bin) => (
              <div key={bin} className="flex items-center gap-1.5 text-[11px]">
                <span
                  className="inline-block h-3 w-3 rounded-sm border border-slate-300"
                  style={{ background: ESTIMATE_RSSI_BAND_COLORS[bin] }}
                />
                <span>{t.bins[bin]}</span>
              </div>
            ))}
            <div className="flex items-center gap-1.5 text-[11px] text-slate-500">
              <span className="inline-block h-3 w-3 rounded-sm border border-dashed border-slate-300 bg-transparent" />
              <span>{t.notCovered}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
