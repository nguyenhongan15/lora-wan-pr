// @ts-check
// Admin manual review queue — gom theo file CSV (batch = 1 lần user upload).
// Default view: danh sách batch. Mỗi batch = 1 dòng (uploader + uploaded_at)
// với nút Duyệt-cả-file / Từ chối-cả-file / Xem-bản-đồ.
//
// Drill-in: nhấn "Xem bản đồ" mở modal hiển thị toàn bộ điểm trên 1 map
// (maplibre GeoJSON layer, scalable cho batch lớn 1000+ điểm). Click marker
// → popup chi tiết 1 điểm. KHÔNG còn per-row approve/reject — admin chỉ
// thao tác cấp batch (đúng pattern khi file lớn).
//
// Approve cả batch → backend gửi 1 email summary đến uploader.

import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import maplibregl from "maplibre-gl";
import { ApiError } from "../auth/client.js";
import {
  approveBatch,
  listBatchRows,
  listPendingBatches,
  rejectBatch,
} from "./client.js";
import { strings } from "../strings.js";

const t = strings.admin.review;
const tErr = strings.admin.errors;
const tb = t.batch;

/**
 * @param {string|null} sourceType
 */
function _sourceLabel(sourceType) {
  if (sourceType === "csv_upload") return t.sourceCsv;
  if (sourceType && sourceType !== "unknown") return t.sourceWebhook;
  return t.sourceUnknown;
}

/**
 * @param {string} iso
 */
function _formatTime(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("vi-VN", { hour12: false });
}

/**
 * @param {string} earliest @param {string} latest
 */
function _formatRange(earliest, latest) {
  return `${_formatTime(earliest)} → ${_formatTime(latest)}`;
}

export function ContributionReviewPanel() {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["admin", "pending", "batches"],
    queryFn: () => listPendingBatches(),
  });

  const [drillIn, setDrillIn] = useState(
    /** @type {{ uploader_id: string, uploaded_at: string, uploader_email: string | null } | null} */ (
      null
    ),
  );

  const [confirmBatch, setConfirmBatch] = useState(
    /** @type {{ kind: "approve" | "reject", uploader_id: string, uploaded_at: string, pending: number } | null} */ (
      null
    ),
  );
  const [rejectBatchNote, setRejectBatchNote] = useState("");

  const invalidateAll = () => {
    qc.invalidateQueries({ queryKey: ["admin", "pending", "batches"] });
    qc.invalidateQueries({ queryKey: ["admin", "pending", "batch"] });
    qc.invalidateQueries({ queryKey: ["admin", "stats"] });
  };

  const approveBatchM = useMutation({
    mutationFn: (
      /** @type {{ uploader_id: string, uploaded_at: string }} */ vars,
    ) => approveBatch(vars.uploader_id, vars.uploaded_at),
    onSuccess: () => {
      invalidateAll();
      setConfirmBatch(null);
      setDrillIn(null);
    },
  });

  const rejectBatchM = useMutation({
    mutationFn: (
      /** @type {{ uploader_id: string, uploaded_at: string, note: string | null }} */ vars,
    ) => rejectBatch(vars.uploader_id, vars.uploaded_at, vars.note),
    onSuccess: () => {
      invalidateAll();
      setConfirmBatch(null);
      setRejectBatchNote("");
      setDrillIn(null);
    },
  });

  if (q.isPending) {
    return (
      <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 px-3 py-6 text-center text-sm text-slate-500">
        {t.loading}
      </div>
    );
  }
  if (q.isError) {
    return <ReviewError error={q.error} fallback={tb.errorLoad} />;
  }

  const batches = q.data.items;
  if (batches.length === 0) {
    return (
      <div className="rounded-lg border border-slate-200 bg-white px-3 py-6 text-center text-sm text-slate-500">
        {tb.empty}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="text-xs text-slate-500">
        {tb.heading} — {batches.length}
      </div>

      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-600">
            <tr>
              {tb.headers.map((h, i) => (
                <th key={i} className="px-3 py-2">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {batches.map((b) => {
              const key = `${b.uploader_id}|${b.uploaded_at}`;
              const busy =
                (approveBatchM.isPending &&
                  approveBatchM.variables?.uploader_id === b.uploader_id &&
                  approveBatchM.variables?.uploaded_at === b.uploaded_at) ||
                (rejectBatchM.isPending &&
                  rejectBatchM.variables?.uploader_id === b.uploader_id &&
                  rejectBatchM.variables?.uploaded_at === b.uploaded_at);
              return (
                <tr key={key} className="hover:bg-slate-50">
                  <td className="px-3 py-2 text-slate-700">
                    {b.uploader_email ?? "—"}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-slate-700">
                    {_formatTime(b.uploaded_at)}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-slate-700">
                    {tb.countLabel(b.pending_review_count, b.total_count)}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-xs text-slate-600">
                    {_formatRange(b.earliest_timestamp, b.latest_timestamp)}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-right">
                    <div className="flex justify-end gap-1">
                      <button
                        type="button"
                        onClick={() =>
                          setDrillIn({
                            uploader_id: b.uploader_id,
                            uploaded_at: b.uploaded_at,
                            uploader_email: b.uploader_email,
                          })
                        }
                        className="rounded border border-slate-300 px-2 py-1 text-xs hover:bg-slate-100"
                      >
                        {tb.btnViewRows}
                      </button>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() =>
                          setConfirmBatch({
                            kind: "approve",
                            uploader_id: b.uploader_id,
                            uploaded_at: b.uploaded_at,
                            pending: b.pending_review_count,
                          })
                        }
                        className="rounded bg-emerald-600 px-2 py-1 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
                      >
                        {tb.btnApproveBatch}
                      </button>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => {
                          setRejectBatchNote("");
                          setConfirmBatch({
                            kind: "reject",
                            uploader_id: b.uploader_id,
                            uploaded_at: b.uploaded_at,
                            pending: b.pending_review_count,
                          });
                        }}
                        className="rounded bg-red-600 px-2 py-1 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50"
                      >
                        {tb.btnRejectBatch}
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {(approveBatchM.isError || rejectBatchM.isError) && (
        <ReviewError
          error={approveBatchM.error ?? rejectBatchM.error}
          fallback={tErr.reviewActionFailed}
        />
      )}

      {drillIn && (
        <BatchMapModal
          uploaderId={drillIn.uploader_id}
          uploadedAt={drillIn.uploaded_at}
          uploaderEmail={drillIn.uploader_email}
          onClose={() => setDrillIn(null)}
          onApprove={(pending) =>
            setConfirmBatch({
              kind: "approve",
              uploader_id: drillIn.uploader_id,
              uploaded_at: drillIn.uploaded_at,
              pending,
            })
          }
          onReject={(pending) => {
            setRejectBatchNote("");
            setConfirmBatch({
              kind: "reject",
              uploader_id: drillIn.uploader_id,
              uploaded_at: drillIn.uploaded_at,
              pending,
            });
          }}
        />
      )}

      {confirmBatch && confirmBatch.kind === "approve" && (
        <ConfirmModal
          title={t.confirm.title}
          message={tb.confirm.approve(confirmBatch.pending)}
          confirmLabel={tb.btnApproveBatch}
          confirmClass="bg-emerald-600 hover:bg-emerald-700"
          onCancel={() => setConfirmBatch(null)}
          onConfirm={() =>
            approveBatchM.mutate({
              uploader_id: confirmBatch.uploader_id,
              uploaded_at: confirmBatch.uploaded_at,
            })
          }
          pending={approveBatchM.isPending}
        />
      )}

      {confirmBatch && confirmBatch.kind === "reject" && (
        <RejectModal
          title={t.confirm.title}
          message={tb.confirm.reject(confirmBatch.pending)}
          note={rejectBatchNote}
          onNoteChange={setRejectBatchNote}
          onCancel={() => {
            setConfirmBatch(null);
            setRejectBatchNote("");
          }}
          onConfirm={() =>
            rejectBatchM.mutate({
              uploader_id: confirmBatch.uploader_id,
              uploaded_at: confirmBatch.uploaded_at,
              note: rejectBatchNote || null,
            })
          }
          pending={rejectBatchM.isPending}
        />
      )}
    </div>
  );
}

/**
 * Drill-in modal: hiển thị toàn batch trên 1 map (maplibre GeoJSON circle
 * layer) — scale tốt cho batch ngàn điểm. Click marker → popup chi tiết.
 * Approve/Reject ở footer kích hoạt ConfirmModal/RejectModal của parent.
 *
 * @param {{
 *   uploaderId: string,
 *   uploadedAt: string,
 *   uploaderEmail: string | null,
 *   onClose: () => void,
 *   onApprove: (pending: number) => void,
 *   onReject: (pending: number) => void,
 * }} props
 */
function BatchMapModal({
  uploaderId,
  uploadedAt,
  uploaderEmail,
  onClose,
  onApprove,
  onReject,
}) {
  const q = useQuery({
    queryKey: ["admin", "pending", "batch", uploaderId, uploadedAt],
    queryFn: () => listBatchRows(uploaderId, uploadedAt),
  });

  const mapDiv = useRef(/** @type {HTMLDivElement | null} */ (null));
  const mapRef = useRef(/** @type {maplibregl.Map | null} */ (null));
  const popupRef = useRef(/** @type {maplibregl.Popup | null} */ (null));
  const [selected, setSelected] = useState(
    /** @type {import("./client.js").PendingContributionT | null} */ (null),
  );

  const items = q.data?.items ?? [];

  // Init map CHỈ khi container đã visible và có data → tránh tạo map khi
  // div còn display:none (size 0×0) làm canvas mãi mãi sai.
  const mapReady = q.isSuccess && items.length > 0;
  useEffect(() => {
    const el = mapDiv.current;
    if (!el || mapRef.current || !mapReady) return;
    const map = new maplibregl.Map({
      container: el,
      style: {
        version: 8,
        sources: {
          osm: {
            type: "raster",
            tiles: [
              "https://a.tile.openstreetmap.org/{z}/{x}/{y}.png",
              "https://b.tile.openstreetmap.org/{z}/{x}/{y}.png",
              "https://c.tile.openstreetmap.org/{z}/{x}/{y}.png",
            ],
            tileSize: 256,
            attribution: "© OpenStreetMap",
          },
        },
        layers: [{ id: "osm", type: "raster", source: "osm" }],
      },
      center: [108.22, 16.05],
      zoom: 11,
    });
    map.addControl(new maplibregl.NavigationControl(), "top-right");
    mapRef.current = map;

    // ResizeObserver: nếu modal/layout đổi kích thước (ví dụ legend +
    // footer nhảy vào sau khi data về), gọi map.resize() để canvas khớp.
    const ro = new ResizeObserver(() => {
      mapRef.current?.resize();
    });
    ro.observe(el);

    return () => {
      ro.disconnect();
      map.remove();
      mapRef.current = null;
      popupRef.current = null;
    };
  }, [mapReady]);

  // Khi data tới, push lên map (chờ map.loaded để addSource an toàn).
  useEffect(() => {
    const map = mapRef.current;
    if (!map || items.length === 0) return;

    const features = items.map((it) => ({
      type: /** @type {"Feature"} */ ("Feature"),
      geometry: {
        type: /** @type {"Point"} */ ("Point"),
        coordinates: [it.longitude, it.latitude],
      },
      properties: { id: it.id },
    }));
    /** @type {GeoJSON.FeatureCollection} */
    const fc = { type: "FeatureCollection", features };

    const apply = () => {
      // rssi expression: lookup theo properties.id thì phức tạp; thay vào
      // đó nhét rssi vào properties để paint-step dùng trực tiếp.
      const featuresWithRssi = items.map((it) => ({
        type: /** @type {"Feature"} */ ("Feature"),
        geometry: {
          type: /** @type {"Point"} */ ("Point"),
          coordinates: [it.longitude, it.latitude],
        },
        properties: { id: it.id, rssi: it.rssi_dbm },
      }));
      /** @type {GeoJSON.FeatureCollection} */
      const fcWithRssi = { type: "FeatureCollection", features: featuresWithRssi };

      const existing = map.getSource("batch_points");
      if (existing && "setData" in existing) {
        /** @type {maplibregl.GeoJSONSource} */ (existing).setData(fcWithRssi);
      } else {
        map.addSource("batch_points", { type: "geojson", data: fcWithRssi });
        map.addLayer({
          id: "batch_points_layer",
          type: "circle",
          source: "batch_points",
          paint: {
            "circle-radius": 6,
            "circle-color": [
              "step",
              ["get", "rssi"],
              "#dc2626", // < -120
              -120,
              "#f97316", // -120 .. -115
              -115,
              "#eab308", // -115 .. -100
              -100,
              "#16a34a", // >= -100
            ],
            "circle-stroke-width": 1.5,
            "circle-stroke-color": "#ffffff",
          },
        });
        map.on("click", "batch_points_layer", (e) => {
          const f = e.features?.[0];
          if (!f) return;
          const fid = /** @type {string} */ (f.properties?.id);
          const item = items.find((it) => it.id === fid) ?? null;
          setSelected(item);
        });
        map.on("mouseenter", "batch_points_layer", () => {
          map.getCanvas().style.cursor = "pointer";
        });
        map.on("mouseleave", "batch_points_layer", () => {
          map.getCanvas().style.cursor = "";
        });
      }

      // Resize trước khi fit-bounds để bounds tính theo canvas hiện tại.
      map.resize();

      // Fit bounds to all points (+ small padding). maplibre LngLatBounds.
      const bounds = new maplibregl.LngLatBounds();
      for (const it of items) bounds.extend([it.longitude, it.latitude]);
      if (items.length === 1) {
        map.flyTo({ center: [items[0].longitude, items[0].latitude], zoom: 14 });
      } else {
        map.fitBounds(bounds, { padding: 60, maxZoom: 14, duration: 600 });
      }
    };

    if (map.loaded()) apply();
    else map.once("load", apply);
  }, [items]);

  // Khi user click 1 marker, mở popup tại toạ độ điểm đó.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    popupRef.current?.remove();
    if (!selected) return;
    const popup = new maplibregl.Popup({ closeOnClick: false, offset: 12 })
      .setLngLat([selected.longitude, selected.latitude])
      .setHTML(_pointPopupHtml(selected))
      .addTo(map);
    popup.on("close", () => setSelected(null));
    popupRef.current = popup;
  }, [selected]);

  const pending = items.length;

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/50 p-4"
      onClick={onClose}
    >
      <div
        className="flex h-[90vh] w-full max-w-6xl flex-col rounded-lg bg-white p-4 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-start justify-between gap-3">
          <div>
            <button
              type="button"
              onClick={onClose}
              className="text-xs text-slate-600 hover:underline"
            >
              {tb.btnBack}
            </button>
            <h3 className="mt-1 text-base font-semibold text-slate-900">
              {tb.mapHeading(pending)}
            </h3>
            <p className="mt-1 text-xs text-slate-500">
              {uploaderEmail ?? "—"} · {_formatTime(uploadedAt)}
            </p>
            <p className="mt-1 text-xs text-slate-500">{tb.mapHint}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-slate-300 px-2 py-1 text-xs hover:bg-slate-100"
          >
            {t.closePreview}
          </button>
        </div>

        {q.isPending && (
          <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 px-3 py-6 text-center text-sm text-slate-500">
            {t.loading}
          </div>
        )}
        {q.isError && <ReviewError error={q.error} fallback={t.errorLoad} />}

        {q.isSuccess && items.length === 0 && (
          <div className="rounded-lg border border-slate-200 bg-white px-3 py-6 text-center text-sm text-slate-500">
            {tb.mapNoPoints}
          </div>
        )}

        <div
          ref={mapDiv}
          className={
            "flex-1 overflow-hidden rounded-md border border-slate-200 " +
            (q.isSuccess && items.length > 0 ? "block" : "hidden")
          }
        />

        {q.isSuccess && items.length > 0 && (
          <>
            <MapLegend />
            <div className="mt-3 flex flex-wrap items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => onReject(pending)}
                className="rounded bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700"
              >
                {tb.btnRejectBatch}
              </button>
              <button
                type="button"
                onClick={() => onApprove(pending)}
                className="rounded bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700"
              >
                {tb.btnApproveBatch}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function MapLegend() {
  const L = tb.mapLegend;
  return (
    <div className="mt-2 flex flex-wrap items-center gap-3 text-[11px] text-slate-600">
      <LegendDot color="#16a34a" label={L.strong} />
      <LegendDot color="#eab308" label={L.medium} />
      <LegendDot color="#f97316" label={L.weak} />
      <LegendDot color="#dc2626" label={L.veryWeak} />
    </div>
  );
}

/** @param {{ color: string, label: string }} props */
function LegendDot({ color, label }) {
  return (
    <span className="inline-flex items-center gap-1">
      <span
        className="inline-block h-3 w-3 rounded-full ring-1 ring-white"
        style={{ backgroundColor: color, boxShadow: "0 0 0 1px rgba(0,0,0,0.3)" }}
      />
      <span>{label}</span>
    </span>
  );
}

/**
 * HTML popup khi click 1 marker — info-only, không có action button.
 * @param {import("./client.js").PendingContributionT} it
 */
function _pointPopupHtml(it) {
  const esc = (/** @type {string} */ s) =>
    s.replace(/[&<>"]/g, (c) =>
      c === "&" ? "&amp;" : c === "<" ? "&lt;" : c === ">" ? "&gt;" : "&quot;",
    );
  const rows = [
    ["Thời điểm", _formatTime(it.timestamp)],
    ["Toạ độ", `${it.latitude.toFixed(5)}, ${it.longitude.toFixed(5)}`],
    ["RSSI", `${it.rssi_dbm.toFixed(1)} dBm`],
    ["SNR", `${it.snr_db.toFixed(1)} dB`],
    ["SF", String(it.spreading_factor)],
    ["Gateway", it.gateway_code ?? "—"],
    ["Người gửi", it.contributor_email ?? "—"],
  ];
  return (
    `<div style="font-size:12px;line-height:1.5;min-width:200px">` +
    rows
      .map(
        ([k, v]) =>
          `<div><span style="color:#64748b">${esc(k)}:</span> <strong>${esc(String(v))}</strong></div>`,
      )
      .join("") +
    `</div>`
  );
}

/**
 * @param {{
 *   title: string,
 *   message: string,
 *   confirmLabel: string,
 *   confirmClass: string,
 *   onCancel: () => void,
 *   onConfirm: () => void,
 *   pending: boolean,
 * }} props
 */
function ConfirmModal({
  title,
  message,
  confirmLabel,
  confirmClass,
  onCancel,
  onConfirm,
  pending,
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4"
      onClick={onCancel}
    >
      <div
        className="w-full max-w-md rounded-lg bg-white p-4 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-base font-semibold text-slate-900">{title}</h3>
        <p className="mt-2 text-sm text-slate-600">{message}</p>
        <div className="mt-3 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-100"
          >
            {t.confirm.cancel}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={pending}
            className={`rounded px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 ${confirmClass}`}
          >
            {pending ? t.btnPending : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * @param {{
 *   title: string,
 *   message: string,
 *   note: string,
 *   onNoteChange: (s: string) => void,
 *   onCancel: () => void,
 *   onConfirm: () => void,
 *   pending: boolean,
 * }} props
 */
function RejectModal({
  title,
  message,
  note,
  onNoteChange,
  onCancel,
  onConfirm,
  pending,
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4"
      onClick={onCancel}
    >
      <div
        className="w-full max-w-md rounded-lg bg-white p-4 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-base font-semibold text-slate-900">{title}</h3>
        <p className="mt-1 text-sm text-slate-600">{message}</p>
        <label className="mt-3 block text-xs font-medium text-slate-700">
          {t.noteLabel}
        </label>
        <textarea
          value={note}
          onChange={(e) => onNoteChange(e.target.value)}
          placeholder={t.notePlaceholder}
          rows={3}
          maxLength={500}
          className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1 text-sm"
        />
        <div className="mt-3 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-100"
          >
            {t.confirm.cancel}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={pending}
            className="rounded bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
          >
            {pending ? t.btnPending : t.btnReject}
          </button>
        </div>
      </div>
    </div>
  );
}

/** @param {{ error: unknown, fallback: string }} props */
function ReviewError({ error, fallback }) {
  let msg = fallback;
  let code = "";
  if (error instanceof ApiError) {
    code = error.problem.code ?? "";
    const localized = tErr.byCode(code);
    msg = localized || error.problem.detail || error.problem.title || fallback;
    if (error.problem.status === 404) msg = tErr.reviewGone;
  }
  return (
    <div
      role="alert"
      className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800"
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
