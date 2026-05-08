// @ts-check
// General-purpose 2-input numeric range (Ousterhout: general-purpose modules
// are deeper). Dùng cho RSSI dBm và SNR dB; có thể tái dùng cho range
// numeric tương lai (frequency, weight…).

import { strings } from "../../strings.js";

const tFilters = strings.coverageMap.filters;

/**
 * @param {{
 *   legend: string,
 *   unit: string,
 *   min: number,
 *   max: number,
 *   step?: number,
 *   value: { min: number | null, max: number | null },
 *   onChange: (next: { min: number | null, max: number | null }) => void,
 * }} props
 */
export function NumericRangeFilter({ legend, unit, min, max, step, value, onChange }) {
  /** @param {string} raw @returns {number | null} */
  function parse(raw) {
    if (raw.trim() === "") return null;
    const n = Number(raw);
    if (!Number.isFinite(n)) return null;
    return Math.min(max, Math.max(min, n));
  }

  const hasValue = value.min !== null || value.max !== null;

  return (
    <fieldset className="space-y-1">
      <legend className="text-xs font-semibold text-slate-700">{legend}</legend>
      <div className="flex items-center gap-1.5 text-[11px] text-slate-600">
        <input
          type="number"
          inputMode="decimal"
          step={step ?? 1}
          min={min}
          max={max}
          value={value.min ?? ""}
          onChange={(e) => onChange({ ...value, min: parse(e.target.value) })}
          placeholder={String(min)}
          className="w-16 rounded-md border border-slate-300 px-1.5 py-0.5 text-right font-mono shadow-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
        />
        <span aria-hidden>—</span>
        <input
          type="number"
          inputMode="decimal"
          step={step ?? 1}
          min={min}
          max={max}
          value={value.max ?? ""}
          onChange={(e) => onChange({ ...value, max: parse(e.target.value) })}
          placeholder={String(max)}
          className="w-16 rounded-md border border-slate-300 px-1.5 py-0.5 text-right font-mono shadow-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
        />
        <span className="text-slate-500">{unit}</span>
        {hasValue && (
          <button
            type="button"
            onClick={() => onChange({ min: null, max: null })}
            aria-label={`${tFilters.clear} ${legend}`}
            title={`${tFilters.clear} ${legend}`}
            className="ml-auto inline-flex h-5 w-5 items-center justify-center rounded text-slate-400 hover:bg-slate-100 hover:text-slate-700 focus:outline-none focus:ring-1 focus:ring-slate-500"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 20 20"
              fill="currentColor"
              className="h-3.5 w-3.5"
              aria-hidden
            >
              <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
            </svg>
          </button>
        )}
      </div>
    </fieldset>
  );
}
