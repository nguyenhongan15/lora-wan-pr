// @ts-check
// Panel góc trái cho tab "Bản đồ phủ sóng" + viewMode "estimate":
// legend màu RSSI tổng hợp + ghi chú mô hình.
//
// Composite RSSI heatmap: 1 grid duy nhất cho 11 gateway, mỗi ô tô màu theo
// max(RSSI) ước lượng nhận được.

import { strings } from "../strings.js";
import { ESTIMATE_RSSI_BAND_COLORS } from "./legend.js";

const t = strings.coverageMap.estimate;
const RSSI_BIN_IDS = /** @type {const} */ ([1, 2, 3, 4, 5, 6]);

/**
 * @param {{
 *   loadingError: string | null,
 * }} props
 */
export function EstimatePanel({ loadingError }) {
  return (
    <div className="w-64 rounded-md border border-slate-200 bg-white px-3 py-2.5 text-xs text-slate-700 shadow-sm">
      <div className="text-sm font-semibold text-slate-900">{t.panelTitle}</div>

      {loadingError && (
        <div className="mt-2 rounded-md border border-amber-300 bg-amber-50 px-2 py-1 text-[11px] text-amber-900">
          {loadingError}
        </div>
      )}

      <div className="mt-3 border-t border-slate-200 pt-2">
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

      <div className="mt-3 border-t border-slate-200 pt-2">
        <div className="text-[10px] leading-snug text-slate-500">{t.hint}</div>
        <div className="mt-1 text-[10px] leading-snug text-slate-400">
          {t.model}
        </div>
      </div>
    </div>
  );
}
