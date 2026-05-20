// @ts-check
// DevicesPanel — list devices đã sync của 1 linked source.
//
// Component-level state: chỉ giữ pagination offset. Data lấy qua TanStack
// Query với key ["devices", id] — invalidate khi sync xong (LinkedSourceCard
// đã invalidate ["surveys"] + ["sources"]; thêm ["devices"] vào syncM
// onSuccess để DevicesPanel tự refetch).
//
// Empty/loading/error pattern follows existing SourcesPage/LinkedSourceCard.

import { useQuery } from "@tanstack/react-query";
import { ApiError } from "../auth/client.js";
import { listDevices } from "./client.js";
import { strings } from "../strings.js";

const t = strings.sources.devices;
const tErr = strings.sources.errors;

const PAGE_SIZE = 50;

/** @param {{ linkedSourceId: string }} props */
export function DevicesPanel({ linkedSourceId }) {
  const q = useQuery({
    queryKey: ["devices", linkedSourceId],
    queryFn: () => listDevices(linkedSourceId, { limit: PAGE_SIZE, offset: 0 }),
  });

  if (q.isPending) {
    return (
      <div className="rounded-md border border-slate-200 bg-slate-50 p-3 text-sm text-slate-600">
        {t.loading}
      </div>
    );
  }

  if (q.isError) {
    const msg =
      q.error instanceof ApiError
        ? tErr.byCode(q.error.problem.code ?? "") ||
          q.error.problem.detail ||
          q.error.problem.title
        : t.errorLoad;
    return (
      <div
        role="alert"
        className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-800"
      >
        {msg}
      </div>
    );
  }

  const { items, total } = q.data;

  if (items.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-slate-300 bg-slate-50 p-3 text-center text-sm text-slate-600">
        {t.empty}
      </div>
    );
  }

  return (
    <section className="rounded-md border border-slate-200 bg-white p-3">
      <header className="mb-2 flex items-center justify-between">
        <h4 className="text-sm font-semibold text-slate-900">{t.heading}</h4>
        <span className="text-xs text-slate-500">{t.total(total)}</span>
      </header>
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead className="text-left text-xs font-medium text-slate-500">
            <tr>
              {t.headers.map((h) => (
                <th key={h} className="px-2 py-1">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {items.map((d) => (
              <tr
                key={d.id}
                className="border-t border-slate-100 text-slate-800"
              >
                <td className="px-2 py-1 font-mono text-xs">{d.dev_eui}</td>
                <td className="px-2 py-1">{d.name ?? "—"}</td>
                <td className="px-2 py-1 text-xs text-slate-600">
                  {d.last_seen_at
                    ? new Date(d.last_seen_at).toLocaleString("vi-VN")
                    : t.lastSeenNever}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
