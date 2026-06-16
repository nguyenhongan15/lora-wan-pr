// @ts-check
// Filter "Số điểm gần nhất" — input số N + dropdown thứ tự (mới nhất / cũ nhất).
// Map sang backend: limit=N + sort_order=desc|asc. count=null → không gửi
// limit (backend dùng cap mặc định).

import { strings } from "../../strings.js";

const t = strings.coverageMap.filters.latestCount;
const tFilters = strings.coverageMap.filters;

/**
 * @typedef {"desc" | "asc"} LatestOrder
 * @typedef {{ count: number | null, order: LatestOrder }} LatestCountValue
 */

const MAX = 50000;

/**
 * @param {{
 *   value: LatestCountValue,
 *   onChange: (next: LatestCountValue) => void,
 * }} props
 */
export function LatestPointsFilter({ value, onChange }) {
  /** @param {string} raw @returns {number | null} */
  function parseCount(raw) {
    if (raw.trim() === "") return null;
    const n = Number(raw);
    if (!Number.isFinite(n)) return null;
    const i = Math.floor(n);
    if (i < 1) return null;
    return Math.min(MAX, i);
  }

  return (
    <fieldset className="space-y-1">
      <legend className="text-xs font-semibold text-slate-700">
        {t.legend}
      </legend>
      <div className="flex items-center gap-1.5 text-[11px] text-slate-600">
        <input
          type="text"
          inputMode="numeric"
          pattern="[0-9]*"
          value={value.count ?? ""}
          onChange={(e) =>
            onChange({ ...value, count: parseCount(e.target.value) })
          }
          placeholder={t.placeholder}
          className="w-28 rounded-md border border-slate-300 px-2 py-1.5 text-right text-sm font-mono shadow-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
        />
        <select
          value={value.order}
          onChange={(e) =>
            onChange({
              ...value,
              order: /** @type {LatestOrder} */ (e.target.value),
            })
          }
          className="flex-1 rounded-md border border-slate-300 px-1.5 py-0.5 text-xs shadow-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
        >
          <option value="desc">{t.orders.desc}</option>
          <option value="asc">{t.orders.asc}</option>
        </select>
        {value.count !== null && (
          <button
            type="button"
            onClick={() => onChange({ ...value, count: null })}
            aria-label={`${tFilters.clear} ${t.legend}`}
            title={`${tFilters.clear} ${t.legend}`}
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
