"""ChirpStack JSON → records mapping (private).

Gateway shape (v4 REST):
  {
    "gatewayId": "0102030405060708",   # EUI-64 hex
    "name": "...",
    "description": "...",
    "location": {"latitude": 10.0, "longitude": 105.0, "altitude": 50.0,
                 "source": "GPS", "accuracy": 5.0},
    "tenantId": "...",
    "createdAt": "...", "updatedAt": "...", "lastSeenAt": "...",
  }

Một số deployment trả "id" thay cho "gatewayId"; accept cả 2.
Skip gateway thiếu location hoặc lat/lon = 0 (gateway chưa có toạ độ).
"""

from __future__ import annotations

from typing import Any

from ..base import GatewayRecord


def gateway_record(raw: dict[str, Any]) -> GatewayRecord | None:
    eui = _opt_str(raw.get("gatewayId")) or _opt_str(raw.get("id"))
    if not eui:
        return None

    loc = raw.get("location")
    if not isinstance(loc, dict):
        return None
    lat = _opt_float(loc.get("latitude"))
    lon = _opt_float(loc.get("longitude"))
    if lat is None or lon is None:
        return None
    if lat == 0.0 and lon == 0.0:
        return None  # placeholder toạ độ "chưa cấu hình"
    if not -90.0 <= lat <= 90.0 or not -180.0 <= lon <= 180.0:
        return None

    return GatewayRecord(
        external_id=eui,
        latitude=lat,
        longitude=lon,
        altitude_m=_opt_float(loc.get("altitude")),
        label=_opt_str(raw.get("name")),
    )


def _opt_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _opt_str(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None
