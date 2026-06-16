// @ts-check
// Panel "Theo dõi trực tiếp" (refactor 2026-06-15) — chỉ xem live, không
// còn tạo batch. Picker chọn linked_source → bật toggle → poll điểm mới
// hiển thị trên map. Tắt toggle → ngừng poll, giữ markers.
// Tải dữ liệu thật về DB dùng nút "Tải dữ liệu mới nhất" trong tab Nguồn.

import { useEffect, useState } from "react";
import { strings } from "../../strings.js";
import { LiveSessionSourcePicker } from "./LiveSessionSourcePicker.jsx";

const t = strings.coverageMap.filters.realtime;

/**
 * Input số giây với local string state — cho phép user xoá hết / gõ tạm số
 * ngoài [min,max] mà KHÔNG bị parent clamp ép giá trị về giữa chừng. Commit
 * lên parent khi blur hoặc Enter; giá trị rỗng / invalid → revert về value.
 *
 * @param {{
 *   value: number,
 *   min: number,
 *   max: number,
 *   onCommit: (v: number) => void,
 *   className?: string,
 * }} props
 */
function IntervalSecondsInput({ value, min, max, onCommit, className }) {
  const [draft, setDraft] = useState(String(value));
  // Đồng bộ khi parent đổi value từ ngoài (vd reset session).
  useEffect(() => {
    setDraft(String(value));
  }, [value]);

  const commit = () => {
    const n = Number.parseInt(draft, 10);
    if (!Number.isFinite(n)) {
      setDraft(String(value));
      return;
    }
    const clamped = Math.min(max, Math.max(min, n));
    setDraft(String(clamped));
    if (clamped !== value) onCommit(clamped);
  };

  return (
    <input
      type="number"
      min={min}
      max={max}
      step={1}
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          commit();
          /** @type {HTMLInputElement} */ (e.currentTarget).blur();
        }
      }}
      className={className}
    />
  );
}

/**
 * @param {{
 *   open: boolean,
 *   onToggle: () => void,
 *   realtimeEnabled: boolean,
 * }} props
 */
export function RealtimeToggleBtn({ open, onToggle, realtimeEnabled }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-label={open ? t.panelToggle.close : t.panelToggle.open}
      title={open ? t.panelToggle.close : t.panelToggle.open}
      aria-expanded={open}
      className={`relative inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md border shadow-sm focus:outline-none focus:ring-1 focus:ring-slate-500 ${
        open
          ? "border-slate-400 bg-slate-100 text-slate-900"
          : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50 hover:text-slate-900"
      }`}
    >
      <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 20 20"
        fill="currentColor"
        className="h-5 w-5"
        aria-hidden
      >
        <path d="M10 7a3 3 0 100 6 3 3 0 000-6z" />
        <path
          fillRule="evenodd"
          d="M3.05 6.05a.75.75 0 011.06 0 6 6 0 010 8.485.75.75 0 11-1.06-1.06 4.5 4.5 0 000-6.364.75.75 0 010-1.06zm13.9 0a.75.75 0 010 1.06 4.5 4.5 0 000 6.364.75.75 0 11-1.06 1.06 6 6 0 010-8.485.75.75 0 011.06 0zM6.586 8.586a.75.75 0 010 1.06 1.5 1.5 0 000 2.122.75.75 0 11-1.06 1.06 3 3 0 010-4.243.75.75 0 011.06 0zm6.828 0a.75.75 0 011.06 0 3 3 0 010 4.243.75.75 0 11-1.06-1.06 1.5 1.5 0 000-2.122.75.75 0 010-1.06z"
          clipRule="evenodd"
        />
      </svg>
      {realtimeEnabled && (
        <span className="absolute -right-0.5 -top-0.5 inline-block h-2.5 w-2.5 animate-pulse rounded-full bg-red-500 ring-2 ring-white" />
      )}
    </button>
  );
}

/**
 * @param {{
 *   user: import("../../auth/store.js").UserT | null,
 *   onRequestLogin?: (afterLogin?: () => void) => void,
 *   realtimeEnabled: boolean,
 *   onRealtimeEnabledChange: (v: boolean) => void,
 *   realtimeStarted: boolean,
 *   onStartWatching: () => void,
 *   onChangeSource: () => void,
 *   onStopWatching: () => void,
 *   autoFollowEnabled: boolean,
 *   onAutoFollowEnabledChange: (v: boolean) => void,
 *   connectionLinesEnabled: boolean,
 *   onConnectionLinesEnabledChange: (v: boolean) => void,
 *   onlyNewAfterStart: boolean,
 *   onOnlyNewAfterStartChange: (v: boolean) => void,
 *   liveSessionSourceId: string | null,
 *   onLiveSessionSourceIdChange: (v: string | null) => void,
 *   livePullIntervalSec: number,
 *   onLivePullIntervalSecChange: (v: number) => void,
 *   livePullIntervalMin: number,
 *   livePullIntervalMax: number,
 * }} props
 */
export function RealtimeBody({
  user,
  onRequestLogin,
  realtimeEnabled,
  onRealtimeEnabledChange,
  realtimeStarted,
  onStartWatching,
  onChangeSource,
  onStopWatching,
  autoFollowEnabled,
  onAutoFollowEnabledChange,
  connectionLinesEnabled,
  onConnectionLinesEnabledChange,
  onlyNewAfterStart,
  onOnlyNewAfterStartChange,
  liveSessionSourceId,
  onLiveSessionSourceIdChange,
  livePullIntervalSec,
  onLivePullIntervalSecChange,
  livePullIntervalMin,
  livePullIntervalMax,
}) {
  const loggedIn = !!user;
  const canStart = !!liveSessionSourceId;

  return (
    <div className="flex max-h-full min-h-0 min-w-0 flex-1 flex-col overflow-y-auto rounded-md border border-slate-200 bg-white text-xs text-slate-700 shadow-sm md:w-64 md:flex-initial">
      <div className="sticky top-0 z-10 border-b border-slate-200 bg-white px-3 py-2">
        <span className="text-sm font-semibold text-slate-900">
          {t.panelToggle.title}
        </span>
      </div>
      <div className="space-y-1.5 px-3 py-2">
        <label
          className={`flex items-start gap-2 ${
            loggedIn ? "" : "cursor-pointer"
          }`}
        >
          <input
            type="checkbox"
            checked={loggedIn && realtimeEnabled}
            onChange={(e) => {
              if (!loggedIn) {
                if (e.target.checked) {
                  onRequestLogin?.(() => onRealtimeEnabledChange(true));
                }
                return;
              }
              onRealtimeEnabledChange(e.target.checked);
            }}
            className="mt-0.5"
          />
          <span>
            <span className="font-medium">{t.toggleLabel}</span>
            <span className="block text-xs text-slate-500">{t.toggleHint}</span>
            {!loggedIn && (
              <button
                type="button"
                onClick={() =>
                  onRequestLogin?.(() => onRealtimeEnabledChange(true))
                }
                className="mt-1 block text-xs font-medium text-blue-600 hover:underline focus:outline-none"
              >
                {t.loginRequiredCta}
              </button>
            )}
          </span>
        </label>
        {loggedIn && realtimeEnabled && (
          <>
            <LiveSessionSourcePicker
              value={liveSessionSourceId}
              onChange={onLiveSessionSourceIdChange}
              disabled={realtimeStarted}
            />
            <label className="flex items-center gap-2 pl-5">
              <span className="flex-1 text-sm">{t.intervalLabel}</span>
              <span className="flex items-center gap-1.5">
                <IntervalSecondsInput
                  value={livePullIntervalSec}
                  min={livePullIntervalMin}
                  max={livePullIntervalMax}
                  onCommit={onLivePullIntervalSecChange}
                  className="h-9 w-20 rounded border border-slate-300 px-2 py-1 text-right text-sm [appearance:textfield] [&::-webkit-inner-spin-button]:m-0 [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:m-0 [&::-webkit-outer-spin-button]:appearance-none"
                />
                <span className="text-sm text-slate-600">{t.intervalUnit}</span>
              </span>
            </label>
            <label className="flex items-start gap-2 pl-5">
              <input
                type="checkbox"
                checked={autoFollowEnabled}
                onChange={(e) => onAutoFollowEnabledChange(e.target.checked)}
                className="mt-0.5"
              />
              <span>
                <span>{t.autoFollowLabel}</span>
                <span className="block text-xs text-slate-500">
                  {t.autoFollowHint}
                </span>
              </span>
            </label>
            <label className="flex items-start gap-2 pl-5">
              <input
                type="checkbox"
                checked={connectionLinesEnabled}
                onChange={(e) =>
                  onConnectionLinesEnabledChange(e.target.checked)
                }
                className="mt-0.5"
              />
              <span>
                <span>{t.connectionLinesLabel}</span>
                <span className="block text-xs text-slate-500">
                  {t.connectionLinesHint}
                </span>
              </span>
            </label>
            <label className="flex items-start gap-2 pl-5">
              <input
                type="checkbox"
                checked={onlyNewAfterStart}
                onChange={(e) => onOnlyNewAfterStartChange(e.target.checked)}
                className="mt-0.5"
              />
              <span>
                <span>{t.onlyNewLabel}</span>
                <span className="block text-xs text-slate-500">
                  {t.onlyNewHint}
                </span>
              </span>
            </label>
            <div className="flex flex-wrap gap-2 pl-5 pt-1">
              {!realtimeStarted ? (
                <button
                  type="button"
                  onClick={onStartWatching}
                  disabled={!canStart}
                  title={canStart ? undefined : t.viewButtonDisabledHint}
                  className="inline-flex items-center justify-center rounded-md border border-slate-300 bg-slate-900 px-3 py-1 text-xs font-medium text-white shadow-sm hover:bg-slate-800 focus:outline-none focus:ring-1 focus:ring-slate-500 disabled:cursor-not-allowed disabled:bg-slate-300"
                >
                  {t.viewButton}
                </button>
              ) : (
                <>
                  <button
                    type="button"
                    onClick={onChangeSource}
                    className="inline-flex items-center justify-center rounded-md border border-slate-300 bg-white px-3 py-1 text-xs font-medium text-slate-700 shadow-sm hover:bg-slate-50 focus:outline-none focus:ring-1 focus:ring-slate-500"
                  >
                    {t.changeSourceButton}
                  </button>
                  <button
                    type="button"
                    onClick={onStopWatching}
                    className="inline-flex items-center justify-center rounded-md border border-red-300 bg-white px-3 py-1 text-xs font-medium text-red-700 shadow-sm hover:bg-red-50 focus:outline-none focus:ring-1 focus:ring-red-500"
                  >
                    {t.stopButton}
                  </button>
                </>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
