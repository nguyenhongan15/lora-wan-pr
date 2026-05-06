// @ts-check
import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { ApiError, lookupCoverageBatch } from "../api/client.js";
import { strings } from "../strings.js";

const t = strings.bulkLookup;
/** @type {Record<string, string>} */
const STATUS_LABEL = strings.coverageStatus;

const SAMPLE_CSV = `label,address,latitude,longitude
"Nhà Đà Nẵng",,16.0544,108.2022
"Trụ sở HCM","Số 1 Lê Lợi, Q1, TP.HCM",,
"Cà Mau xa","Cà Mau",,
"Toạ độ DMS","16°03'15.8\\"N 108°12'07.9\\"E",,
`;

/**
 * @typedef {{ label: string | null, address: string | null, latitude: number | null, longitude: number | null }} ParsedItem
 */

/**
 * @param {string} text
 * @returns {{ items: ParsedItem[], errors: string[] }}
 */
function parseCsv(text) {
  /** @type {string[]} */
  const errors = [];
  /** @type {ParsedItem[]} */
  const items = [];

  const lines = text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => l.length > 0);
  if (lines.length < 2) {
    errors.push(t.parse.headerRequired);
    return { items, errors };
  }

  // CSV parser nhỏ — hỗ trợ giá trị quoted ("…") để chứa dấu phẩy / escape.
  const header = splitCsvLine(lines[0]).map((s) => s.toLowerCase());
  const has = (col) => header.includes(col);
  if (!has("address") && !has("latitude") && !has("longitude")) {
    errors.push(t.parse.noColumn);
    return { items, errors };
  }

  for (let i = 1; i < lines.length; i++) {
    const cols = splitCsvLine(lines[i]);
    if (cols.length !== header.length) {
      errors.push(t.parse.colCountMismatch(i + 1, cols.length, header.length));
      continue;
    }
    /** @type {Record<string, string>} */
    const row = {};
    header.forEach((h, j) => {
      row[h] = cols[j] ?? "";
    });
    const latRaw = row.latitude;
    const lngRaw = row.longitude;
    const latNum = latRaw ? Number(latRaw) : null;
    const lngNum = lngRaw ? Number(lngRaw) : null;
    items.push({
      label: row.label || null,
      address: row.address || null,
      latitude: latNum != null && Number.isFinite(latNum) ? latNum : null,
      longitude: lngNum != null && Number.isFinite(lngNum) ? lngNum : null,
    });
  }

  if (items.length === 0) errors.push(t.parse.noRecord);
  return { items, errors };
}

/** @param {string} line */
function splitCsvLine(line) {
  /** @type {string[]} */
  const out = [];
  let cur = "";
  let inQuote = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (inQuote) {
      if (ch === '"' && line[i + 1] === '"') {
        cur += '"';
        i++;
      } else if (ch === '"') {
        inQuote = false;
      } else {
        cur += ch;
      }
    } else if (ch === '"') {
      inQuote = true;
    } else if (ch === ",") {
      out.push(cur.trim());
      cur = "";
    } else {
      cur += ch;
    }
  }
  out.push(cur.trim());
  return out;
}

/** @param {string} s */
function csvEscape(s) {
  if (s == null) return "";
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function BulkLookup() {
  const [csvText, setCsvText] = useState("");
  const [sf, setSf] = useState(7);

  const parsed = useMemo(() => (csvText ? parseCsv(csvText) : null), [csvText]);

  const m = useMutation({
    /** @param {ParsedItem[]} items */
    mutationFn: async (items) =>
      lookupCoverageBatch({
        items: items.map((it) => ({
          label: it.label ?? undefined,
          address: it.address ?? undefined,
          latitude: it.latitude ?? undefined,
          longitude: it.longitude ?? undefined,
        })),
        spreading_factor: sf,
        frequency_mhz: 923,
      }),
  });

  /** @param {import("react").ChangeEvent<HTMLInputElement>} e */
  function onFile(e) {
    const f = e.target.files?.[0];
    if (!f) return;
    f.text().then(setCsvText);
  }

  function onSubmit() {
    if (!parsed || parsed.items.length === 0) return;
    m.mutate(parsed.items);
  }

  function downloadCsv() {
    const data = m.data;
    if (!data) return;
    const header = [
      "label",
      "status",
      "address",
      "latitude",
      "longitude",
      "rssi_dbm",
      "snr_db",
      "coverage_status",
      "recommended_sf",
      "error_code",
      "error_message",
    ];
    const rows = data.items.map((it) => [
      csvEscape(it.label ?? ""),
      it.status,
      csvEscape(it.address?.display_name ?? ""),
      it.address?.latitude?.toString() ?? "",
      it.address?.longitude?.toString() ?? "",
      it.prediction?.rssi_dbm?.toFixed(1) ?? "",
      it.prediction?.snr_db?.toFixed(1) ?? "",
      it.prediction?.coverage_status ?? "",
      it.prediction?.recommended_sf?.toString() ?? "",
      csvEscape(it.error_code ?? ""),
      csvEscape(it.error_message ?? ""),
    ]);
    const csv = [header.join(","), ...rows.map((r) => r.join(","))].join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `coverage-batch-${Date.now()}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
      <h2 className="text-xl font-semibold text-slate-900">{t.title}</h2>
      <p className="mt-1 text-sm text-slate-600">{t.description}</p>

      <div className="mt-6 grid gap-4 rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-wrap items-center gap-3">
          <label className="text-sm font-medium text-slate-700">
            {t.fields.file}
          </label>
          <input
            type="file"
            accept=".csv,text/csv"
            onChange={onFile}
            className="text-sm"
          />
          <label className="ml-4 text-sm font-medium text-slate-700">
            {t.fields.sf}
          </label>
          <select
            value={sf}
            onChange={(e) => setSf(Number(e.target.value))}
            className="rounded-md border border-slate-300 px-2 py-1 text-sm"
          >
            {[7, 8, 9, 10, 11, 12].map((v) => (
              <option key={v} value={v}>
                SF{v}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => setCsvText(SAMPLE_CSV)}
            className="ml-auto rounded-md border border-slate-300 px-3 py-1 text-xs text-slate-700 hover:bg-slate-100"
          >
            {t.sampleCsv}
          </button>
        </div>

        <div>
          <label className="text-sm font-medium text-slate-700">
            {t.fields.csv}
          </label>
          <textarea
            value={csvText}
            onChange={(e) => setCsvText(e.target.value)}
            rows={8}
            spellCheck={false}
            className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1 font-mono text-xs"
          />
          <p className="mt-1 text-xs text-slate-500">{t.csvHint}</p>
        </div>

        {parsed && parsed.errors.length > 0 && (
          <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900">
            <div className="font-semibold">{t.parseErrorTitle}</div>
            <ul className="mt-1 list-disc pl-4">
              {parsed.errors.slice(0, 5).map((e, i) => (
                <li key={i}>{e}</li>
              ))}
            </ul>
          </div>
        )}

        {parsed && parsed.items.length > 0 && (
          <div className="text-sm text-slate-600">
            {t.previewCount(parsed.items.length)}
          </div>
        )}

        <div>
          <button
            type="button"
            onClick={onSubmit}
            disabled={
              m.isPending ||
              !parsed ||
              parsed.items.length === 0 ||
              parsed.errors.length > 0
            }
            className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-slate-800 disabled:opacity-50"
          >
            {m.isPending ? t.submitPending : t.submit}
          </button>
          {m.data && (
            <button
              type="button"
              onClick={downloadCsv}
              className="ml-2 rounded-md border border-slate-300 px-4 py-2 text-sm text-slate-700 hover:bg-slate-100"
            >
              {t.download}
            </button>
          )}
        </div>

        {m.isError && (
          <div className="rounded-md border border-red-300 bg-red-50 p-3 text-xs text-red-800">
            {m.error instanceof ApiError ? (
              <>
                <div className="font-semibold">{m.error.problem.title}</div>
                {m.error.problem.detail && (
                  <div className="mt-0.5">{m.error.problem.detail}</div>
                )}
              </>
            ) : (
              String(m.error)
            )}
          </div>
        )}
      </div>

      {m.data && (
        <div className="mt-6 overflow-x-auto rounded-lg border border-slate-200 bg-white shadow-sm">
          <div className="border-b border-slate-200 px-4 py-2 text-sm text-slate-600">
            {t.summary.counts(m.data.ok_count, m.data.error_count)}
          </div>
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                {t.table.headers.map((h) => (
                  <th key={h} className="px-3 py-2 text-left">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {m.data.items.map((it, i) => (
                <tr key={i} className="border-t border-slate-100">
                  <td className="px-3 py-2 text-slate-500">{i + 1}</td>
                  <td className="px-3 py-2">{it.label ?? "—"}</td>
                  <td className="px-3 py-2 text-xs text-slate-700">
                    {it.address?.display_name ?? "—"}
                  </td>
                  <td className="px-3 py-2">
                    {it.status === "ok" && it.prediction ? (
                      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-700">
                        {STATUS_LABEL[it.prediction.coverage_status]}
                      </span>
                    ) : (
                      <span className="rounded-full bg-red-50 px-2 py-0.5 text-xs text-red-700">
                        {it.error_code ?? t.table.error}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 font-mono text-xs">
                    {it.prediction ? `${it.prediction.rssi_dbm.toFixed(1)} dBm` : "—"}
                  </td>
                  <td className="px-3 py-2 font-mono text-xs">
                    {it.prediction ? `${it.prediction.snr_db.toFixed(1)} dB` : "—"}
                  </td>
                  <td className="px-3 py-2 font-mono text-xs">
                    {it.prediction ? `SF${it.prediction.recommended_sf}` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
