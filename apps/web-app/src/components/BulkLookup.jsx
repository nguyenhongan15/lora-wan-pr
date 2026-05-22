// @ts-check
import { useMemo, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { ApiError, lookupCoverageBatch } from "../api/client.js";
import { strings } from "../strings.js";
import { DEFAULT_SF } from "./CoverageMap.config.js";

const t = strings.bulkLookup;
/** @type {Record<string, string>} */
const STATUS_LABEL = strings.coverageStatus;
/** @type {Record<string, string>} */
const BOTTLENECK_LABEL = t.bottleneck;

const SAMPLE_CSV = `label,address,latitude,longitude
"Nhà Đà Nẵng",,16.0544,108.2022
"Trụ sở HCM","Số 1 Lê Lợi, Q1, TP.HCM",,
"Cà Mau xa","Cà Mau",,
"Toạ độ DMS","16°03'15.8\\"N 108°12'07.9\\"E",,
`;

const MAX_BATCH_ROWS = 500;

/**
 * Chuẩn hoá decimal-comma kiểu VN ("16,0544") → "16.0544".
 * Chỉ chấp nhận pattern 1 dấu phẩy + chỉ digits → strict để không nuốt
 * nhầm CSV escape (tách cell). Trả raw string nếu không match.
 * @param {string} raw
 */
function normalizeDecimal(raw) {
  if (/^-?\d+,\d+$/.test(raw)) return raw.replace(",", ".");
  return raw;
}

/**
 * @typedef {{ label: string | null, address: string | null, latitude: number | null, longitude: number | null }} ParsedItem
 */

/**
 * Tokenize CSV theo state-machine 1 pass: hỗ trợ quoted cells (chứa dấu
 * phẩy, dấu nháy escape "", VÀ newline embedded). Khác với approach cũ
 * split-by-newline-rồi-parse — bị break khi cell có \n nội tại (Excel
 * export địa chỉ đa dòng).
 *
 * - Trim whitespace CHỈ với unquoted cells; quoted giữ nguyên (`"  X  "` →
 *   "  X  ") vì user có thể intentionally pad.
 * - Bỏ qua row toàn cell rỗng (trailing blank line).
 * @param {string} text
 * @returns {string[][]}
 */
function tokenizeCsv(text) {
  /** @type {string[][]} */
  const rows = [];
  /** @type {string[]} */
  let row = [];
  let cur = "";
  let inQuote = false;
  let quoted = false; // cell hiện tại từng được mở bằng "
  const n = text.length;
  for (let i = 0; i < n; i++) {
    const ch = text[i];
    if (inQuote) {
      if (ch === '"' && text[i + 1] === '"') {
        cur += '"';
        i++;
      } else if (ch === '"') {
        inQuote = false;
      } else {
        cur += ch; // bao gồm newline trong quote
      }
    } else if (ch === '"' && cur === "") {
      inQuote = true;
      quoted = true;
    } else if (ch === ",") {
      row.push(quoted ? cur : cur.trim());
      cur = "";
      quoted = false;
    } else if (ch === "\r" || ch === "\n") {
      if (ch === "\r" && text[i + 1] === "\n") i++;
      row.push(quoted ? cur : cur.trim());
      cur = "";
      quoted = false;
      rows.push(row);
      row = [];
    } else {
      cur += ch;
    }
  }
  // Flush cell + row cuối nếu có content (file không end-with-newline).
  if (cur.length > 0 || row.length > 0) {
    row.push(quoted ? cur : cur.trim());
    rows.push(row);
  }
  // Drop blank rows (all cells empty).
  return rows.filter((r) => r.some((c) => c.length > 0));
}

/**
 * @param {string} text
 * @returns {{ items: ParsedItem[], errors: string[] }}
 */
function parseCsv(text) {
  /** @type {string[]} */
  const errors = [];
  /** @type {ParsedItem[]} */
  const items = [];

  // Strip UTF-8 BOM (Excel/Google Sheets exports thường gắn \ufeff ở đầu;
  // không strip thì column đầu tên sẽ là "\ufeffaddress" → header detect fail).
  const cleaned = text.replace(/^\ufeff/, "");
  const rows = tokenizeCsv(cleaned);
  if (rows.length < 2) {
    errors.push(t.parse.headerRequired);
    return { items, errors };
  }

  const header = rows[0].map((s) => s.toLowerCase());
  const has = (/** @type {string} */ col) => header.includes(col);
  if (!has("address") && !has("latitude") && !has("longitude")) {
    errors.push(t.parse.noColumn);
    return { items, errors };
  }

  // Pre-check giới hạn 500 (BE Zod max, tránh request waste).
  const dataRowCount = rows.length - 1;
  if (dataRowCount > MAX_BATCH_ROWS) {
    errors.push(t.parse.tooManyRows(dataRowCount));
    return { items, errors };
  }

  for (let i = 1; i < rows.length; i++) {
    const cols = rows[i];
    // Lenient: cols < header → pad "" (Excel drop trailing empty cols).
    // cols > header → likely malformed quote / extra comma → reject.
    if (cols.length > header.length) {
      errors.push(t.parse.colCountMismatch(i + 1, cols.length, header.length));
      continue;
    }
    /** @type {Record<string, string>} */
    const row = {};
    header.forEach((h, j) => {
      row[h] = cols[j] ?? "";
    });
    const latRaw = normalizeDecimal(row.latitude ?? "");
    const lngRaw = normalizeDecimal(row.longitude ?? "");
    const latParsed = latRaw ? Number(latRaw) : null;
    const lngParsed = lngRaw ? Number(lngRaw) : null;

    // Range check: lat ∈ [-90,90], lng ∈ [-180,180]. Catch ở FE để không
    // tốn round-trip BE cho lỗi rõ ràng (vd: user dán nhầm cột).
    let latNum = null;
    let lngNum = null;
    if (latParsed !== null) {
      if (!Number.isFinite(latParsed) || latParsed < -90 || latParsed > 90) {
        errors.push(t.parse.rowError(i + 1, t.parse.latOutOfRange(latRaw)));
        continue;
      }
      latNum = latParsed;
    }
    if (lngParsed !== null) {
      if (!Number.isFinite(lngParsed) || lngParsed < -180 || lngParsed > 180) {
        errors.push(t.parse.rowError(i + 1, t.parse.lngOutOfRange(lngRaw)));
        continue;
      }
      lngNum = lngParsed;
    }
    // Partial coords (chỉ lat hoặc chỉ lng) → ambiguous, reject.
    if ((latNum === null) !== (lngNum === null)) {
      errors.push(t.parse.rowError(i + 1, t.parse.partialCoords));
      continue;
    }
    const addr = row.address ? row.address.trim() : "";
    // Phải có address HOẶC cặp lat+lng. Nếu không có cả 2 → row vô nghĩa.
    if (!addr && latNum === null) {
      errors.push(t.parse.rowError(i + 1, t.parse.emptyRow));
      continue;
    }
    items.push({
      label: row.label ? row.label.trim() || null : null,
      address: addr || null,
      latitude: latNum,
      longitude: lngNum,
    });
  }

  if (items.length === 0 && errors.length === 0) {
    errors.push(t.parse.noRecord);
  }
  return { items, errors };
}

/**
 * AbortError từ fetch khi user re-submit/reset. Không phải lỗi thực sự —
 * không show banner để tránh flicker đỏ khi mutation bị huỷ chủ động.
 * @param {unknown} err
 */
function isAbortError(err) {
  return err instanceof DOMException && err.name === "AbortError";
}

/**
 * CSV-injection safe escape. Excel/Sheets sẽ EXEC cell bắt đầu bằng = @ + -
 * (hoặc TAB/CR) khi mở file — attacker có thể nhúng formula qua label/address.
 * Prefix `'` (single-quote) là pattern chuẩn OWASP: Excel hiển thị nguyên text
 * và bỏ qua quote khi parse, không trigger formula engine.
 * @param {string} s
 */
function csvEscape(s) {
  if (s == null) return "";
  const safe = /^[=@+\-\t\r]/.test(s) ? `'${s}` : s;
  return /[",\n]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
}

/**
 * @typedef {{
 *   lat: number,
 *   lng: number,
 *   prediction: import("../api/client.js").PredictionT,
 *   sf: number,
 *   isAuto: boolean,
 *   label: string | null,
 * }} BulkHandoffPoint
 */

/**
 * @param {{
 *   onViewOnMap?: (points: BulkHandoffPoint[]) => void,
 * }} props
 */
export function BulkLookup({ onViewOnMap }) {
  const [csvText, setCsvText] = useState("");
  // Snapshot CSV tại thời điểm submit cuối. Khi user sửa csvText (paste/upload
  // file mới / edit textarea) mà chưa bấm "Tra cứu" lại → bảng vẫn show kết
  // quả cũ → banner cảnh báo stale. Null khi chưa submit lần nào.
  const [lastSubmittedCsv, setLastSubmittedCsv] = useState(
    /** @type {string | null} */ (null),
  );
  // Snapshot SF tại thời điểm submit. handoff sang Predict tab phải dùng giá
  // trị này, KHÔNG dùng `sf` hiện tại — nếu user đổi select sau khi có kết
  // quả thì popup ở Predict sẽ hiển thị SF sai (không khớp prediction).
  const [lastSubmittedSf, setLastSubmittedSf] = useState(
    /** @type {number | "auto" | null} */ (null),
  );
  // sf = "auto" → gửi DEFAULT_SF (12 = max sensitivity) cho BE, popup ở
  // Predict tab hiển thị recommended_sf thay vì SF dùng. Đồng convention với
  // sfPicker ở Predict tab.
  const [sf, setSf] = useState(/** @type {number | "auto"} */ ("auto"));
  // AbortController của request đang chạy. User submit nhanh 2 lần liên tiếp
  // (hoặc bấm "Xoá kết quả") → huỷ request cũ để BE không tốn xử lý serial
  // 500 item cho data sắp bị overwrite.
  const abortRef = useRef(/** @type {AbortController | null} */ (null));

  const parsed = useMemo(() => (csvText ? parseCsv(csvText) : null), [csvText]);

  const isAuto = sf === "auto";
  const sfForApi = isAuto ? DEFAULT_SF : sf;

  const m = useMutation({
    /** @param {ParsedItem[]} items */
    mutationFn: async (items) => {
      // Tạo controller ở đầu mutationFn (sau khi onSubmit đã abort cái cũ).
      // Lưu ref để onSubmit/onReset lần sau có thể huỷ.
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      return lookupCoverageBatch(
        {
          items: items.map((it) => ({
            label: it.label ?? undefined,
            address: it.address ?? undefined,
            latitude: it.latitude ?? undefined,
            longitude: it.longitude ?? undefined,
          })),
          spreading_factor: sfForApi,
          frequency_mhz: 923,
        },
        ctrl.signal,
      );
    },
  });

  /** @param {import("react").ChangeEvent<HTMLInputElement>} e */
  function onFile(e) {
    const f = e.target.files?.[0];
    if (!f) return;
    // Reset input value để user upload lại CHÍNH file đó vẫn trigger onChange.
    // Nếu không reset, browser nhớ filename và onChange im lặng (no-op).
    e.target.value = "";
    f.text().then(setCsvText);
  }

  function onSubmit() {
    if (!parsed || parsed.items.length === 0) return;
    // Huỷ request cũ nếu user re-submit nhanh (vd: chỉnh CSV trong khi đang
    // pending). Tránh 2 batch song song race onSuccess.
    abortRef.current?.abort();
    setLastSubmittedCsv(csvText);
    setLastSubmittedSf(sf);
    m.mutate(parsed.items);
  }

  function onReset() {
    abortRef.current?.abort();
    abortRef.current = null;
    setCsvText("");
    setLastSubmittedCsv(null);
    setLastSubmittedSf(null);
    m.reset();
  }

  // Stale = đã có kết quả (m.data) nhưng csvText hiện tại khác snapshot tại
  // thời điểm submit. Banner nhắc user bấm "Tra cứu" để refresh.
  const isStale = m.data != null && lastSubmittedCsv !== csvText;

  // Handoff dùng SNAPSHOT SF lúc submit, không phải `sf` state hiện tại.
  // Nếu user đổi select sau khi có kết quả, popup ở Predict tab sẽ hiển thị
  // SF khớp với prediction được tính ở BE.
  const handoffSf =
    lastSubmittedSf == null
      ? sfForApi
      : lastSubmittedSf === "auto"
        ? DEFAULT_SF
        : lastSubmittedSf;
  const handoffIsAuto = lastSubmittedSf === "auto";

  // Filter ok items có address (lat/lng) + prediction để build handoff cho
  // Predict tab. Bulk endpoint luôn populate address field cho ok items (kể
  // cả user-supplied coords: BE wrap thành "cache" provider).
  function viewBulkOnMap() {
    const data = m.data;
    if (!data || !onViewOnMap) return;
    /** @type {BulkHandoffPoint[]} */
    const points = [];
    for (const it of data.items) {
      if (it.status !== "ok" || !it.prediction || !it.address) continue;
      points.push({
        lat: it.address.latitude,
        lng: it.address.longitude,
        prediction: it.prediction,
        sf: handoffSf,
        isAuto: handoffIsAuto,
        label: it.label,
      });
    }
    if (points.length === 0) return;
    onViewOnMap(points);
  }

  // Đếm trước số điểm hợp lệ để disable nút khi 0.
  const viewableCount = m.data
    ? m.data.items.filter(
        (it) => it.status === "ok" && it.prediction && it.address,
      ).length
    : 0;

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
      "bottleneck",
      "uplink_rssi_dbm",
      "uplink_margin_db",
      "downlink_rssi_dbm",
      "downlink_margin_db",
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
      it.prediction?.bottleneck ?? "",
      it.prediction?.uplink?.rssi_dbm?.toFixed(1) ?? "",
      it.prediction?.uplink?.margin_db?.toFixed(1) ?? "",
      it.prediction?.downlink?.rssi_dbm?.toFixed(1) ?? "",
      it.prediction?.downlink?.margin_db?.toFixed(1) ?? "",
      csvEscape(it.error_code ?? ""),
      csvEscape(it.error_message ?? ""),
    ]);
    const csv = [header.join(","), ...rows.map((r) => r.join(","))].join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    // ISO timestamp (file-system safe): "2026-05-20T15-30-12". User dễ đọc
    // và sort theo tên = sort theo thời gian export. Date.now() (epoch ms)
    // technically đúng nhưng "1747750212345" không gợi ý gì cho người mở folder.
    const stamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    a.download = `coverage-batch-${stamp}.csv`;
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
            onChange={(e) => {
              const v = e.target.value;
              setSf(v === "auto" ? "auto" : Number(v));
            }}
            className="rounded-md border border-slate-300 px-2 py-1 text-sm"
          >
            <option value="auto">{t.fields.sfAuto}</option>
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
          {m.data && onViewOnMap && (
            <button
              type="button"
              onClick={viewBulkOnMap}
              disabled={viewableCount === 0}
              title={viewableCount === 0 ? t.viewOnMapEmpty : undefined}
              className="ml-2 rounded-md border border-slate-300 px-4 py-2 text-sm text-slate-700 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {t.viewOnMap}
            </button>
          )}
          {(m.data || csvText) && (
            <button
              type="button"
              onClick={onReset}
              className="ml-2 rounded-md border border-slate-300 px-4 py-2 text-sm text-slate-700 hover:bg-slate-100"
            >
              {t.reset}
            </button>
          )}
        </div>

        {m.isError && !isAbortError(m.error) && (
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
          {isStale && (
            <div className="border-b border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-900">
              {t.staleResults}
            </div>
          )}
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
                  <td className="px-3 py-2">
                    {it.prediction?.bottleneck ? (
                      <span
                        className={`rounded-full px-2 py-0.5 text-xs ${
                          it.prediction.bottleneck === "both_ok"
                            ? "bg-emerald-50 text-emerald-700"
                            : "bg-amber-50 text-amber-800"
                        }`}
                      >
                        {BOTTLENECK_LABEL[it.prediction.bottleneck]}
                      </span>
                    ) : (
                      "—"
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
