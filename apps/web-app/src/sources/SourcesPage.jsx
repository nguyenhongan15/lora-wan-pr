// @ts-check
// SourcesPage — container của Step 10. Header + AddSourceForm + list cards.
//
// Caller (App.jsx) đảm bảo chỉ render khi user logged in (tab gating). Trong
// trường hợp 401 chạy bất ngờ (token expire khi đang ở tab này), authFetch
// tự clear store → useSyncExternalStore ở App fire → App ẩn tab → unmount
// SourcesPage. Không cần redirect riêng.

import { useQuery } from "@tanstack/react-query";
import { ApiError } from "../auth/client.js";
import { listSources } from "./client.js";
import { AddSourceForm } from "./AddSourceForm.jsx";
import { LinkedSourceCard } from "./LinkedSourceCard.jsx";
import { strings } from "../strings.js";

const t = strings.sources.page;
const tErr = strings.sources.errors;

export function SourcesPage() {
  const q = useQuery({
    queryKey: ["sources"],
    queryFn: listSources,
  });

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-6">
      <header>
        <h1 className="text-xl font-bold text-slate-900">{t.title}</h1>
        <p className="mt-1 text-sm text-slate-600">{t.subtitle}</p>
      </header>

      <AddSourceForm />

      {q.isPending && (
        <div className="rounded-md border border-slate-200 bg-white p-4 text-sm text-slate-600">
          {t.loading}
        </div>
      )}

      {q.isError && <ListError error={q.error} />}

      {q.isSuccess && q.data.items.length === 0 && (
        <div className="rounded-md border border-dashed border-slate-300 bg-slate-50 p-6 text-center text-sm text-slate-600">
          {t.empty}
        </div>
      )}

      {q.isSuccess && q.data.items.length > 0 && (
        <div className="space-y-3">
          {q.data.items.map((s) => (
            <LinkedSourceCard key={s.id} source={s} />
          ))}
        </div>
      )}
    </div>
  );
}

/** @param {{ error: unknown }} props */
function ListError({ error }) {
  let msg = t.errorLoad;
  let code = "";
  if (error instanceof ApiError) {
    code = error.problem.code ?? "";
    const localized = tErr.byCode(code);
    msg = localized || error.problem.detail || error.problem.title || msg;
  }
  return (
    <div
      role="alert"
      className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-800"
    >
      <div className="font-semibold">{msg}</div>
      {code && (
        <div className="mt-1 text-xs text-red-600">
          {tErr.errorCodeLabel}: {code}
        </div>
      )}
    </div>
  );
}
