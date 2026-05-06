"""Coordinate parser — input là chuỗi tự do, output (lat, lng) hoặc None.

Phục vụ F2 funnel (core-feature.md §2.2): user có thể nhập decimal hoặc DMS
trực tiếp vào ô địa chỉ. Tách thành module riêng để geocoding cascade
không phải đoán định dạng input.

Pure function, không I/O. Test với tests/unit/test_coordinate_parser.py.

Định dạng được hỗ trợ:
  * "16.0544, 108.2022"           — decimal lat,lng
  * "16.0544 108.2022"            — decimal whitespace-separated
  * "16°03'15.8\"N 108°12'07.9\"E" — DMS với hướng
  * "16 03 15.8 N, 108 12 07.9 E" — DMS spaces

Không hỗ trợ MGRS / UTM (out of scope cho v0.1).
"""

from __future__ import annotations

import re

# Decimal: hai số float liền nhau, phân tách bằng "," hoặc whitespace.
_DECIMAL_PAIR_RE = re.compile(r"^\s*(-?\d{1,3}(?:\.\d+)?)\s*[,\s]\s*(-?\d{1,3}(?:\.\d+)?)\s*$")

# DMS: bắt nhóm "deg [min [sec]] hemisphere" — hemisphere bắt buộc để phân biệt
# lat (N/S) khỏi lng (E/W). Cho phép unicode degree/prime hoặc ký tự ASCII.
_DMS_RE = re.compile(
    r"""
    (?P<deg>\d{1,3})            # độ
    (?:[°d\s]+
        (?P<min>\d{1,2}(?:\.\d+)?)
        (?:[\'′m\s]+
            (?P<sec>\d{1,2}(?:\.\d+)?)
            [\"″s]?
        )?
    )?
    \s*(?P<hemi>[NnSsEeWw])
    """,
    re.VERBOSE,
)


def _dms_to_decimal(deg: float, minutes: float, seconds: float, hemi: str) -> float:
    val = deg + minutes / 60.0 + seconds / 3600.0
    if hemi.upper() in ("S", "W"):
        val = -val
    return val


def parse_coordinates(raw: str) -> tuple[float, float] | None:
    """Trả (lat, lng) nếu chuỗi là tọa độ; None nếu không nhận diện được.

    Decimal được ưu tiên: nếu chuỗi vừa khớp decimal vừa khớp DMS thì decimal
    thắng (ít ambiguous hơn).
    """
    if not raw:
        return None
    text = raw.strip()
    if not text:
        return None

    m = _DECIMAL_PAIR_RE.match(text)
    if m is not None:
        try:
            lat = float(m.group(1))
            lng = float(m.group(2))
        except ValueError:
            return None
        return _validated(lat, lng)

    # DMS: cần đúng 2 match (lat + lng), với hemispheres N/S và E/W.
    matches = list(_DMS_RE.finditer(text))
    if len(matches) != 2:
        return None

    coords: list[tuple[float, str]] = []
    for mm in matches:
        deg = float(mm.group("deg"))
        minutes = float(mm.group("min") or 0)
        seconds = float(mm.group("sec") or 0)
        hemi = mm.group("hemi").upper()
        coords.append((_dms_to_decimal(deg, minutes, seconds, hemi), hemi))

    lat_val: float | None = None
    lng_val: float | None = None
    for v, hemi in coords:
        if hemi in ("N", "S") and lat_val is None:
            lat_val = v
        elif hemi in ("E", "W") and lng_val is None:
            lng_val = v
    if lat_val is None or lng_val is None:
        return None
    return _validated(lat_val, lng_val)


def _validated(lat: float, lng: float) -> tuple[float, float] | None:
    if not -90.0 <= lat <= 90.0:
        return None
    if not -180.0 <= lng <= 180.0:
        return None
    return (lat, lng)
