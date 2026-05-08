// @ts-check
// Sub-filter cho mode "me" — dropdown các device_id user từng upload, kèm
// số điểm để user nhận diện thiết bị. Backend `/api/v1/survey/me/devices`
// trả max 200 device sort theo count DESC.
//
// Khi `linkedSourceId` đổi, refetch để dropdown narrow theo source. Nếu
// device đang chọn không còn thuộc list mới → tự reset về null (gọi
// onChange) để URL state + queryKey nhất quán với UI.
//
// Caller chịu trách nhiệm chỉ render khi mode === "me" và có user.

import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { listMyDevices } from "../../api/client.js";
import { strings } from "../../strings.js";

const t = strings.coverageMap.filters.device;

/**
 * @param {{
 *   value: string | null,
 *   onChange: (next: string | null) => void,
 *   linkedSourceId: string | null,
 * }} props
 */
export function DeviceFilter({ value, onChange, linkedSourceId }) {
  const q = useQuery({
    queryKey: ["my-devices", linkedSourceId],
    queryFn: () =>
      listMyDevices({ linkedSourceId: linkedSourceId ?? undefined }),
  });

  // Auto-reset selection nếu device đang chọn không còn trong list (đổi
  // linked_source khiến device không thuộc source mới).
  useEffect(() => {
    if (!value || !q.data) return;
    const exists = q.data.items.some((d) => d.device_id === value);
    if (!exists) onChange(null);
  }, [value, q.data, onChange]);

  return (
    <div className="space-y-1">
      <label
        className="block text-xs font-semibold text-slate-700"
        htmlFor="device-filter"
      >
        {t.label}
      </label>
      <select
        id="device-filter"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
        disabled={q.isPending || q.isError}
        className="w-full rounded-md border border-slate-300 px-2 py-1 text-xs shadow-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500 disabled:bg-slate-100"
      >
        <option value="">{t.optionAll}</option>
        {q.data?.items.map((d) => (
          <option key={d.device_id} value={d.device_id}>
            {d.device_id} ({d.count})
          </option>
        ))}
      </select>
      {q.isError && <div className="text-[11px] text-red-600">{t.errorLoad}</div>}
      {q.data && q.data.items.length === 0 && (
        <div className="text-[11px] text-slate-500">{t.empty}</div>
      )}
    </div>
  );
}
