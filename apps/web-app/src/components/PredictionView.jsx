// @ts-check
import { useState } from "react";
import { strings } from "../strings.js";

const t = strings.predictionView;
/** @type {Record<string, string>} */
const STATUS_LABEL = strings.coverageStatus;

/** @type {Record<string, string>} */
const STATUS_BG = {
  strong: "bg-strong",
  marginal: "bg-marginal",
  weak: "bg-weak",
  no_coverage: "bg-nocov",
};

const tBi = t.bidirectional;

/**
 * Two-layer view per business-logic §4.2:
 *   Layer 1 — badge + Vietnamese sentence cho end-user.
 *   Layer 2 — chi tiết kỹ thuật (RSSI/SNR/SF khuyến nghị/gateway/confidence)
 *             ẩn mặc định, mở qua toggle.
 *
 * @param {{ prediction: import("../api/client.js").PredictionT }} props
 */
export function PredictionView({ prediction }) {
  const {
    rssi_dbm,
    snr_db,
    coverage_status,
    confidence,
    recommended_sf,
    serving_gateway_id,
    uplink,
    downlink,
    bottleneck,
  } = prediction;
  const [showLayer2, setShowLayer2] = useState(false);

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm md:p-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-900">{t.title}</h2>
        <span
          className={`rounded-full px-3 py-1 text-xs font-medium text-white ${STATUS_BG[coverage_status]}`}
        >
          {STATUS_LABEL[coverage_status]}
        </span>
      </div>

      <p className="mt-3 text-sm text-slate-700">
        {t.layer1Sentence[coverage_status]}
      </p>

      <button
        type="button"
        onClick={() => setShowLayer2((v) => !v)}
        className="mt-3 text-xs font-medium text-slate-500 hover:text-slate-900"
      >
        {showLayer2 ? t.toggleLayer2.hide : t.toggleLayer2.show}
      </button>

      {showLayer2 && (
        <>
          <dl className="mt-4 grid grid-cols-2 gap-4 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-slate-500">{t.fields.rssi}</dt>
              <dd className="mt-1 font-mono text-base text-slate-900">
                {rssi_dbm.toFixed(1)} dBm
              </dd>
            </div>
            <div>
              <dt className="text-slate-500">{t.fields.snr}</dt>
              <dd className="mt-1 font-mono text-base text-slate-900">
                {snr_db.toFixed(1)} dB
              </dd>
            </div>
            <div>
              <dt className="text-slate-500">{t.fields.recommendedSf}</dt>
              <dd className="mt-1 font-mono text-base text-slate-900">
                SF{recommended_sf}
              </dd>
            </div>
            <div>
              <dt className="text-slate-500">{t.fields.confidence}</dt>
              <dd className="mt-1 font-mono text-base text-slate-900">
                {(confidence.score * 100).toFixed(1)}%
              </dd>
              <dd className="text-xs text-slate-400">({confidence.method})</dd>
            </div>
            <div>
              <dt className="text-slate-500">{t.fields.gateway}</dt>
              <dd className="mt-1 truncate font-mono text-xs text-slate-700">
                {serving_gateway_id ?? t.gatewayNone}
              </dd>
            </div>
          </dl>

          {uplink && downlink && bottleneck && (
            <BidirectionalBlock
              uplink={uplink}
              downlink={downlink}
              bottleneck={bottleneck}
            />
          )}
        </>
      )}
    </div>
  );
}

/**
 * @param {{
 *   uplink: import("../api/client.js").LinkBudgetT,
 *   downlink: import("../api/client.js").LinkBudgetT,
 *   bottleneck: "uplink" | "downlink" | "both_ok"
 * }} props
 */
function BidirectionalBlock({ uplink, downlink, bottleneck }) {
  /** @type {Record<string, string>} */
  const bottleneckBg = {
    uplink: "bg-amber-100 text-amber-900 ring-amber-200",
    downlink: "bg-amber-100 text-amber-900 ring-amber-200",
    both_ok: "bg-emerald-100 text-emerald-900 ring-emerald-200",
  };
  return (
    <div className="mt-6 rounded-md border border-slate-200 bg-slate-50 p-4">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-700">
          {tBi.sectionTitle}
        </h3>
        <span
          className={`rounded-full px-2 py-0.5 text-xs ring-1 ${bottleneckBg[bottleneck]}`}
        >
          {tBi.bottleneckLabel}: {tBi.bottleneck[bottleneck]}
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[360px] text-xs">
          <thead className="text-slate-500">
            <tr>
              <th className="py-1 text-left font-medium"></th>
              <th className="py-1 text-right font-medium">{tBi.colRssi}</th>
              <th className="py-1 text-right font-medium">{tBi.colSnr}</th>
              <th className="py-1 text-right font-medium">{tBi.colMargin}</th>
              <th className="py-1 text-right font-medium">{tBi.colStatus}</th>
            </tr>
          </thead>
          <tbody className="font-mono text-slate-900">
            <DirectionRow label={tBi.directionUplink} budget={uplink} />
            <DirectionRow label={tBi.directionDownlink} budget={downlink} />
          </tbody>
        </table>
      </div>
    </div>
  );
}

/**
 * @param {{ label: string, budget: import("../api/client.js").LinkBudgetT }} props
 */
function DirectionRow({ label, budget }) {
  return (
    <tr className="border-t border-slate-200">
      <td className="py-1 pr-2 font-sans text-slate-700">{label}</td>
      <td className="py-1 text-right">{budget.rssi_dbm.toFixed(1)} dBm</td>
      <td className="py-1 text-right">{budget.snr_db.toFixed(1)} dB</td>
      <td className="py-1 text-right">{budget.margin_db.toFixed(1)} dB</td>
      <td className="py-1 text-right font-sans">
        <span
          className={`rounded px-1.5 py-0.5 text-white ${STATUS_BG[budget.status]}`}
        >
          {STATUS_LABEL[budget.status]}
        </span>
      </td>
    </tr>
  );
}
