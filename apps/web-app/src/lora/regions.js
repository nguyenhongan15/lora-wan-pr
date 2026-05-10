// LoRaWAN regional parameters — mirror của
// services/api-service/src/lora_coverage_api/domain/lora_regions.py
// Source: LoRa Alliance RP002-1.0.4.
//
// Khi sửa: cập nhật cả 2 file để tránh lệch nhau.

/**
 * @typedef {Object} LoRaRegion
 * @property {string} code                 - "AS923-2"
 * @property {string} label                - "AS923-2 — Vietnam, Indonesia"
 * @property {433|470|779|868|915|923} bandLabelMhz  - số tròn dùng cho DB CHECK
 * @property {number} carrierDefaultMhz    - channel 0 (cho Friis/calibration)
 * @property {number} bandMinMhz
 * @property {number} bandMaxMhz
 * @property {readonly string[]} countries - ISO-3166 alpha-2
 */

/** @type {readonly LoRaRegion[]} */
export const LORA_REGIONS = Object.freeze([
  {
    code: "EU433",
    label: "EU433 — Europe (ISM 433 MHz)",
    bandLabelMhz: 433,
    carrierDefaultMhz: 433.175,
    bandMinMhz: 433.05,
    bandMaxMhz: 434.79,
    countries: ["AT","BE","BG","CH","CY","CZ","DE","DK","EE","ES","FI","FR","GB","GR","HR","HU","IE","IT","LT","LU","LV","MT","NL","NO","PL","PT","RO","SE","SI","SK"],
  },
  {
    code: "CN470",
    label: "CN470-510 — China",
    bandLabelMhz: 470,
    carrierDefaultMhz: 486.3,
    bandMinMhz: 470.0,
    bandMaxMhz: 510.0,
    countries: ["CN"],
  },
  {
    code: "CN779",
    label: "CN779-787 — China (deprecated)",
    bandLabelMhz: 779,
    carrierDefaultMhz: 779.5,
    bandMinMhz: 779.0,
    bandMaxMhz: 787.0,
    countries: ["CN"],
  },
  {
    code: "EU868",
    label: "EU863-870 — Europe",
    bandLabelMhz: 868,
    carrierDefaultMhz: 868.1,
    bandMinMhz: 863.0,
    bandMaxMhz: 870.0,
    countries: ["AT","BE","BG","CH","CY","CZ","DE","DK","EE","ES","FI","FR","GB","GR","HR","HU","IE","IT","LT","LU","LV","MT","NL","NO","PL","PT","RO","SE","SI","SK","UA","TR"],
  },
  {
    code: "IN865",
    label: "IN865-867 — India",
    bandLabelMhz: 868,
    carrierDefaultMhz: 865.0625,
    bandMinMhz: 865.0,
    bandMaxMhz: 867.0,
    countries: ["IN"],
  },
  {
    code: "RU864",
    label: "RU864-870 — Russia",
    bandLabelMhz: 868,
    carrierDefaultMhz: 868.9,
    bandMinMhz: 864.0,
    bandMaxMhz: 870.0,
    countries: ["RU"],
  },
  {
    code: "US915",
    label: "US902-928 — USA, Canada, Mexico",
    bandLabelMhz: 915,
    carrierDefaultMhz: 903.9,
    bandMinMhz: 902.0,
    bandMaxMhz: 928.0,
    countries: ["US","CA","MX"],
  },
  {
    code: "AU915",
    label: "AU915-928 — Australia",
    bandLabelMhz: 915,
    carrierDefaultMhz: 916.8,
    bandMinMhz: 915.0,
    bandMaxMhz: 928.0,
    countries: ["AU"],
  },
  {
    code: "KR920",
    label: "KR920-923 — South Korea",
    bandLabelMhz: 923,
    carrierDefaultMhz: 922.1,
    bandMinMhz: 920.9,
    bandMaxMhz: 923.3,
    countries: ["KR"],
  },
  {
    code: "AS923-1",
    label: "AS923-1 — Brunei, Cambodia, Indonesia, Japan, Laos, NZ, Singapore, Taiwan, Thailand",
    bandLabelMhz: 923,
    carrierDefaultMhz: 923.2,
    bandMinMhz: 915.0,
    bandMaxMhz: 928.0,
    countries: ["BN","KH","ID","JP","LA","NZ","SG","TW","TH"],
  },
  {
    code: "AS923-2",
    label: "AS923-2 — Vietnam, Indonesia",
    bandLabelMhz: 923,
    carrierDefaultMhz: 921.4,
    bandMinMhz: 920.0,
    bandMaxMhz: 923.0,
    countries: ["VN","ID"],
  },
  {
    code: "AS923-3",
    label: "AS923-3 — Indonesia (sub-band 3)",
    bandLabelMhz: 915,
    carrierDefaultMhz: 916.6,
    bandMinMhz: 915.0,
    bandMaxMhz: 921.0,
    countries: ["ID"],
  },
  {
    code: "AS923-4",
    label: "AS923-4 — Israel",
    bandLabelMhz: 915,
    carrierDefaultMhz: 917.3,
    bandMinMhz: 917.0,
    bandMaxMhz: 920.0,
    countries: ["IL"],
  },
]);

/** @type {Readonly<Record<string, LoRaRegion>>} */
export const REGIONS_BY_CODE = Object.freeze(
  Object.fromEntries(LORA_REGIONS.map((r) => [r.code, r])),
);

// Region mặc định của dự án (Đà Nẵng → AS923-2).
export const DEFAULT_REGION = REGIONS_BY_CODE["AS923-2"];

/** @param {string} code */
export function resolveRegion(code) {
  const r = REGIONS_BY_CODE[code];
  if (!r) {
    throw new Error(
      `Unknown LoRa region: ${code}. Expected one of ${Object.keys(REGIONS_BY_CODE).sort().join(", ")}`,
    );
  }
  return r;
}

/** @param {string} iso2 */
export function regionsForCountry(iso2) {
  const code = iso2.toUpperCase();
  return LORA_REGIONS.filter((r) => r.countries.includes(code));
}
