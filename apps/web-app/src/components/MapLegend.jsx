// @ts-check
import { strings } from "../strings.js";

const t = strings.coverageMap.legend;

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
    <div className="self-start rounded-md border border-slate-200 bg-white px-2 py-1.5 text-[10px] text-slate-700 shadow-sm">
      <div className="mb-1.5 text-[11px] leading-tight text-slate-500">
        <div>{t.gatewayCount(gatewayCount)}</div>
          {surveyCount != null && <div>{t.surveyCount(surveyCount)}</div>}
        </div>
      <div className="flex flex-col gap-1">
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rotate-45 bg-blue-700" />
          {t.gateway}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-full bg-green-600" />
          {t.strongRssi}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-full bg-yellow-500" />
          {t.mediumRssi}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-full bg-orange-500" />
          {t.weakRssi}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-full bg-red-600" />
          {t.noCoverage}
        </span>
      </div>
    </div>
  );
}
