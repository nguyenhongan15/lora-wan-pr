// @ts-check
import { useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { ApiError } from "../auth/client.js";
import { uploadMeasurementsCsv } from "../sources/client.js";
import { strings } from "../strings.js";

const t = strings.contributeUpload;

const MAX_FILE_BYTES = 1_048_576;

export function ContributeUpload() {
  const [file, setFile] = useState(/** @type {File | null} */ (null));
  const [clientError, setClientError] = useState(/** @type {string | null} */ (null));
  const inputRef = useRef(/** @type {HTMLInputElement | null} */ (null));

  // Upload luôn tạo batch private. User opt-in cộng đồng sau bằng nút "Đóng góp"
  // ở bảng "Quản lý dữ liệu".
  const m = useMutation({
    /** @param {{ file: File }} args */
    mutationFn: ({ file }) => uploadMeasurementsCsv(file),
  });

  /** @param {import("react").ChangeEvent<HTMLInputElement>} e */
  function onFile(e) {
    const f = e.target.files?.[0] ?? null;
    setClientError(null);
    m.reset();
    if (!f) {
      setFile(null);
      return;
    }
    if (f.size > MAX_FILE_BYTES) {
      setClientError(t.errors.fileTooLarge);
      setFile(null);
      e.target.value = "";
      return;
    }
    setFile(f);
  }

  function onSubmit() {
    if (!file) {
      setClientError(t.errors.fileEmpty);
      return;
    }
    setClientError(null);
    m.mutate({ file });
  }

  function onReset() {
    setFile(null);
    setClientError(null);
    m.reset();
    if (inputRef.current) inputRef.current.value = "";
  }

  const result = m.data;

  return (
    <section>
      <div className="grid gap-4">
        <div>
          <label className="text-sm font-medium text-slate-700">
            {t.fields.file}
          </label>
          <input
            ref={inputRef}
            type="file"
            accept=".csv,.json,text/csv,application/json"
            onChange={onFile}
            className="mt-1 block text-sm"
          />
          <p className="mt-1 text-xs text-slate-500">
            {file ? t.fileSelected(file.name, file.size) : t.noFileSelected}
          </p>
          <p className="mt-2 text-xs text-slate-500">{t.csvHint}</p>
        </div>

        {clientError && (
          <div className="rounded-md border border-red-300 bg-red-50 p-3 text-xs text-red-800">
            {clientError}
          </div>
        )}

        <div>
          <button
            type="button"
            onClick={onSubmit}
            disabled={m.isPending || !file}
            className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-slate-800 disabled:opacity-50"
          >
            {m.isPending ? t.submitPending : t.submit}
          </button>
          {(file || result) && (
            <button
              type="button"
              onClick={onReset}
              className="ml-2 rounded-md border border-slate-300 px-4 py-2 text-sm text-slate-700 hover:bg-slate-100"
            >
              {t.reset}
            </button>
          )}
        </div>

        {m.isError && (
          <div className="rounded-md border border-red-300 bg-red-50 p-3 text-xs text-red-800">
            <div className="font-semibold">{t.errors.title}</div>
            <div className="mt-0.5">
              {m.error instanceof ApiError
                ? m.error.problem.detail || m.error.problem.title
                : String(m.error)}
            </div>
          </div>
        )}
      </div>

      {result && (
        <div className="mt-6 rounded-lg border border-slate-200 bg-white p-4 shadow-sm md:p-6">
          <div className="text-sm font-semibold text-slate-900">
            {t.summary.title}
          </div>
          <ul className="mt-3 space-y-1 text-sm text-slate-700">
            <li>• {t.summary.parsed(result.parsed_count)}</li>
            {result.parse_rejected_count > 0 && (
              <li className="text-amber-700">
                • {t.summary.parseRejected(result.parse_rejected_count)}
              </li>
            )}
            <li>• {t.summary.inserted(result.inserted_count)}</li>
          </ul>

          {result.parse_rejected_reasons.length > 0 && (
            <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
              <div className="font-semibold">{t.parseErrorTitle}</div>
              <ul className="mt-1 list-disc pl-4">
                {result.parse_rejected_reasons.slice(0, 20).map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
