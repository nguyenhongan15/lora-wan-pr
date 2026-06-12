// @ts-check
// Bảng "Lịch sử upload" — read-only log mọi batch (bao gồm deleted).
// Share queryKey root ["upload-batches"] để invalidate đồng bộ với DataManagementTable.

import { useQuery } from "@tanstack/react-query";
import { listUploadBatches } from "./client.js";
import { strings } from "../strings.js";

const t = strings.uploadHistoryTable;
const tKind = strings.uploadKindLabel;
const tStatus = strings.batchStatusLabel;

/** @param {string} iso */
function formatTs(iso) {
  try {
    return new Date(iso).toLocaleString("vi-VN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export function UploadHistoryTable() {
  const q = useQuery({
    queryKey: ["upload-batches", "history"],
    queryFn: () => listUploadBatches({ includeDeleted: true }),
  });

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <h3 className="text-base font-semibold text-slate-900">{t.title}</h3>
      <p className="mt-1 text-sm text-slate-600">{t.subtitle}</p>

      {q.isPending && (
        <p className="mt-3 text-xs text-slate-500">{t.loading}</p>
      )}

      {q.isError && (
        <p className="mt-3 text-xs text-red-700">{t.errorLoad}</p>
      )}

      {q.data && q.data.length === 0 && (
        <p className="mt-3 text-xs text-slate-500">{t.empty}</p>
      )}

      {q.data && q.data.length > 0 && (
        <div className="mt-3 overflow-x-auto">
          <table className="min-w-full text-xs">
            <thead>
              <tr className="border-b border-slate-200 text-left text-slate-600">
                <th className="py-1.5 pr-3 font-medium">{t.headers[0]}</th>
                <th className="py-1.5 pr-3 font-medium">{t.headers[1]}</th>
                <th className="py-1.5 pr-3 text-right font-medium">
                  {t.headers[2]}
                </th>
                <th className="py-1.5 pr-3 font-medium">{t.headers[3]}</th>
                <th className="py-1.5 pr-3 font-medium">{t.headers[4]}</th>
              </tr>
            </thead>
            <tbody>
              {q.data.map((batch) => {
                const isDeleted =
                  batch.status === "deleted" || batch.deleted_at !== null;
                const displayStatus = isDeleted ? "deleted" : batch.status;
                return (
                  <tr
                    key={batch.id}
                    className={
                      isDeleted
                        ? "border-b border-slate-100 text-slate-400"
                        : "border-b border-slate-100 text-slate-700"
                    }
                  >
                    <td className="py-1.5 pr-3 whitespace-nowrap">
                      {formatTs(batch.uploaded_at)}
                    </td>
                    <td
                      className="py-1.5 pr-3 max-w-[200px] truncate"
                      title={batch.filename}
                    >
                      {batch.filename}
                    </td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">
                      {batch.points_count}
                    </td>
                    <td className="py-1.5 pr-3">{tKind[batch.kind]}</td>
                    <td className="py-1.5 pr-3">
                      <span className={_statusClass(displayStatus)}>
                        {tStatus[displayStatus]}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/** @param {"private"|"pending"|"public"|"rejected"|"deleted"} status */
function _statusClass(status) {
  switch (status) {
    case "private":
      return "rounded-full bg-slate-100 px-2 py-0.5 text-slate-700";
    case "pending":
      return "rounded-full bg-sky-100 px-2 py-0.5 text-sky-800";
    case "public":
      return "rounded-full bg-emerald-100 px-2 py-0.5 text-emerald-800";
    case "rejected":
      return "rounded-full bg-rose-100 px-2 py-0.5 text-rose-800";
    case "deleted":
      return "rounded-full bg-slate-100 px-2 py-0.5 text-slate-500 line-through";
    default:
      return "";
  }
}
