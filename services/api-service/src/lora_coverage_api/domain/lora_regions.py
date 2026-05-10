"""LoRaWAN regional parameters registry — RP002-1.0.4.

Source of truth cho mapping `region code` ↔ `band label` ↔ `carrier frequency`.
Pure data, không I/O, không phụ thuộc framework.

Mỗi region có:
  - code:                định danh ngắn theo LoRa Alliance (ví dụ "AS923-2")
  - label:               nhãn hiển thị cho UI ("AS923-2 — Vietnam, Indonesia")
  - band_label_mhz:      số tròn dùng cho DB CHECK constraint (433/868/915/923)
  - carrier_default_mhz: tần số channel 0 (dùng cho Friis/calibration)
  - band_min/max_mhz:    biên dải tần
  - countries:           mã ISO-3166 alpha-2 các quốc gia áp dụng

Tham khảo:
  LoRa Alliance — RP002-1.0.4 Regional Parameters
  (https://lora-alliance.org/resource_hub/rp002-1-0-4-regional-parameters/)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LoRaRegion:
    code: str
    label: str
    band_label_mhz: float
    carrier_default_mhz: float
    band_min_mhz: float
    band_max_mhz: float
    countries: tuple[str, ...]


# ── Sub-GHz LoRaWAN regions worldwide (RP002-1.0.4) ───────────────────────
EU433 = LoRaRegion(
    code="EU433",
    label="EU433 — Europe (ISM 433 MHz)",
    band_label_mhz=433.0,
    carrier_default_mhz=433.175,
    band_min_mhz=433.05,
    band_max_mhz=434.79,
    countries=(
        "AT",
        "BE",
        "BG",
        "CH",
        "CY",
        "CZ",
        "DE",
        "DK",
        "EE",
        "ES",
        "FI",
        "FR",
        "GB",
        "GR",
        "HR",
        "HU",
        "IE",
        "IT",
        "LT",
        "LU",
        "LV",
        "MT",
        "NL",
        "NO",
        "PL",
        "PT",
        "RO",
        "SE",
        "SI",
        "SK",
    ),
)

CN470 = LoRaRegion(
    code="CN470",
    label="CN470-510 — China",
    band_label_mhz=470.0,  # NOTE: chưa nằm trong DB CHECK constraint hiện tại
    carrier_default_mhz=486.3,
    band_min_mhz=470.0,
    band_max_mhz=510.0,
    countries=("CN",),
)

CN779 = LoRaRegion(
    code="CN779",
    label="CN779-787 — China (deprecated)",
    band_label_mhz=779.0,  # NOTE: deprecated, không dùng cho thiết kế mới
    carrier_default_mhz=779.5,
    band_min_mhz=779.0,
    band_max_mhz=787.0,
    countries=("CN",),
)

EU868 = LoRaRegion(
    code="EU868",
    label="EU863-870 — Europe",
    band_label_mhz=868.0,
    carrier_default_mhz=868.1,
    band_min_mhz=863.0,
    band_max_mhz=870.0,
    countries=(
        "AT",
        "BE",
        "BG",
        "CH",
        "CY",
        "CZ",
        "DE",
        "DK",
        "EE",
        "ES",
        "FI",
        "FR",
        "GB",
        "GR",
        "HR",
        "HU",
        "IE",
        "IT",
        "LT",
        "LU",
        "LV",
        "MT",
        "NL",
        "NO",
        "PL",
        "PT",
        "RO",
        "SE",
        "SI",
        "SK",
        "UA",
        "TR",
    ),
)

IN865 = LoRaRegion(
    code="IN865",
    label="IN865-867 — India",
    band_label_mhz=868.0,  # nhãn band gần nhất trong CHECK constraint
    carrier_default_mhz=865.0625,
    band_min_mhz=865.0,
    band_max_mhz=867.0,
    countries=("IN",),
)

RU864 = LoRaRegion(
    code="RU864",
    label="RU864-870 — Russia",
    band_label_mhz=868.0,
    carrier_default_mhz=868.9,
    band_min_mhz=864.0,
    band_max_mhz=870.0,
    countries=("RU",),
)

US915 = LoRaRegion(
    code="US915",
    label="US902-928 — USA, Canada, Mexico",
    band_label_mhz=915.0,
    carrier_default_mhz=903.9,
    band_min_mhz=902.0,
    band_max_mhz=928.0,
    countries=("US", "CA", "MX"),
)

AU915 = LoRaRegion(
    code="AU915",
    label="AU915-928 — Australia",
    band_label_mhz=915.0,
    carrier_default_mhz=916.8,
    band_min_mhz=915.0,
    band_max_mhz=928.0,
    countries=("AU",),
)

KR920 = LoRaRegion(
    code="KR920",
    label="KR920-923 — South Korea",
    band_label_mhz=923.0,
    carrier_default_mhz=922.1,
    band_min_mhz=920.9,
    band_max_mhz=923.3,
    countries=("KR",),
)

AS923_1 = LoRaRegion(
    code="AS923-1",
    label="AS923-1 — Brunei, Cambodia, Indonesia, Japan, Laos, NZ, Singapore, Taiwan, Thailand",
    band_label_mhz=923.0,
    carrier_default_mhz=923.2,
    band_min_mhz=915.0,
    band_max_mhz=928.0,
    countries=("BN", "KH", "ID", "JP", "LA", "NZ", "SG", "TW", "TH"),
)

AS923_2 = LoRaRegion(
    code="AS923-2",
    label="AS923-2 — Vietnam, Indonesia",
    band_label_mhz=923.0,
    carrier_default_mhz=921.4,
    band_min_mhz=920.0,
    band_max_mhz=923.0,
    countries=("VN", "ID"),
)

AS923_3 = LoRaRegion(
    code="AS923-3",
    label="AS923-3 — Indonesia (sub-band 3)",
    band_label_mhz=915.0,
    carrier_default_mhz=916.6,
    band_min_mhz=915.0,
    band_max_mhz=921.0,
    countries=("ID",),
)

AS923_4 = LoRaRegion(
    code="AS923-4",
    label="AS923-4 — Israel",
    band_label_mhz=915.0,
    carrier_default_mhz=917.3,
    band_min_mhz=917.0,
    band_max_mhz=920.0,
    countries=("IL",),
)


# ── Registry ──────────────────────────────────────────────────────────────
ALL_REGIONS: tuple[LoRaRegion, ...] = (
    EU433,
    CN470,
    CN779,
    EU868,
    IN865,
    RU864,
    US915,
    AU915,
    KR920,
    AS923_1,
    AS923_2,
    AS923_3,
    AS923_4,
)

REGIONS_BY_CODE: dict[str, LoRaRegion] = {r.code: r for r in ALL_REGIONS}

# Region mặc định của dự án (Đà Nẵng → AS923-2).
DEFAULT_REGION: LoRaRegion = AS923_2


def resolve_region(code: str) -> LoRaRegion:
    """Map region code → LoRaRegion. Allowlist; raise nếu không khớp."""
    try:
        return REGIONS_BY_CODE[code]
    except KeyError:
        raise ValueError(
            f"unknown LoRa region: {code!r}; expected one of {sorted(REGIONS_BY_CODE)}"
        ) from None


def regions_for_country(iso2: str) -> tuple[LoRaRegion, ...]:
    """Trả các regions hợp lệ cho 1 quốc gia. Một số nước có nhiều region."""
    code = iso2.upper()
    return tuple(r for r in ALL_REGIONS if code in r.countries)
