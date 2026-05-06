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
    model_version,
    recommended_sf,
    serving_gateway_id,
  } = prediction;
  const [showLayer2, setShowLayer2] = useState(false);

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
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
          <div>
            <dt className="text-slate-500">{t.fields.model}</dt>
            <dd className="mt-1 font-mono text-xs text-slate-700">
              {model_version}
            </dd>
          </div>
        </dl>
      )}
    </div>
  );
}
