"""Address domain types (F2 — lookup by address funnel).

Pure types + invariants. Theo data-architecture.md §3.4 AddressResolution
capability. Không phụ thuộc framework, không I/O.

Mục tiêu: input là chuỗi địa chỉ tự do (vd "Số 1 Lý Thường Kiệt, Hải Châu, Đà Nẵng")
→ output là toạ độ WGS84 + thông tin canonical đã chuẩn hoá.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

# Vietnam bounding box (rộng, để cho biên giới đảo + Trường Sa).
# Dùng để reject toạ độ rõ ràng không phải VN.
VN_LAT_MIN, VN_LAT_MAX = 8.0, 23.5
VN_LON_MIN, VN_LON_MAX = 102.0, 118.0


class GeocodingProvider(StrEnum):
    """Tier trong cascade. Chuỗi giá trị KHÔNG đổi (lưu vào address.canonical)."""

    POSTGRES = "postgres"  # cache nội bộ trong address.canonical
    NOMINATIM = "nominatim"  # OSM, free, rate-limited
    VIETMAP = "vietmap"  # paid, ưu tiên VN — defer
    GOONG = "goong"  # paid, alt — defer
    GOOGLE = "google"  # last resort — sponsor only, defer


_NORMALIZE_RE = re.compile(r"\s+")


def normalize_query(raw: str) -> str:
    """Chuẩn hoá địa chỉ thành key cache stable.

    Quy tắc:
      * lowercase
      * Unicode NFKD + bỏ dấu (diacritics) — match dữ liệu lưu unaccent
      * collapse whitespace
      * trim

    Không bỏ dấu phẩy/số/chữ — chúng có nghĩa.
    """
    if not raw:
        return ""
    # NFKD không tách được Đ/đ (precomposed, không có combining stroke) —
    # phải map tay trước khi strip combining chars.
    pre = raw.replace("Đ", "D").replace("đ", "d")
    nfkd = unicodedata.normalize("NFKD", pre)
    no_accent = "".join(c for c in nfkd if not unicodedata.combining(c))
    collapsed = _NORMALIZE_RE.sub(" ", no_accent.lower()).strip()
    return collapsed


@dataclass(frozen=True, slots=True)
class Address:
    """Input cho AddressResolution.lookup."""

    raw: str

    def __post_init__(self) -> None:
        if not self.raw or not self.raw.strip():
            raise ValueError("Address.raw không được rỗng")
        if len(self.raw) > 500:
            raise ValueError("Address.raw quá dài (>500 ký tự)")

    @property
    def normalized(self) -> str:
        return normalize_query(self.raw)


@dataclass(frozen=True, slots=True)
class AddressLookupResult:
    """Kết quả geocode 1 địa chỉ.

    `display_name` là chuỗi canonical (vd "1 Lý Thường Kiệt, Hải Châu, Đà Nẵng,
    Việt Nam") — KHÔNG nhất thiết bằng input.
    """

    latitude: float
    longitude: float
    display_name: str
    provider: GeocodingProvider
    confidence: float = 1.0  # [0,1] — provider tự đánh giá; cache = 1.0

    def __post_init__(self) -> None:
        if not -90.0 <= self.latitude <= 90.0:
            raise ValueError(f"latitude out of range: {self.latitude}")
        if not -180.0 <= self.longitude <= 180.0:
            raise ValueError(f"longitude out of range: {self.longitude}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0,1], got {self.confidence}")

    @property
    def is_in_vietnam(self) -> bool:
        return (
            VN_LAT_MIN <= self.latitude <= VN_LAT_MAX and VN_LON_MIN <= self.longitude <= VN_LON_MAX
        )
