import { makeRssiNormalizer, calcHeatmapBase, rssiToIntensity } from "./rssi";
import { RSSI_SCALE_MIN, RSSI_SCALE_MAX } from "./rssiThresholds";
import { api } from "../api";

function buildWeightStops(base) {
  return [0, 0.25, 0.50, 0.75, 1.0].flatMap(t => [
    parseFloat(t.toFixed(2)),
    parseFloat(Math.pow(t, base).toFixed(4)),
  ]);
}

function defaultConfig() {
  return {
    campaignId:  null,
    minRssi:     RSSI_SCALE_MIN,
    maxRssi:     RSSI_SCALE_MAX,
    normalizer:  rssiToIntensity,
    base:        3,
    weightStops: buildWeightStops(3),
  };
}

// Cache theo campaignId — tránh fetch lại khi re-render
const configCache = new Map();

/**
 * Tính config heatmap từ backend stats.
 * Backend trả camelCase: { total, avgRssi, minRssi, maxRssi, avgSnr }
 */
export async function loadRssiConfig(campaignId) {
  if (configCache.has(campaignId)) return configCache.get(campaignId);

  let stats;
  try {
    stats = await api.getStats(campaignId);   // ← dùng chung api.js, đã parse wrapper
  } catch (e) {
    console.warn("[rssiConfig] fallback default:", e.message);
    return defaultConfig();
  }

  // Fallback về scale chuẩn (−135, −55) nếu backend thiếu field
  const minRssi = stats?.minRssi ?? RSSI_SCALE_MIN;
  const maxRssi = stats?.maxRssi ?? RSSI_SCALE_MAX;
  const p75     = stats?.p75 ?? stats?.avgRssi ?? -100;

  const normalizer  = makeRssiNormalizer(minRssi, maxRssi);
  const base        = calcHeatmapBase(stats);
  const weightStops = buildWeightStops(base);

  const config = { campaignId, minRssi, maxRssi, p75, normalizer, base, weightStops };
  configCache.set(campaignId, config);

  console.log(`[rssiConfig] ${campaignId} → base=${base}, range=[${minRssi}, ${maxRssi}]`);
  return config;
}

export function clearRssiConfigCache(campaignId) {
  if (campaignId) configCache.delete(campaignId);
  else configCache.clear();
}
