// @ts-check
// Picker chọn linked_source để GHI dữ liệu cho 1 chuyến khảo sát trực tiếp
// (mig 0031). Khác LinkedSourceFilter (vốn là filter XEM): không có option
// "Tất cả nguồn" — live session cần 1 nguồn cụ thể để biết pull upstream từ
// đâu và gom rows vào batch nào.
//
// Chỉ liệt kê source status='active'; paused/failed không sync được nên không
// cho chọn. Reuse query key ["sources"] đã cache (LinkedSourceFilter dùng
// cùng query) để khỏi double fetch.

import { useQuery } from "@tanstack/react-query";
import { listSources } from "../../sources/client.js";
import { strings } from "../../strings.js";

const t = strings.coverageMap.filters.realtime;

/**
 * @param {{
 *   value: string | null,
 *   onChange: (next: string | null) => void,
 *   disabled?: boolean,
 * }} props
 */
export function LiveSessionSourcePicker({ value, onChange, disabled = false }) {
  const q = useQuery({
    queryKey: ["sources"],
    queryFn: listSources,
  });

  const activeSources = (q.data?.items ?? []).filter(
    (s) => s.status === "active",
  );

  return (
    <div className="space-y-1 pl-5">
      <label
        className="block text-xs font-semibold text-slate-700"
        htmlFor="live-session-source-picker"
      >
        {t.sourcePickerLabel}
      </label>
      <select
        id="live-session-source-picker"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
        disabled={disabled || q.isPending || q.isError || activeSources.length === 0}
        className="w-full rounded-md border border-slate-300 px-2 py-1 text-xs shadow-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500 disabled:bg-slate-100"
      >
        <option value="">{t.sourcePickerPlaceholder}</option>
        {activeSources.map((s) => (
          <option key={s.id} value={s.id}>
            {s.label} ({s.source_type})
          </option>
        ))}
      </select>
      <div className="text-[11px] text-slate-500">{t.sourcePickerHint}</div>
      {q.isError && (
        <div className="text-[11px] text-red-600">{t.sourcePickerErrorLoad}</div>
      )}
      {!q.isPending && !q.isError && activeSources.length === 0 && (
        <div className="text-[11px] text-amber-700">
          {t.sourcePickerNoActive}
        </div>
      )}
    </div>
  );
}
