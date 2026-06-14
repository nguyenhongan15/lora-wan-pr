// @ts-check
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

/** @param {number} ber */
function formatBer(ber) {
  if (ber <= 0) return "≈ 0";
  const exp = Math.round(Math.log10(ber));
  return `≈ 10${toSuperscript(exp)}`;
}

/** @param {number} n */
function toSuperscript(n) {
  const map = {
    "-": "⁻",
    0: "⁰",
    1: "¹",
    2: "²",
    3: "³",
    4: "⁴",
    5: "⁵",
    6: "⁶",
    7: "⁷",
    8: "⁸",
    9: "⁹",
  };
  return String(n)
    .split("")
    .map((c) => map[c] ?? c)
    .join("");
}

/**
 * @param {{ prediction: import("../api/client.js").PredictionT }} props
 */
export function PredictionView({ prediction }) {
  const {
    rssi_dbm,
    snr_db,
    coverage_status,
    recommended_sf,
    serving_gateway_id,
    signal_quality,
    environment_params,
  } = prediction;

  // BE chưa rebuild → signal_quality/environment_params undefined. Hiển thị
  // dải tối thiểu (RSSI/SNR/SF/GW) + báo "BE chưa hỗ trợ".
  const hasSq = !!signal_quality;
  const hasEnv = !!environment_params;
  const usedSf = environment_params?.spreading_factor ?? recommended_sf;
  const envLabel = hasEnv ? t.environmentLabel[environment_params.environment] : "—";
  const envValue = hasEnv
    ? `${environment_params.frequency_mhz} MHz · ${environment_params.tx_power_dbm} dBm · ${envLabel}`
    : t.fields.unavailable;

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

      <dl className="mt-5 grid grid-cols-1 gap-4 text-sm sm:grid-cols-2 lg:grid-cols-3">
        <ResultItem
          label={t.fields.rssi}
          value={`${rssi_dbm.toFixed(1)} dBm`}
        />
        <ResultItem
          label={t.fields.snr}
          value={`${snr_db.toFixed(1)} dB`}
        />
        <ResultItem
          label={t.fields.pdr}
          value={hasSq ? `${(signal_quality.pdr * 100).toFixed(1)}%` : t.fields.unavailable}
          sub={hasSq ? t.fields.pdrSub : undefined}
        />
        <ResultItem
          label={t.fields.interference}
          value={
            hasSq
              ? `UL ${signal_quality.uplink_noise_floor_dbm.toFixed(1)} · DL ${signal_quality.downlink_noise_floor_dbm.toFixed(1)} dBm`
              : t.fields.unavailable
          }
          sub={hasSq ? t.fields.interferenceSub : undefined}
        />
        <ResultItem
          label={t.fields.sf}
          value={`SF${usedSf}`}
          sub={
            usedSf === recommended_sf
              ? t.fields.sfMatch
              : t.fields.sfRecommended(recommended_sf)
          }
        />
        <ResultItem
          label={t.fields.bandwidth}
          value={
            hasSq
              ? `${(signal_quality.bandwidth_hz / 1000).toFixed(0)} kHz`
              : t.fields.unavailable
          }
          sub={hasSq ? t.fields.bandwidthSub : undefined}
        />
        <ResultItem
          label={t.fields.shadowing}
          value={
            hasSq
              ? `σ = ${signal_quality.shadow_fading_sigma_db.toFixed(1)} dB`
              : t.fields.unavailable
          }
          sub={hasSq ? t.fields.shadowingSub : undefined}
        />
        <ResultItem
          label={t.fields.berFer}
          value={
            hasSq
              ? `${formatBer(signal_quality.ber)} · FER ${(signal_quality.fer * 100).toFixed(1)}%`
              : t.fields.unavailable
          }
          sub={hasSq ? t.fields.berFerSub : undefined}
        />
        <ResultItem
          label={t.fields.latency}
          value={
            hasSq
              ? `≈ ${signal_quality.time_on_air_ms.toFixed(0)} ms`
              : t.fields.unavailable
          }
          sub={hasSq ? t.fields.latencySub(signal_quality.jitter_ms) : undefined}
        />
        <ResultItem
          label={t.fields.gateway}
          value={serving_gateway_id ?? t.gatewayNone}
          mono
        />
        <ResultItem
          label={t.fields.environment}
          value={envValue}
          sub={hasEnv ? t.fields.environmentSub : undefined}
        />
      </dl>
    </div>
  );
}

/**
 * @param {{ label: string, value: string, sub?: string, mono?: boolean }} props
 */
function ResultItem({ label, value, sub, mono }) {
  return (
    <div>
      <dt className="text-slate-500">{label}</dt>
      <dd
        className={`mt-1 font-mono text-slate-900 ${mono ? "truncate text-xs" : "text-base"}`}
      >
        {value}
      </dd>
      {sub && <dd className="mt-0.5 text-xs text-slate-400">{sub}</dd>}
    </div>
  );
}
