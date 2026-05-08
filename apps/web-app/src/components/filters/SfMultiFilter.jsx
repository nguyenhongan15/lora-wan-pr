// @ts-check
// Single-select SF dropdown — chỉ dùng ở tab "Bản đồ điểm đo". Giá trị "all"
// = không gửi sf param (tất cả SF). Backend nhận sf_list dạng CSV; UI hiện
// đã rút gọn thành chọn 1 SF tại 1 thời điểm để gọn dropdown. State giữ
// nguyên `number[]` ([] = all, [n] = single SF) để contract với
// listSurveyTraining không phải đổi.

import { strings } from "../../strings.js";

const t = strings.coverageMap.filters.sfMulti;
const SF_VALUES = /** @type {const} */ ([7, 8, 9, 10, 11, 12]);

/**
 * @param {{
 *   value: ReadonlyArray<number>,
 *   onChange: (next: number[]) => void,
 * }} props
 */
export function SfMultiFilter({ value, onChange }) {
  const selected = value.length === 1 ? value[0] : "all";

  /** @param {string} raw */
  function handleChange(raw) {
    if (raw === "all") {
      onChange([]);
      return;
    }
    const n = Number(raw);
    if (!Number.isInteger(n) || n < 7 || n > 12) return;
    onChange([n]);
  }

  return (
    <div className="space-y-1">
      <label className="block text-xs font-semibold text-slate-700" htmlFor="sf-multi-picker">
        {t.legend}
      </label>
      <select
        id="sf-multi-picker"
        value={selected}
        onChange={(e) => handleChange(e.target.value)}
        className="w-full rounded-md border border-slate-300 px-2 py-1 text-xs shadow-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
      >
        <option value="all">{t.optionAll}</option>
        {SF_VALUES.map((sf) => (
          <option key={sf} value={sf}>
            SF{sf}
          </option>
        ))}
      </select>
    </div>
  );
}
