// @ts-check
// Admin manual review queue — gom theo batch (1 file CSV/JSON, hoặc 1 lượt
// sync lpwanmapper/chirpstack). Mỗi batch có thể đi kèm GATEWAY MỚI nếu sync
// tạo gateway lạ (gateway_quarantine.batch_id trỏ về batch này).
//
// Default view: list batch. Mỗi batch hiển thị "${pending}/${total} điểm +
// ${newGw} gateway mới". Click "Xem chi tiết" → BatchMapModal: maplibre map
// vẽ cả điểm đo (color theo RSSI) lẫn gateway (cam pulse = mới, xám = cũ).
// Filter toggle góc trên-phải cho phép ẩn/hiện từng layer.
//
// 4 nút phê duyệt (cấp batch, không có per-row action):
//   • Từ chối — reject toàn bộ điểm đo + gateway pending của batch.
//   • Duyệt cả file — duyệt cả điểm đo + gateway.
//   • Duyệt điểm đo (không duyệt gateway) — điểm trỏ gateway cũ promote ngay;
//     điểm trỏ gateway mới defer (status pending_gateway, auto-promote khi
//     gateway được duyệt sau).
//   • Duyệt gateway (không duyệt điểm đo) — gateway lên geo.gateways; điểm
//     đo của batch reject hết.
//
// Khi batch không có gateway mới (new_gateway_count=0), 2 nút mode chia đôi
// disable (degenerate — chính là "Duyệt cả file").

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import maplibregl from "maplibre-gl";
import { SURVEY_RSSI_BINS, surveyRssiColorExpression } from "../components/legend.js";
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

/** @typedef {"all" | "points_only" | "gateways_only"} ApproveMode */

/**
 * @param {string} iso
 */
function _formatTime(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("vi-VN", { hour12: false });
}

/**
 * @param {string|null} earliest @param {string|null} latest
 */
function _formatRange(earliest, latest) {
  if (!earliest || !latest) return "—";
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

  /**
   * @typedef {{
   *   kind: "approve",
   *   mode: ApproveMode,
   *   uploader_id: string,
   *   uploaded_at: string,
   *   points: number,
   *   newGw: number,
   * } | {
   *   kind: "reject",
   *   uploader_id: string,
   *   uploaded_at: string,
   *   points: number,
   *   newGw: number,
   * }} BatchConfirmState
   */
  const [confirmBatch, setConfirmBatch] = useState(
    /** @type {BatchConfirmState | null} */ (null),
  );
  const [rejectBatchNote, setRejectBatchNote] = useState("");

  const invalidateAll = () => {
    qc.invalidateQueries({ queryKey: ["admin", "pending", "batches"] });
    qc.invalidateQueries({ queryKey: ["admin", "pending", "batch"] });
    qc.invalidateQueries({ queryKey: ["admin", "stats"] });
    qc.invalidateQueries({ queryKey: ["gateways"] });
  };

  const approveBatchM = useMutation({
    mutationFn: (
      /** @type {{ uploader_id: string, uploaded_at: string, mode: ApproveMode }} */ vars,
    ) => approveBatch(vars.uploader_id, vars.uploaded_at, vars.mode),
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
                    {tb.countLabel(
                      b.pending_review_count,
                      b.total_count,
                      b.new_gateway_count,
                    )}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-xs text-slate-600">
                    {_formatRange(b.earliest_timestamp, b.latest_timestamp)}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-right">
                    <div className="flex justify-end gap-1">
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() =>
                          setDrillIn({
                            uploader_id: b.uploader_id,
                            uploaded_at: b.uploaded_at,
                            uploader_email: b.uploader_email,
                          })
                        }
                        className="rounded border border-slate-300 px-2 py-1 text-xs hover:bg-slate-100 disabled:opacity-50"
                      >
                        {tb.btnViewRows}
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
          onApprove={(mode, points, newGw) =>
            setConfirmBatch({
              kind: "approve",
              mode,
              uploader_id: drillIn.uploader_id,
              uploaded_at: drillIn.uploaded_at,
              points,
              newGw,
            })
          }
          onReject={(points, newGw) => {
            setRejectBatchNote("");
            setConfirmBatch({
              kind: "reject",
              uploader_id: drillIn.uploader_id,
              uploaded_at: drillIn.uploaded_at,
              points,
              newGw,
            });
          }}
        />
      )}

      {confirmBatch && confirmBatch.kind === "approve" && (
        <ConfirmModal
          title={t.confirm.title}
          message={_approveMessage(
            confirmBatch.mode,
            confirmBatch.points,
            confirmBatch.newGw,
          )}
          confirmLabel={_approveLabel(confirmBatch.mode)}
          confirmClass="bg-emerald-600 hover:bg-emerald-700"
          onCancel={() => setConfirmBatch(null)}
          onConfirm={() =>
            approveBatchM.mutate({
              uploader_id: confirmBatch.uploader_id,
              uploaded_at: confirmBatch.uploaded_at,
              mode: confirmBatch.mode,
            })
          }
          pending={approveBatchM.isPending}
        />
      )}

      {confirmBatch && confirmBatch.kind === "reject" && (
        <RejectModal
          title={t.confirm.title}
          message={tb.confirm.reject(confirmBatch.points, confirmBatch.newGw)}
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
 * @param {ApproveMode} mode @param {number} points @param {number} newGw
 */
function _approveMessage(mode, points, newGw) {
  if (mode === "points_only") return tb.confirm.approvePointsOnly(points, newGw);
  if (mode === "gateways_only") return tb.confirm.approveGatewaysOnly(points, newGw);
  return tb.confirm.approveAll(points, newGw);
}

/** @param {ApproveMode} mode */
function _approveLabel(mode) {
  if (mode === "points_only") return tb.btnApprovePointsOnly;
  if (mode === "gateways_only") return tb.btnApproveGatewaysOnly;
  return tb.btnApproveBatch;
}

/**
 * Drill-in modal: vẽ batch (điểm đo + gateway) trên 1 maplibre map. Footer
 * có 4 nút mode (Từ chối / Duyệt cả file / Duyệt điểm đo / Duyệt gateway).
 * Filter toggle góc trên-phải ẩn/hiện từng layer.
 *
 * @param {{
 *   uploaderId: string,
 *   uploadedAt: string,
 *   uploaderEmail: string | null,
 *   onClose: () => void,
 *   onApprove: (mode: ApproveMode, points: number, newGw: number) => void,
 *   onReject: (points: number, newGw: number) => void,
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
  const [selectedPoint, setSelectedPoint] = useState(
    /** @type {import("./client.js").PendingContributionT | null} */ (null),
  );
  const [selectedGateway, setSelectedGateway] = useState(
    /** @type {import("./client.js").BatchGatewayT | null} */ (null),
  );
  const [showPoints, setShowPoints] = useState(true);
  const [showGateways, setShowGateways] = useState(true);
  const [showFilter, setShowFilter] = useState(false);

  const points = useMemo(() => q.data?.points ?? [], [q.data]);
  const gateways = useMemo(() => q.data?.gateways ?? [], [q.data]);
  const newGwCount = q.data?.new_gateway_count ?? 0;
  const hasContent = points.length > 0 || gateways.length > 0;

  // Init map khi có content (tránh tạo map khi div đang display:none).
  const mapReady = q.isSuccess && hasContent;
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

  // Render layers khi data về.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !hasContent) return;

    const apply = () => {
      // Points layer
      const pointFc = {
        type: /** @type {"FeatureCollection"} */ ("FeatureCollection"),
        features: points.map((it) => ({
          type: /** @type {"Feature"} */ ("Feature"),
          geometry: {
            type: /** @type {"Point"} */ ("Point"),
            coordinates: [it.longitude, it.latitude],
          },
          properties: { id: it.id, rssi_dbm: it.rssi_dbm },
        })),
      };

      const pointsSrc = map.getSource("batch_points");
      if (pointsSrc && "setData" in pointsSrc) {
        /** @type {maplibregl.GeoJSONSource} */ (pointsSrc).setData(pointFc);
      } else {
        map.addSource("batch_points", { type: "geojson", data: pointFc });
        map.addLayer({
          id: "batch_points_layer",
          type: "circle",
          source: "batch_points",
          paint: /** @type {any} */ ({
            "circle-radius": 6,
            "circle-color": surveyRssiColorExpression(),
            "circle-stroke-width": 1.5,
            "circle-stroke-color": "#ffffff",
          }),
        });
        map.on("click", "batch_points_layer", (e) => {
          const f = e.features?.[0];
          if (!f) return;
          const fid = /** @type {string} */ (f.properties?.id);
          const item = points.find((it) => it.id === fid) ?? null;
          setSelectedPoint(item);
          setSelectedGateway(null);
        });
        map.on("mouseenter", "batch_points_layer", () => {
          map.getCanvas().style.cursor = "pointer";
        });
        map.on("mouseleave", "batch_points_layer", () => {
          map.getCanvas().style.cursor = "";
        });
      }

      // Gateway layer (1 source, 2 layer: existing xám + new cam viền pulse-look).
      const gwFc = {
        type: /** @type {"FeatureCollection"} */ ("FeatureCollection"),
        features: gateways.map((g) => ({
          type: /** @type {"Feature"} */ ("Feature"),
          geometry: {
            type: /** @type {"Point"} */ ("Point"),
            coordinates: [g.longitude, g.latitude],
          },
          properties: {
            id: g.id,
            code: g.code,
            name: g.name ?? "",
            is_new: g.is_new,
          },
        })),
      };
      const gwSrc = map.getSource("batch_gateways");
      if (gwSrc && "setData" in gwSrc) {
        /** @type {maplibregl.GeoJSONSource} */ (gwSrc).setData(gwFc);
      } else {
        map.addSource("batch_gateways", { type: "geojson", data: gwFc });
        // Outer halo cho gateway mới (đứng giả pulse — static, không animate
        // vì maplibre không có CSS animation cho layer; user vẫn nhận diện
        // được nhờ size+color khác hẳn).
        map.addLayer({
          id: "batch_gateways_halo",
          type: "circle",
          source: "batch_gateways",
          filter: ["==", ["get", "is_new"], true],
          paint: /** @type {any} */ ({
            "circle-radius": 16,
            "circle-color": "#FF6B00",
            "circle-opacity": 0.25,
          }),
        });
        map.addLayer({
          id: "batch_gateways_layer",
          type: "circle",
          source: "batch_gateways",
          paint: /** @type {any} */ ({
            "circle-radius": 9,
            "circle-color": [
              "case",
              ["==", ["get", "is_new"], true],
              "#FF6B00",
              "#64748b",
            ],
            "circle-stroke-width": 2,
            "circle-stroke-color": "#ffffff",
          }),
        });
        map.on("click", "batch_gateways_layer", (e) => {
          const f = e.features?.[0];
          if (!f) return;
          const fid = /** @type {string} */ (f.properties?.id);
          const g = gateways.find((it) => it.id === fid) ?? null;
          setSelectedGateway(g);
          setSelectedPoint(null);
        });
        map.on("mouseenter", "batch_gateways_layer", () => {
          map.getCanvas().style.cursor = "pointer";
        });
        map.on("mouseleave", "batch_gateways_layer", () => {
          map.getCanvas().style.cursor = "";
        });
      }

      map.resize();

      // Fit bounds tới mọi điểm + gateway.
      const bounds = new maplibregl.LngLatBounds();
      for (const it of points) bounds.extend([it.longitude, it.latitude]);
      for (const g of gateways) bounds.extend([g.longitude, g.latitude]);
      const totalFeatures = points.length + gateways.length;
      if (totalFeatures === 1) {
        const first = points[0] ?? gateways[0];
        map.flyTo({ center: [first.longitude, first.latitude], zoom: 14 });
      } else if (totalFeatures > 1) {
        map.fitBounds(bounds, { padding: 60, maxZoom: 14, duration: 600 });
      }
    };

    if (map.loaded()) apply();
    else map.once("load", apply);
  }, [points, gateways, hasContent]);

  // Toggle visibility từng layer khi user click filter.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const setVis = (/** @type {string} */ id, /** @type {boolean} */ show) => {
      if (map.getLayer(id)) {
        map.setLayoutProperty(id, "visibility", show ? "visible" : "none");
      }
    };
    setVis("batch_points_layer", showPoints);
    setVis("batch_gateways_layer", showGateways);
    setVis("batch_gateways_halo", showGateways);
  }, [showPoints, showGateways, points, gateways]);

  // Popup cho điểm đo.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    popupRef.current?.remove();
    if (!selectedPoint) return;
    const popup = new maplibregl.Popup({ closeOnClick: false, offset: 12 })
      .setLngLat([selectedPoint.longitude, selectedPoint.latitude])
      .setHTML(_pointPopupHtml(selectedPoint))
      .addTo(map);
    popup.on("close", () => setSelectedPoint(null));
    popupRef.current = popup;
  }, [selectedPoint]);

  // Popup cho gateway.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    popupRef.current?.remove();
    if (!selectedGateway) return;
    const popup = new maplibregl.Popup({ closeOnClick: false, offset: 12 })
      .setLngLat([selectedGateway.longitude, selectedGateway.latitude])
      .setHTML(_gatewayPopupHtml(selectedGateway))
      .addTo(map);
    popup.on("close", () => setSelectedGateway(null));
    popupRef.current = popup;
  }, [selectedGateway]);

  const totalPoints = points.length;
  const canSplit = newGwCount > 0;

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
              {tb.mapHeading(totalPoints, newGwCount)}
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

        {q.isSuccess && !hasContent && (
          <div className="rounded-lg border border-slate-200 bg-white px-3 py-6 text-center text-sm text-slate-500">
            {tb.mapNoPoints}
          </div>
        )}

        <div
          className={
            "relative flex-1 overflow-hidden rounded-md border border-slate-200 " +
            (q.isSuccess && hasContent ? "block" : "hidden")
          }
        >
          <div ref={mapDiv} className="h-full w-full" />
          <FilterToggle
            open={showFilter}
            onToggle={() => setShowFilter((v) => !v)}
            showPoints={showPoints}
            showGateways={showGateways}
            onChangePoints={setShowPoints}
            onChangeGateways={setShowGateways}
          />
        </div>

        {q.isSuccess && hasContent && (
          <>
            <MapLegend showGatewayLegend={gateways.length > 0} />
            <div className="mt-3 flex flex-wrap items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => onReject(totalPoints, newGwCount)}
                className="rounded bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700"
              >
                {tb.btnRejectBatch}
              </button>
              <button
                type="button"
                onClick={() => onApprove("all", totalPoints, newGwCount)}
                className="rounded bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700"
              >
                {tb.btnApproveBatch}
              </button>
              <button
                type="button"
                disabled={!canSplit}
                onClick={() => onApprove("points_only", totalPoints, newGwCount)}
                title={canSplit ? undefined : tb.btnApproveBatch}
                className="rounded border border-emerald-600 px-3 py-1.5 text-sm font-medium text-emerald-700 hover:bg-emerald-50 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {tb.btnApprovePointsOnly}
              </button>
              <button
                type="button"
                disabled={!canSplit}
                onClick={() => onApprove("gateways_only", totalPoints, newGwCount)}
                title={canSplit ? undefined : tb.btnApproveBatch}
                className="rounded border border-emerald-600 px-3 py-1.5 text-sm font-medium text-emerald-700 hover:bg-emerald-50 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {tb.btnApproveGatewaysOnly}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/**
 * @param {{
 *   open: boolean,
 *   onToggle: () => void,
 *   showPoints: boolean,
 *   showGateways: boolean,
 *   onChangePoints: (v: boolean) => void,
 *   onChangeGateways: (v: boolean) => void,
 * }} props
 */
function FilterToggle({
  open,
  onToggle,
  showPoints,
  showGateways,
  onChangePoints,
  onChangeGateways,
}) {
  const tf = tb.filterToggle;
  return (
    <div className="absolute right-2 top-2 z-10">
      <button
        type="button"
        onClick={onToggle}
        aria-label={tf.title}
        className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs font-medium text-slate-700 shadow hover:bg-slate-50"
      >
        {/* funnel icon SVG inline */}
        <svg
          className="inline h-3.5 w-3.5"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          viewBox="0 0 24 24"
        >
          <path d="M3 4h18l-7 9v6l-4 2v-8L3 4z" />
        </svg>
      </button>
      {open && (
        <div className="mt-1 w-44 rounded-md border border-slate-200 bg-white p-2 text-xs shadow-lg">
          <div className="mb-1 font-semibold text-slate-700">{tf.title}</div>
          <label className="flex items-center gap-2 py-0.5 text-slate-700">
            <input
              type="checkbox"
              checked={showPoints}
              onChange={(e) => onChangePoints(e.target.checked)}
            />
            <span>{tf.showPoints}</span>
          </label>
          <label className="flex items-center gap-2 py-0.5 text-slate-700">
            <input
              type="checkbox"
              checked={showGateways}
              onChange={(e) => onChangeGateways(e.target.checked)}
            />
            <span>{tf.showGateways}</span>
          </label>
        </div>
      )}
    </div>
  );
}

/** @param {{ showGatewayLegend: boolean }} props */
function MapLegend({ showGatewayLegend }) {
  const rows = [...SURVEY_RSSI_BINS].reverse();
  return (
    <div className="mt-2 flex flex-wrap items-center gap-3 text-[11px] text-slate-600">
      {rows.map((bin) => (
        <LegendDot key={bin.label} color={bin.color} label={bin.label} />
      ))}
      {showGatewayLegend && (
        <>
          <span className="mx-1 text-slate-300">|</span>
          <LegendDot color="#FF6B00" label={tb.gatewayLegend.newLabel} ring />
          <LegendDot color="#64748b" label={tb.gatewayLegend.existingLabel} ring />
        </>
      )}
    </div>
  );
}

/** @param {{ color: string, label: string, ring?: boolean }} props */
function LegendDot({ color, label, ring }) {
  return (
    <span className="inline-flex items-center gap-1">
      <span
        className={"inline-block h-3 w-3 rounded-full " + (ring ? "ring-2 ring-white" : "ring-1 ring-white")}
        style={{ backgroundColor: color, boxShadow: "0 0 0 1px rgba(0,0,0,0.3)" }}
      />
      <span>{label}</span>
    </span>
  );
}

/**
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

/** @param {import("./client.js").BatchGatewayT} g */
function _gatewayPopupHtml(g) {
  const esc = (/** @type {string} */ s) =>
    s.replace(/[&<>"]/g, (c) =>
      c === "&" ? "&amp;" : c === "<" ? "&lt;" : c === ">" ? "&gt;" : "&quot;",
    );
  const rows = [
    ["Code", g.code],
    ["Tên", g.name ?? "—"],
    ["Toạ độ", `${g.latitude.toFixed(5)}, ${g.longitude.toFixed(5)}`],
    ["Tần số", `${g.frequency_mhz} MHz`],
    ["Nguồn", g.source_type ?? "—"],
    [
      "Trạng thái",
      g.is_new ? tb.gatewayLegend.newLabel : tb.gatewayLegend.existingLabel,
    ],
  ];
  return (
    `<div style="font-size:12px;line-height:1.5;min-width:220px">` +
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
