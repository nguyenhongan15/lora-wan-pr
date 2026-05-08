// @ts-check
// Filter theo timestamp — preset 24h / 7d / 30d / All. Backend nhận ISO 8601;
// component output lưu sẵn ISO string (không phải Date object) để URL state
// stable + JSON-serializable.

import { useState } from "react";
import { strings } from "../../strings.js";

const t = strings.coverageMap.filters.timeRange;

/**
 * @typedef {"all" | "24h" | "7d" | "30d"} Preset
 * @typedef {{ from: string | null, to: string | null }} TimeRangeValue
 */

const PRESETS = /** @type {const} */ (["all", "24h", "7d", "30d"]);

/**
 * Preset → ISO `from` (giờ to=now). "all" trả null = không apply auto.
 * @param {Preset} p
 * @returns {string | null}
 */
function presetFromIso(p) {
  if (p === "all") return null;
  const ms = p === "24h" ? 86400e3 : p === "7d" ? 7 * 86400e3 : 30 * 86400e3;
  return new Date(Date.now() - ms).toISOString();
}

/**
 * @param {{
 *   value: TimeRangeValue,
 *   onChange: (next: TimeRangeValue) => void,
 * }} props
 */
export function TimeRangeFilter({ value, onChange }) {
  // Preset là UI state. Persisted state là ISO from/to → reload từ URL khôi
  // phục đúng filter mà không cần biết user đã chọn preset nào.
  const [preset, setPreset] = useState(/** @type {Preset} */ (
    value.from ? "24h" : "all"
  ));

  /** @param {Preset} p */
  function selectPreset(p) {
    setPreset(p);
    if (p === "all") {
      onChange({ from: null, to: null });
    } else {
      onChange({ from: presetFromIso(p), to: null });
    }
  }

  return (
    <fieldset className="space-y-1">
      <legend className="text-xs font-semibold text-slate-700">{t.legend}</legend>
      <select
        value={preset}
        onChange={(e) => selectPreset(/** @type {Preset} */ (e.target.value))}
        className="w-full rounded-md border border-slate-300 px-2 py-1 text-xs shadow-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
      >
        {PRESETS.map((p) => (
          <option key={p} value={p}>
            {t.presets[p]}
          </option>
        ))}
      </select>
    </fieldset>
  );
}
