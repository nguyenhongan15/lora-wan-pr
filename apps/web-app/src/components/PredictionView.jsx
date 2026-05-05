// @ts-check

/** @type {Record<string, string>} */
const STATUS_LABEL = {
  strong: "Mạnh",
  marginal: "Tạm được",
  weak: "Yếu",
  no_coverage: "Không phủ",
};

/** @type {Record<string, string>} */
const STATUS_BG = {
  strong: "bg-strong",
  marginal: "bg-marginal",
  weak: "bg-weak",
  no_coverage: "bg-nocov",
};

/**
 * @param {{ prediction: import("../api/client.js").PredictionT }} props
 */
export function PredictionView({ prediction }) {
  const { rssi_dbm, snr_db, coverage_status, confidence, model_version } =
    prediction;
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-900">Kết quả dự đoán</h2>
        <span
          className={`rounded-full px-3 py-1 text-xs font-medium text-white ${STATUS_BG[coverage_status]}`}
        >
          {STATUS_LABEL[coverage_status]}
        </span>
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-slate-500">RSSI</dt>
          <dd className="mt-1 font-mono text-base text-slate-900">
            {rssi_dbm.toFixed(1)} dBm
          </dd>
        </div>
        <div>
          <dt className="text-slate-500">SNR</dt>
          <dd className="mt-1 font-mono text-base text-slate-900">
            {snr_db.toFixed(1)} dB
          </dd>
        </div>
        <div>
          <dt className="text-slate-500">Confidence</dt>
          <dd className="mt-1 font-mono text-base text-slate-900">
            {(confidence.score * 100).toFixed(1)}%
          </dd>
          <dd className="text-xs text-slate-400">({confidence.method})</dd>
        </div>
        <div>
          <dt className="text-slate-500">Model</dt>
          <dd className="mt-1 font-mono text-xs text-slate-700">
            {model_version}
          </dd>
        </div>
      </dl>
    </div>
  );
}
