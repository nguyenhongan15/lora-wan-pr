// @ts-check
// Panel góc trái cho tab "Bản đồ phủ sóng" + viewMode "minsf":
// dropdown chọn gateway + legend màu min-SF + ghi chú mô hình.
//
// Deep module: parent (CoverageMap) chỉ truyền danh sách gateway + selected
// code + onChange; panel tự render UI + legend. Không quản lý fetch GeoJSON
// (parent useEffect làm) — tách concern: panel = UI, parent = data flow.

import { strings } from "../strings.js";
import { MINSF_BAND_COLORS } from "./CoverageMap.config.js";

const t = strings.coverageMap.minsf;
const SF_LEVELS = /** @type {const} */ ([7, 8, 9, 10, 11, 12]);

/**
 * Gateway prop type — chỉ cần id/code/name (id cho React key, code làm value,
 * name hiển thị). Để optional vì zod-inferred type (`GatewayT`) đôi khi mark
 * field optional khi qua JSDoc → cho phép cả 2 shape mà không cần ép kiểu
 * ở callsite.
 *
 * @param {{
 *   gateways: ReadonlyArray<{ id?: string, code?: string, name?: string }>,
 *   selectedCode: string | null,
 *   onChange: (code: string | null) => void,
 *   loadingError: string | null,
 * }} props
 */
export function MinSFPanel({ gateways, selectedCode, onChange, loadingError }) {
  return (
    <div className="w-64 rounded-md border border-slate-200 bg-white px-3 py-2.5 text-xs text-slate-700 shadow-sm">
      <div className="text-sm font-semibold text-slate-900">{t.panelTitle}</div>

      <div className="mt-2">
        <label
          className="block text-xs font-medium text-slate-700"
          htmlFor="minsf-gw-selector"
        >
          {t.selector.label}
        </label>
        <select
          id="minsf-gw-selector"
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
        <div className="mt-2 rounded-md border border-amber-300 bg-amber-50 px-2 py-1 text-[11px] text-amber-900">
          {loadingError}
        </div>
      )}

      <div className="mt-3 border-t border-slate-200 pt-2">
        <div className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
          {t.legend.title}
        </div>
        <div className="mt-1 grid grid-cols-2 gap-x-2 gap-y-1">
          {SF_LEVELS.map((sf) => (
            <div key={sf} className="flex items-center gap-1.5 text-[11px]">
              <span
                className="inline-block h-3 w-3 rounded-sm border border-slate-300"
                style={{ background: MINSF_BAND_COLORS[sf] }}
              />
              <span>{t.legend.sfLabel(sf)}</span>
            </div>
          ))}
        </div>
        <div className="mt-2 text-[10px] leading-snug text-slate-500">
          {t.legend.hint}
        </div>
        <div className="mt-1 text-[10px] leading-snug text-slate-400">
          {t.model}
        </div>
      </div>
    </div>
  );
}
