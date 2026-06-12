// @ts-check
// Filter panel cho tab "Bản đồ điểm đo": collapse default, click icon để mở,
// click X để đóng. State filter bên ngoài quản lý (CoverageMap) để URL state
// + react-query queryKey vẫn hoạt động đồng nhất; component này chỉ render +
// giữ `open` state UI nội bộ.

import { useState } from "react";
import { strings } from "../../strings.js";
import { ContributorFilter } from "./ContributorFilter.jsx";
import { LinkedSourceFilter } from "./LinkedSourceFilter.jsx";
import { DeviceFilter } from "./DeviceFilter.jsx";
import { SourceTypeFilter } from "./SourceTypeFilter.jsx";
import { SfMultiFilter } from "./SfMultiFilter.jsx";
import { NumericRangeFilter } from "./NumericRangeFilter.jsx";
import { TimeRangeFilter } from "./TimeRangeFilter.jsx";
import { SortFilter } from "./SortFilter.jsx";

const t = strings.coverageMap.filters;

/**
 * @typedef {{ min: number | null, max: number | null }} NumericRange
 * @typedef {{ from: string | null, to: string | null }} TimeRange
 * @typedef {{
 *   sortBy: import("../../api/client.js").SortBy,
 *   sortOrder: import("../../api/client.js").SortOrder,
 * }} SortConfig
 */

/**
 * @param {{
 *   user: import("../../auth/store.js").UserT | null,
 *   contributor: import("../../api/client.js").ContributorMode,
 *   onContributorChange: (next: import("../../api/client.js").ContributorMode) => void,
 *   linkedSourceId: string | null,
 *   onLinkedSourceChange: (id: string | null) => void,
 *   deviceId: string | null,
 *   onDeviceIdChange: (v: string | null) => void,
 *   sourceType: string | null,
 *   onSourceTypeChange: (s: string | null) => void,
 *   sfList: number[],
 *   onSfListChange: (v: number[]) => void,
 *   rssiRange: NumericRange,
 *   onRssiRangeChange: (v: NumericRange) => void,
 *   snrRange: NumericRange,
 *   onSnrRangeChange: (v: NumericRange) => void,
 *   timeRange: TimeRange,
 *   onTimeRangeChange: (v: TimeRange) => void,
 *   sortConfig: SortConfig,
 *   onSortConfigChange: (v: SortConfig) => void,
 *   realtimeEnabled: boolean,
 *   onRealtimeEnabledChange: (v: boolean) => void,
 *   autoFollowEnabled: boolean,
 *   onAutoFollowEnabledChange: (v: boolean) => void,
 *   connectionLinesEnabled: boolean,
 *   onConnectionLinesEnabledChange: (v: boolean) => void,
 * }} props
 */
export function PointsFilterPanel({
  user,
  contributor,
  onContributorChange,
  linkedSourceId,
  onLinkedSourceChange,
  deviceId,
  onDeviceIdChange,
  sourceType,
  onSourceTypeChange,
  sfList,
  onSfListChange,
  rssiRange,
  onRssiRangeChange,
  snrRange,
  onSnrRangeChange,
  timeRange,
  onTimeRangeChange,
  sortConfig,
  onSortConfigChange,
  realtimeEnabled,
  onRealtimeEnabledChange,
  autoFollowEnabled,
  onAutoFollowEnabledChange,
  connectionLinesEnabled,
  onConnectionLinesEnabledChange,
}) {
  const [open, setOpen] = useState(false);

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={t.toggle.open}
        title={t.toggle.open}
        className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-slate-200 bg-white text-slate-700 shadow-sm hover:bg-slate-50 hover:text-slate-900 focus:outline-none focus:ring-1 focus:ring-slate-500"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 20 20"
          fill="currentColor"
          className="h-5 w-5"
          aria-hidden
        >
          <path
            fillRule="evenodd"
            d="M2.628 1.601C5.028 1.206 7.49 1 10 1s4.973.206 7.372.601a.75.75 0 01.628.74v.387c0 1.224-.486 2.398-1.353 3.265L13.067 9.74a1.5 1.5 0 00-.439 1.06v3.745a3 3 0 01-1.318 2.486l-1.864 1.243a.75.75 0 01-1.165-.624v-6.85a1.5 1.5 0 00-.44-1.06L2.353 5.993A4.617 4.617 0 011 2.728V2.34a.75.75 0 01.628-.74z"
            clipRule="evenodd"
          />
        </svg>
      </button>
    );
  }

  return (
    <div className="flex max-h-full min-h-0 w-full flex-col overflow-y-auto rounded-md border border-slate-200 bg-white text-xs text-slate-700 shadow-sm md:w-64">
      <div className="sticky top-0 z-10 flex items-center justify-between border-b border-slate-200 bg-white px-3 py-2">
        <span className="text-sm font-semibold text-slate-900">
          {t.toggle.title}
        </span>
        <button
          type="button"
          onClick={() => setOpen(false)}
          aria-label={t.toggle.close}
          className="rounded p-1 text-slate-500 hover:bg-slate-100 hover:text-slate-900 focus:outline-none focus:ring-1 focus:ring-slate-500"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 20 20"
            fill="currentColor"
            className="h-4 w-4"
            aria-hidden
          >
            <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
          </svg>
        </button>
      </div>
      <div className="space-y-2.5 px-3 py-2">
        <ContributorFilter
          value={contributor}
          onChange={(next) => {
            onContributorChange(next);
            // Đổi mode khác "me" → reset linked_source + device_id (chỉ liên
            // quan mode me). Đổi sang "me" → reset source_type (mode "me"
            // ẩn SourceTypeFilter, không để filter ngầm không thấy được).
            if (next !== "me") {
              onLinkedSourceChange(null);
              onDeviceIdChange(null);
            } else {
              onSourceTypeChange(null);
            }
          }}
          user={user}
        />
        {contributor === "me" && user && (
          <>
            <LinkedSourceFilter
              value={linkedSourceId}
              onChange={onLinkedSourceChange}
            />
            <DeviceFilter
              value={deviceId}
              onChange={onDeviceIdChange}
              linkedSourceId={linkedSourceId}
            />
            <div className="border-t border-slate-200 pt-2.5 space-y-1.5">
              <div className="text-xs font-semibold text-slate-700">
                {t.realtime.sectionLabel}
              </div>
              <label className="flex items-start gap-2">
                <input
                  type="checkbox"
                  checked={realtimeEnabled}
                  onChange={(e) => onRealtimeEnabledChange(e.target.checked)}
                  className="mt-0.5"
                />
                <span>
                  <span className="font-medium">{t.realtime.toggleLabel}</span>
                  <span className="block text-xs text-slate-500">
                    {t.realtime.toggleHint}
                  </span>
                </span>
              </label>
              {realtimeEnabled && (
                <label className="flex items-start gap-2 pl-5">
                  <input
                    type="checkbox"
                    checked={autoFollowEnabled}
                    onChange={(e) =>
                      onAutoFollowEnabledChange(e.target.checked)
                    }
                    className="mt-0.5"
                  />
                  <span>
                    <span>{t.realtime.autoFollowLabel}</span>
                    <span className="block text-xs text-slate-500">
                      {t.realtime.autoFollowHint}
                    </span>
                  </span>
                </label>
              )}
            </div>
          </>
        )}
        {/* SourceTypeFilter ẩn khi mode "me" — mỗi linked_source đã bind 1
            source_type nên filter này redundant. Chỉ hữu ích cho cộng đồng
            (data nhiều provider trộn lẫn) hoặc admin. */}
        {user && contributor !== "me" && (
          <SourceTypeFilter value={sourceType} onChange={onSourceTypeChange} />
        )}

        <div className="border-t border-slate-200 pt-2.5 space-y-1.5">
          <label className="flex items-start gap-2">
            <input
              type="checkbox"
              checked={connectionLinesEnabled}
              onChange={(e) => onConnectionLinesEnabledChange(e.target.checked)}
              className="mt-0.5"
            />
            <span>
              <span className="font-medium">
                {t.connectionLines.toggleLabel}
              </span>
              <span className="block text-xs text-slate-500">
                {t.connectionLines.toggleHint}
              </span>
            </span>
          </label>
        </div>

        <div className="border-t border-slate-200 pt-2.5 space-y-2.5">
          <SortFilter value={sortConfig} onChange={onSortConfigChange} />
          <SfMultiFilter value={sfList} onChange={onSfListChange} />
          <NumericRangeFilter
            legend={t.rssi.legend}
            unit={t.rssi.unit}
            min={-150}
            max={0}
            step={1}
            value={rssiRange}
            onChange={onRssiRangeChange}
          />
          <NumericRangeFilter
            legend={t.snr.legend}
            unit={t.snr.unit}
            min={-30}
            max={20}
            step={0.5}
            value={snrRange}
            onChange={onSnrRangeChange}
          />
          <TimeRangeFilter value={timeRange} onChange={onTimeRangeChange} />
        </div>
      </div>
    </div>
  );
}
