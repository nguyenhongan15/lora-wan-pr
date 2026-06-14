// @ts-check
// Panel "Theo dõi trực tiếp" — tách icon + body để icon nằm trong
// icons-column ở CoverageMap, không bị panel filter push xuống khi mở.

import { strings } from "../../strings.js";
import { LiveSessionSourcePicker } from "./LiveSessionSourcePicker.jsx";

const t = strings.coverageMap.filters.realtime;

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
 *   autoFollowEnabled: boolean,
 *   onAutoFollowEnabledChange: (v: boolean) => void,
 *   liveOnlyEnabled: boolean,
 *   onLiveOnlyEnabledChange: (v: boolean) => void,
 *   liveSessionSourceId: string | null,
 *   onLiveSessionSourceIdChange: (v: string | null) => void,
 *   liveSessionActive: boolean,
 * }} props
 */
export function RealtimeBody({
  user,
  onRequestLogin,
  realtimeEnabled,
  onRealtimeEnabledChange,
  autoFollowEnabled,
  onAutoFollowEnabledChange,
  liveOnlyEnabled,
  onLiveOnlyEnabledChange,
  liveSessionSourceId,
  onLiveSessionSourceIdChange,
  liveSessionActive,
}) {
  const loggedIn = !!user;

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
              // Guest tick → ép login. Sau login thành công, App.jsx fire
              // afterLogin để auto-tick. User huỷ login → giữ false.
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
              disabled={liveSessionActive}
            />
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
                checked={liveOnlyEnabled}
                onChange={(e) => onLiveOnlyEnabledChange(e.target.checked)}
                className="mt-0.5"
              />
              <span>
                <span>{t.liveOnlyLabel}</span>
                <span className="block text-xs text-slate-500">
                  {t.liveOnlyHint}
                </span>
              </span>
            </label>
          </>
        )}
      </div>
    </div>
  );
}
