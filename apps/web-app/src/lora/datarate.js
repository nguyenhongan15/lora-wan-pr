// LoRaWAN data-rate metrics — bitrate, time-on-air, max payload theo SF.
// Tham chiếu: Semtech AN1200.22 (LoRa Modulation Basics) + LoRaWAN
// RP002-1.0.4 §2.6.1 (AS923 maxPayloadSize, DwellTime=0).
//
// Đây là metrics đường truyền dữ liệu, không phải coverage — giúp người dùng
// thấy "SF tăng → tầm xa hơn nhưng chậm hơn / payload nhỏ hơn".
//
// Assumptions: BW=125 kHz, CR=4/5, header explicit, CRC on, low-data-rate
// optimize ON khi SF≥11 (BW=125kHz). Payload chuẩn 23 B của TX side.

const BW_KHZ = 125;
const CR_DENOM = 5; // 4/5

// AS923 max app payload (M − header − FRMPayload offset). Spec table 6 §2.6.1
// (DwellTime=0). SF7-9 = 250 B; SF10 = 230 B; SF11 = 230 B; SF12 = 230 B.
// (Khi DwellTime=1 (Thailand) sẽ thấp hơn — Vietnam = 0, không xét.)
const MAX_PAYLOAD_AS923_DT0 = {
  7: 222,
  8: 222,
  9: 115,
  10: 51,
  11: 51,
  12: 51,
};

/**
 * Bitrate (chip rate effective) theo SF. Công thức Semtech:
 *   Rb = SF · (BW / 2^SF) · (4 / (4+CR))   [bps]
 * @param {number} sf  7..12
 * @returns {number}   bits per second
 */
export function bitrateBps(sf) {
  const symbolRate = (BW_KHZ * 1000) / Math.pow(2, sf); // symbols/sec
  return sf * symbolRate * (4 / CR_DENOM);
}

/**
 * Time-on-air (ms) cho payload bytes cho trước. Công thức Semtech AN1200.13:
 *   T_sym = 2^SF / BW
 *   T_preamble = (Npreamble + 4.25) · T_sym   (Npreamble = 8)
 *   payloadSymbNb = 8 + max(ceil((8PL − 4SF + 28 + 16 − 20H) / (4(SF − 2DE))) · (CR+4), 0)
 *     trong đó H=0 (header explicit), DE=1 nếu SF≥11 (low-data-rate opt), else 0.
 *   T_payload = payloadSymbNb · T_sym
 *   ToA = T_preamble + T_payload
 *
 * @param {number} sf
 * @param {number=} payloadBytes  default 23 (LoRaWAN typical app uplink)
 * @returns {number} ms
 */
export function timeOnAirMs(sf, payloadBytes = 23) {
  const tSymMs = Math.pow(2, sf) / BW_KHZ; // ms (vì BW kHz → 1/kHz = ms)
  const nPreamble = 8;
  const tPreamble = (nPreamble + 4.25) * tSymMs;

  const de = sf >= 11 ? 1 : 0;
  const h = 0; // explicit header
  const numerator = 8 * payloadBytes - 4 * sf + 28 + 16 - 20 * h;
  const denominator = 4 * (sf - 2 * de);
  const payloadSymbNb = 8 + Math.max(Math.ceil(numerator / denominator) * CR_DENOM, 0);
  const tPayload = payloadSymbNb * tSymMs;

  return tPreamble + tPayload;
}

/**
 * Max app payload (bytes) theo AS923 DwellTime=0 (Vietnam).
 * @param {number} sf
 * @returns {number}
 */
export function maxPayloadBytes(sf) {
  return MAX_PAYLOAD_AS923_DT0[/** @type {keyof typeof MAX_PAYLOAD_AS923_DT0} */ (sf)] ?? 0;
}

/**
 * Format bitrate cho UI: "5.47 kbps" / "250 bps".
 * @param {number} sf
 */
export function formatBitrate(sf) {
  const bps = bitrateBps(sf);
  if (bps >= 1000) {
    return `${(bps / 1000).toFixed(2)} kbps`;
  }
  return `${bps.toFixed(0)} bps`;
}

/**
 * Format time-on-air cho UI: "61.7 ms" / "1.32 s".
 * @param {number} sf
 * @param {number=} payloadBytes
 */
export function formatTimeOnAir(sf, payloadBytes = 23) {
  const ms = timeOnAirMs(sf, payloadBytes);
  if (ms >= 1000) {
    return `${(ms / 1000).toFixed(2)} s`;
  }
  return `${ms.toFixed(1)} ms`;
}
