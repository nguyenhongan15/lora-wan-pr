// @ts-check
// Sắp xếp theo timestamp / RSSI / SNR + chiều asc/desc. Không kèm cửa sổ
// rank — backend tự cap theo safety limit; UI hiển thị tất cả điểm trong
// khoảng đó.

import { strings } from "../../strings.js";

const t = strings.coverageMap.filters.sort;

const SORT_KEYS = /** @type {const} */ (["timestamp", "rssi", "snr"]);
const ORDER_KEYS = /** @type {const} */ (["desc", "asc"]);

/**
 * @typedef {(typeof SORT_KEYS)[number]} SortBy
 * @typedef {(typeof ORDER_KEYS)[number]} SortOrder
 */

/**
 * @param {{
 *   value: { sortBy: SortBy, sortOrder: SortOrder },
 *   onChange: (next: { sortBy: SortBy, sortOrder: SortOrder }) => void,
 * }} props
 */
export function SortFilter({ value, onChange }) {
  return (
    <fieldset className="space-y-1">
      <legend className="text-xs font-semibold text-slate-700">{t.legend}</legend>
      <div className="flex items-center gap-1.5">
        <select
          value={value.sortBy}
          onChange={(e) =>
            onChange({ ...value, sortBy: /** @type {SortBy} */ (e.target.value) })
          }
          className="flex-1 rounded-md border border-slate-300 px-2 py-1 text-[11px] shadow-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
        >
          {SORT_KEYS.map((k) => (
            <option key={k} value={k}>
              {t.sortBy[k]}
            </option>
          ))}
        </select>
        <select
          value={value.sortOrder}
          onChange={(e) =>
            onChange({
              ...value,
              sortOrder: /** @type {SortOrder} */ (e.target.value),
            })
          }
          className="rounded-md border border-slate-300 px-2 py-1 text-[11px] shadow-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
        >
          {ORDER_KEYS.map((k) => (
            <option key={k} value={k}>
              {t.sortOrder[k]}
            </option>
          ))}
        </select>
      </div>
    </fieldset>
  );
}
