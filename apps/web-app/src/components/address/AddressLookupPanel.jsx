// @ts-check
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { ApiError, lookupCoverageByAddress } from "../../api/client.js";
import { strings } from "../../strings.js";

/**
 * Sub-tab "Nhập địa chỉ" trong Predict panel. Mỗi lần submit thành công →
 * gọi `onResolved` để parent (CoverageMap) vẽ marker, flyTo, ghi URL state.
 * Marker tích lũy giữa các lần submit — clear chung với "1 điểm" qua
 * `clearAllSearchMarkers` (parent truyền `onClear`).
 *
 * BE endpoint /coverage/lookup không nhận `environment` → các điểm tra cứu
 * qua sub-tab này luôn outdoor. User cần indoor thì dùng sub-tab "1 điểm".
 *
 * @param {{
 *   onResolved: (r: {
 *     lat: number,
 *     lng: number,
 *     displayName: string,
 *     prediction: import("../../api/client.js").PredictionT,
 *   }) => void,
 *   markerCount: number,
 *   onClear: () => void,
 * }} props
 */
export function AddressLookupPanel({ onResolved, markerCount, onClear }) {
  const t = strings.coverageMap.predictPanel.addressTab;
  const [address, setAddress] = useState("");

  const m = useMutation({
    mutationFn: lookupCoverageByAddress,
    onSuccess: (data) => {
      onResolved({
        lat: data.address.latitude,
        lng: data.address.longitude,
        displayName: data.address.display_name,
        prediction: data.prediction,
      });
      setAddress("");
    },
  });

  /** @param {import("react").FormEvent} e */
  function onSubmit(e) {
    e.preventDefault();
    const trimmed = address.trim();
    if (!trimmed || m.isPending) return;
    m.mutate({ address: trimmed, spreading_factor: 7, frequency_mhz: 923 });
  }

  const submitDisabled = m.isPending || address.trim().length === 0;

  return (
    <form onSubmit={onSubmit} className="space-y-2">
      <div>
        <label className="text-[11px] font-medium text-slate-700">
          {t.label}
        </label>
        <input
          type="text"
          value={address}
          onChange={(e) => setAddress(e.target.value)}
          placeholder={t.placeholder}
          className="mt-0.5 w-full rounded-md border border-slate-300 px-2 py-1 text-[11px] shadow-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
        />
        <p className="mt-0.5 text-[10px] leading-snug text-slate-500">
          {t.hint}
        </p>
      </div>

      <button
        type="submit"
        disabled={submitDisabled}
        className="w-full rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white shadow-sm transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300"
      >
        {m.isPending ? t.submitting : t.submit}
      </button>

      <button
        type="button"
        onClick={onClear}
        disabled={markerCount === 0}
        className="w-full rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 shadow-sm transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:border-slate-200 disabled:text-slate-400"
      >
        {strings.coverageMap.predictPanel.clearAll}
        {markerCount > 0 ? ` (${markerCount})` : ""}
      </button>

      {m.isError && (
        <div className="rounded-md border border-red-300 bg-red-50 px-2 py-1 text-[10px] text-red-800">
          {m.error instanceof ApiError ? (
            <>
              <div className="font-semibold">{m.error.problem.title}</div>
              {m.error.problem.detail && (
                <div className="mt-0.5">{m.error.problem.detail}</div>
              )}
            </>
          ) : (
            <div>{t.error}</div>
          )}
        </div>
      )}
    </form>
  );
}
