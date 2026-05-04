import { RSSI_STRONG, RSSI_MEDIUM, RSSI_WEAK } from "./rssiThresholds";

/**
 * Tính phân bố vùng phủ từ GeoJSON features — ngưỡng LoRa Alliance CVT.
 * Backend trả properties camelCase: rssiDbm, snrDb, spreadingFactor...
 */
export function computeCoverage(features = []) {
  if (!features.length) return null;
  let strong = 0, medium = 0, weak = 0, veryWeak = 0, skipped = 0;

  for (const f of features) {
    const rssi = f?.properties?.rssiDbm ?? null;

    if (rssi == null) { skipped++; continue; }

    if      (rssi >= RSSI_STRONG) strong++;    // ≥ −90 dBm
    else if (rssi >= RSSI_MEDIUM) medium++;    // −90 ~ −105 dBm
    else if (rssi >= RSSI_WEAK)   weak++;      // −105 ~ −120 dBm
    else                          veryWeak++;  // < −120 dBm
  }

  if (import.meta.env.DEV && skipped > 0 && strong + medium + weak + veryWeak === 0) {
    console.warn(
      `[computeCoverage] Tất cả ${skipped} feature bị skip —`,
      "kiểm tra API có trả về properties.rssiDbm không.\nSample:", features[0],
    );
  }

  const total = strong + medium + weak + veryWeak || 1;
  return {
    strong, medium, weak, veryWeak,
    strongPct:   (strong   / total * 100).toFixed(1),
    mediumPct:   (medium   / total * 100).toFixed(1),
    weakPct:     (weak     / total * 100).toFixed(1),
    veryWeakPct: (veryWeak / total * 100).toFixed(1),
    total: strong + medium + weak + veryWeak,
  };
}

// Uncertainty (dB) → màu
export function uncertaintyToColor(db) {
  if (db == null) return "#888780";
  if (db < 3)  return "#a50026";
  if (db < 6)  return "#fdae61";
  if (db < 10) return "#74add1";
  return "#313695";
}

// Uncertainty → intensity [0, 1]
export function uncertaintyToIntensity(db) {
  return Math.max(0, Math.min(1, (db ?? 0) / 15));
}

// Format số hiển thị
export function fmt(v, unit = "", decimals = 1) {
  if (v == null || isNaN(v)) return "—";
  return `${Number(v).toFixed(decimals)}${unit}`;
}
