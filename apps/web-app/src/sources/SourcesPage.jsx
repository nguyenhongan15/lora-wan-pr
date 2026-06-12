// @ts-check
// SourcesPage — sidebar trái + content phải. 6 mục: Tổng quan, Thêm nguồn,
// Nguồn đã liên kết, Tải lên CSV/JSON, Quản lý dữ liệu, Lịch sử upload.
// Mục active sync vào URL hash (`#tab=...`) → refresh giữ nguyên, share link
// đúng mục.
//
// Caller (App.jsx) đảm bảo chỉ render khi user logged in. 401 bất ngờ →
// authFetch clear store → App unmount SourcesPage, không cần redirect riêng.

import { useCallback, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ApiError } from "../auth/client.js";
import { fetchUploadOverview, listSources } from "./client.js";
import { AddSourceForm } from "./AddSourceForm.jsx";
import { DataManagementTable } from "./DataManagementTable.jsx";
import { LinkedSourceCard } from "./LinkedSourceCard.jsx";
import { UploadHistoryTable } from "./UploadHistoryTable.jsx";
import { ContributeUpload } from "../components/ContributeUpload.jsx";
import { strings } from "../strings.js";

const t = strings.sources.page;
const tErr = strings.sources.errors;
const tSide = strings.sources.sidebar;
const tSec = strings.sources.sections;
const tOver = strings.sources.overview;

/** @typedef {"overview" | "add" | "linked" | "upload" | "manage" | "history"} TabId */

/** @type {ReadonlyArray<{ id: TabId, label: string }>} */
const SECTIONS = [
  { id: "overview", label: tSide.overview },
  { id: "add", label: tSide.addSource },
  { id: "linked", label: tSide.linkedSources },
  { id: "upload", label: tSide.uploadFile },
  { id: "manage", label: tSide.dataManagement },
  { id: "history", label: tSide.uploadHistory },
];

const VALID_TABS = new Set(SECTIONS.map((s) => s.id));

/** Đọc `tab=...` từ hash. Fallback "overview" nếu thiếu/sai. */
function readTabFromHash() {
  if (typeof window === "undefined") return /** @type {TabId} */ ("overview");
  const params = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  const raw = params.get("tab");
  return raw && VALID_TABS.has(/** @type {TabId} */ (raw))
    ? /** @type {TabId} */ (raw)
    : /** @type {TabId} */ ("overview");
}

/** Ghi `tab=...` vào hash, GIỮ NGUYÊN các param khác (vd `page=sources` do App quản lý). */
function writeTabToHash(/** @type {TabId} */ next) {
  if (typeof window === "undefined") return;
  const params = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  params.set("page", "sources");
  params.set("tab", next);
  window.history.replaceState(null, "", `#${params.toString()}`);
}

export function SourcesPage() {
  const [tab, setTab] = useState(readTabFromHash);

  // Sync với back/forward navigation. Click trong sidebar dùng replaceState
  // để không spam history; back vẫn về tab trước qua hashchange event.
  useEffect(() => {
    function onHashChange() {
      setTab(readTabFromHash());
    }
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const navigate = useCallback((/** @type {TabId} */ next) => {
    writeTabToHash(next);
    setTab(next);
  }, []);

  return (
    <div className="mx-auto max-w-6xl p-4 md:p-6">
      <header>
        <h1 className="text-xl font-bold text-slate-900">{t.title}</h1>
        <p className="mt-1 text-sm text-slate-600">{t.subtitle}</p>
      </header>

      <div className="mt-4 md:hidden">
        <label
          htmlFor="src-tab-select"
          className="block text-xs font-medium text-slate-700"
        >
          {tSide.sectionLabel}
        </label>
        <select
          id="src-tab-select"
          value={tab}
          onChange={(e) => navigate(/** @type {TabId} */ (e.target.value))}
          className="mt-1 w-full rounded-md border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-slate-500 focus:ring-slate-500"
        >
          {SECTIONS.map((s) => (
            <option key={s.id} value={s.id}>
              {s.label}
            </option>
          ))}
        </select>
      </div>

      <div className="mt-4 md:grid md:grid-cols-[200px_1fr] md:gap-6">
        <nav aria-label={tSide.sectionLabel} className="hidden md:block">
          <ul className="space-y-1">
            {SECTIONS.map((s) => (
              <li key={s.id}>
                <button
                  type="button"
                  onClick={() => navigate(s.id)}
                  className={
                    tab === s.id
                      ? "w-full rounded-md bg-slate-900 px-3 py-2 text-left text-sm font-medium text-white"
                      : "w-full rounded-md px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-100"
                  }
                  aria-current={tab === s.id ? "page" : undefined}
                >
                  {s.label}
                </button>
              </li>
            ))}
          </ul>
        </nav>

        <main className="mt-4 space-y-4 md:mt-0">
          {tab === "overview" && <OverviewSection />}
          {tab === "add" && <AddSection />}
          {tab === "linked" && <LinkedSection />}
          {tab === "upload" && <UploadSection />}
          {tab === "manage" && <ManageSection />}
          {tab === "history" && <HistorySection />}
        </main>
      </div>
    </div>
  );
}

function OverviewSection() {
  const qSources = useQuery({ queryKey: ["sources"], queryFn: listSources });
  const qOverview = useQuery({
    queryKey: ["upload-overview"],
    queryFn: fetchUploadOverview,
  });

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <h2 className="text-base font-semibold text-slate-900">{tOver.title}</h2>
      <p className="mt-1 text-sm text-slate-600">{tOver.subtitle}</p>

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
          <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
            {tSide.linkedSources}
          </div>
          {qSources.isPending && (
            <p className="mt-2 text-sm text-slate-500">{tOver.loading}</p>
          )}
          {qSources.isError && <SourcesError error={qSources.error} />}
          {qSources.isSuccess && (
            <p className="mt-2 text-sm text-slate-700">
              {qSources.data.items.length === 0
                ? tOver.linkedEmpty
                : tOver.linkedCount(qSources.data.items.length)}
            </p>
          )}
        </div>

        <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
          <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
            {tOver.dataHeading}
          </div>
          {qOverview.isPending && (
            <p className="mt-2 text-sm text-slate-500">{tOver.loading}</p>
          )}
          {qOverview.data && qOverview.data.batches_total === 0 && (
            <p className="mt-2 text-sm text-slate-700">{tOver.dataEmpty}</p>
          )}
          {qOverview.data && qOverview.data.batches_total > 0 && (
            <div className="mt-2 space-y-1 text-sm text-slate-700">
              <div>
                {tOver.dataSummary(
                  qOverview.data.batches_total,
                  qOverview.data.points_total,
                )}
              </div>
              <div className="text-xs text-slate-500">
                {tOver.dataBreakdown(
                  qOverview.data.public_batches,
                  qOverview.data.pending_batches,
                  qOverview.data.private_batches,
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

function AddSection() {
  return (
    <section className="space-y-2">
      <header>
        <h2 className="text-lg font-semibold text-slate-900">
          {tSec.addTitle}
        </h2>
        <p className="text-sm text-slate-600">{tSec.addSubtitle}</p>
      </header>
      <AddSourceForm />
    </section>
  );
}

function LinkedSection() {
  const q = useQuery({ queryKey: ["sources"], queryFn: listSources });

  return (
    <section className="space-y-3">
      <header>
        <h2 className="text-lg font-semibold text-slate-900">
          {tSec.linkedTitle}
        </h2>
        <p className="text-sm text-slate-600">{tSec.linkedSubtitle}</p>
      </header>

      {q.isPending && (
        <div className="rounded-md border border-slate-200 bg-white p-4 text-sm text-slate-600">
          {t.loading}
        </div>
      )}

      {q.isError && <SourcesError error={q.error} />}

      {q.isSuccess && q.data.items.length === 0 && (
        <div className="rounded-md border border-dashed border-slate-300 bg-slate-50 p-4 text-center text-sm text-slate-600 md:p-6">
          {t.empty}
        </div>
      )}

      {q.isSuccess && q.data.items.length > 0 && (
        <div className="space-y-3">
          {q.data.items.map((s) => (
            <LinkedSourceCard
              key={s.id}
              source={s}
              allSources={q.data.items}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function UploadSection() {
  return (
    <section className="space-y-3">
      <header>
        <h2 className="text-lg font-semibold text-slate-900">
          {tSec.uploadTitle}
        </h2>
        <p className="text-sm text-slate-600">{tSec.uploadSubtitle}</p>
      </header>
      <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <ContributeUpload />
      </div>
    </section>
  );
}

function ManageSection() {
  return (
    <section className="space-y-3">
      <header>
        <h2 className="text-lg font-semibold text-slate-900">
          {tSec.manageTitle}
        </h2>
        <p className="text-sm text-slate-600">{tSec.manageSubtitle}</p>
      </header>
      <DataManagementTable />
    </section>
  );
}

function HistorySection() {
  return (
    <section className="space-y-3">
      <header>
        <h2 className="text-lg font-semibold text-slate-900">
          {tSec.historyTitle}
        </h2>
        <p className="text-sm text-slate-600">{tSec.historySubtitle}</p>
      </header>
      <UploadHistoryTable />
    </section>
  );
}

/** @param {{ error: unknown }} props */
function SourcesError({ error }) {
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
