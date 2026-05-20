"""ChirpStack protobuf → records mapping (private).

Adapter chuyển từ REST sang gRPC-web (xem _client.py docstring), nên input
mapping giờ là protobuf message types từ `chirpstack_api.api`:

  api.GatewayListItem:
    string gateway_id, string name, common.Location location,
    google.protobuf.Timestamp last_seen_at, ...

  api.DeviceListItem:
    string dev_eui, string name, google.protobuf.Timestamp last_seen_at, ...

Protobuf python attrs = snake_case. Timestamp WKT có `ToDatetime()` trả
naive datetime UTC — ta gán tzinfo tường minh. Location sub-message luôn
tồn tại trên wire (proto3 default = struct rỗng); skip khi lat=lon=0
(placeholder "chưa cấu hình" — convention của ChirpStack UI).
"""

from __future__ import annotations

from datetime import datetime, timezone

from chirpstack_api import api
from google.protobuf.timestamp_pb2 import Timestamp

from ..base import DeviceRecord, GatewayRecord


def gateway_record(raw: api.GatewayListItem) -> GatewayRecord | None:
    eui = (raw.gateway_id or "").strip()
    if not eui:
        return None

    # Proto3 message-typed field — luôn instantiate, kiểm tra qua lat/lon=0.
    # Một số deployment đặt gateway chưa cấu hình location, ChirpStack UI
    # cũng skip render những gateway đó.
    loc = raw.location
    lat = float(loc.latitude)
    lon = float(loc.longitude)
    if lat == 0.0 and lon == 0.0:
        return None
    if not -90.0 <= lat <= 90.0 or not -180.0 <= lon <= 180.0:
        return None

    altitude = float(loc.altitude) if loc.altitude else None

    return GatewayRecord(
        external_id=eui,
        latitude=lat,
        longitude=lon,
        altitude_m=altitude,
        label=_opt_str(raw.name),
    )


def device_record(raw: api.DeviceListItem) -> DeviceRecord | None:
    """Map 1 DeviceListItem → DeviceRecord. Trả None nếu thiếu dev_eui.

    `external_id` = `dev_eui` lowercased (canonical id ở ChirpStack); index
    DB UNIQUE (source_type, external_id) → idempotent re-sync.
    """
    dev_eui = (raw.dev_eui or "").strip()
    if not dev_eui:
        return None
    dev_eui_lower = dev_eui.lower()
    return DeviceRecord(
        external_id=dev_eui_lower,
        dev_eui=dev_eui_lower,
        name=_opt_str(raw.name),
        last_seen_at=_opt_ts(raw.last_seen_at),
    )


def _opt_ts(ts: Timestamp | None) -> datetime | None:
    """Timestamp WKT → tz-aware UTC datetime. Trả None khi field chưa set
    (seconds=nanos=0 — proto3 default cho message ZERO).
    """
    if ts is None:
        return None
    if ts.seconds == 0 and ts.nanos == 0:
        return None
    return ts.ToDatetime().replace(tzinfo=timezone.utc)


def _opt_str(v: str | None) -> str | None:
    if v is None:
        return None
    s = v.strip()
    return s or None
