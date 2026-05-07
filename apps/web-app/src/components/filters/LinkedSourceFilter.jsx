// @ts-check
// Sub-filter cho mode "me" — chọn 1 linked_source cụ thể (hoặc "Tất cả").
//
// Reuse query key ["sources"] đã được SourcesPage register; React Query
// dedupe → không gọi lại API nếu user đã mở tab "Nguồn dữ liệu". Khi user
// chưa mở tab đó thì query sẽ fetch mới — vẫn rẻ vì backend chỉ trả list
// nhỏ.
//
// Caller chịu trách nhiệm chỉ render component này khi mode === "me" và có
// user — không cần guard trong này.

import { useQuery } from "@tanstack/react-query";
import { listSources } from "../../sources/client.js";
import { strings } from "../../strings.js";

const t = strings.coverageMap.filters.linkedSource;

/**
 * @param {{
 *   value: string | null,
 *   onChange: (next: string | null) => void,
 * }} props
 */
export function LinkedSourceFilter({ value, onChange }) {
  const q = useQuery({
    queryKey: ["sources"],
    queryFn: listSources,
  });

  return (
    <div className="space-y-1">
      <label className="block text-xs font-semibold text-slate-700" htmlFor="linked-source-filter">
        {t.label}
      </label>
      <select
        id="linked-source-filter"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
        disabled={q.isPending || q.isError}
        className="w-full rounded-md border border-slate-300 px-2 py-1 text-xs shadow-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500 disabled:bg-slate-100"
      >
        <option value="">{t.optionAll}</option>
        {q.data?.items.map((s) => (
          <option key={s.id} value={s.id}>
            {s.label} ({s.source_type})
          </option>
        ))}
      </select>
      {q.isError && <div className="text-[11px] text-red-600">{t.errorLoad}</div>}
    </div>
  );
}
