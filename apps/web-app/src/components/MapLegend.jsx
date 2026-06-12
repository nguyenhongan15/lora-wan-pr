// @ts-check
import { strings } from "../strings.js";
import { SURVEY_RSSI_BINS } from "./legend.js";

const t = strings.coverageMap.legend;

// Legend chip render strong → weak (top → bottom, đảo lại so với
// SURVEY_RSSI_BINS sort weak → strong).
const LEGEND_ROWS = [...SURVEY_RSSI_BINS].reverse();

/**
 * Legend cố định cho cả tab "Bản đồ điểm đo" và "Bản đồ phủ sóng".
 * `surveyCount === null` → ẩn dòng "X điểm đo".
 *
 * @param {{
 *   gatewayCount?: number | null,
 *   surveyCount?: number | null,
 * }} props
 */
export function MapLegend({ gatewayCount, surveyCount = null }) {
  return (
    <div className="self-start rounded-md border border-slate-200 bg-white px-1.5 py-1 text-[8px] font-medium text-slate-700 shadow-sm md:px-2 md:py-1.5 md:text-[10px]">
      <div className="mb-0.5 text-[9px] font-semibold leading-tight text-slate-600 md:mb-1.5 md:text-[12px]">
        <div>{t.gatewayCount(gatewayCount)}</div>
          {surveyCount != null && <div>{t.surveyCount(surveyCount)}</div>}
        </div>
      <div className="flex flex-col gap-0.5 md:gap-1">
        {LEGEND_ROWS.map((bin) => (
          <span key={bin.label} className="inline-flex items-center gap-1 md:gap-1.5">
            <span
              className="inline-block h-1.5 w-1.5 rounded-full md:h-2 md:w-2"
              style={{ backgroundColor: bin.color }}
            />
            {bin.label}
          </span>
        ))}
      </div>
    </div>
  );
}
