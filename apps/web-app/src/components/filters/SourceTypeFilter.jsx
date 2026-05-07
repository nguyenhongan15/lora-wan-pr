// @ts-check
// Filter theo source_type (column ts.survey_training.source_type). Hiện chỉ
// có 1 giá trị thực tế "lpwanmapper" (manual upload chưa có) — list cố
// định, mở rộng khi adapter mới ra mắt.

import { strings } from "../../strings.js";

const t = strings.coverageMap.filters.source;

const OPTIONS = /** @type {const} */ (["lpwanmapper"]);

/**
 * @param {{
 *   value: string | null,
 *   onChange: (next: string | null) => void,
 * }} props
 */
export function SourceTypeFilter({ value, onChange }) {
  return (
    <div className="space-y-1">
      <label className="block text-xs font-semibold text-slate-700" htmlFor="source-type-filter">
        {t.label}
      </label>
      <select
        id="source-type-filter"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
        className="w-full rounded-md border border-slate-300 px-2 py-1 text-xs shadow-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
      >
        <option value="">{t.optionAll}</option>
        {OPTIONS.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>
    </div>
  );
}
