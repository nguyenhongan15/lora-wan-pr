"""JSON → records mapping (private).

API doc /login: gateway shape là {gatewayId, latitude, longitude, altitude}
— deterministic.

API /data trả ARRAY of ChirpStack uplinks (lpwanmapper lưu nguyên uplink
user POST vào webhook). 1 uplink = N rxInfo entries (1 entry / gateway nhận
được uplink đó) → 1 uplink emit N MeasurementRecord.

Schema thực tế (xem r-dt/response_*.json):
  - top: `_id`, `time`, `txInfo.frequency` (Hz), `txInfo.modulation.lora.spreadingFactor`
  - device: `deviceInfo.deviceName` hoặc `deviceInfo.devEui`
  - device GPS: `object.gnss_latitude`, `object.gnss_longitude` (scaled int = degree*1e7)
  - rxInfo[]: mỗi entry có `gatewayId`, `rssi`, `snr`, `gwTime`
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from ..base import GatewayRecord, MeasurementRecord

# GNSS payload từ object.gnss_* thường là signed int = degree * 1e7. Heuristic:
# nếu |x| > 360, assume scaled.
_GNSS_SCALE_THRESHOLD = 360.0
_GNSS_SCALE = 1e7


def gateway_record(raw: dict[str, Any]) -> GatewayRecord | None:
    try:
        return GatewayRecord(
            external_id=str(raw["gatewayId"]),
            latitude=float(raw["latitude"]),
            longitude=float(raw["longitude"]),
            altitude_m=_opt_float(raw.get("altitude")),
            label=None,  # /login response không có name
        )
    except (KeyError, TypeError, ValueError):
        return None


def measurement_records(uplink: dict[str, Any]) -> Iterator[MeasurementRecord]:
    """1 uplink → 0..N MeasurementRecord (1 / rxInfo gateway).

    Skip silently nếu uplink thiếu trường essential — không raise.
    """
    dev_info = uplink.get("deviceInfo") or {}
    device = (
        dev_info.get("deviceName")
        or dev_info.get("devEui")
        or uplink.get("devEui")
        or uplink.get("deviceName")
    )
    if not device:
        return

    tx = uplink.get("txInfo") or {}
    sf = (tx.get("modulation") or {}).get("lora", {}).get("spreadingFactor") if isinstance(tx, dict) else None
    freq_mhz = _opt_freq_mhz(tx.get("frequency") if isinstance(tx, dict) else None)

    obj = uplink.get("object") or {}
    dev_lat = _decode_gnss(obj.get("gnss_latitude"))
    dev_lon = _decode_gnss(obj.get("gnss_longitude"))
    if dev_lat is None or dev_lon is None:
        return
    if not -90.0 <= dev_lat <= 90.0 or not -180.0 <= dev_lon <= 180.0:
        return

    uplink_id = uplink.get("_id") or uplink.get("id")
    uplink_time = _parse_time(uplink.get("time"))

    rx_list = uplink.get("rxInfo")
    if not isinstance(rx_list, list):
        return

    for rx in rx_list:
        if not isinstance(rx, dict):
            continue
        rssi = _opt_float(rx.get("rssi"))
        gw_id = _opt_str(rx.get("gatewayId"))
        if rssi is None or gw_id is None:
            continue
        rx_time = _parse_time(rx.get("gwTime")) or uplink_time
        if rx_time is None:
            continue

        eid = (
            f"{uplink_id}@{gw_id}"
            if uplink_id
            else f"{device}@{rx_time.isoformat()}@{gw_id}"
        )

        yield MeasurementRecord(
            external_id=eid,
            time=rx_time,
            latitude=dev_lat,
            longitude=dev_lon,
            rssi_dbm=rssi,
            snr_db=_opt_float(rx.get("snr")),
            spreading_factor=_opt_int(sf),
            frequency_mhz=freq_mhz,
            device_external_id=str(device),
            serving_gateway_external_id=gw_id,
        )


# ─── helpers ────────────────────────────────────────────────────────────────


def _opt_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _opt_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _opt_str(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _opt_freq_mhz(v: Any) -> float | None:
    """txInfo.frequency là Hz (vd 922200000). Convert → MHz."""
    f = _opt_float(v)
    if f is None or f <= 0:
        return None
    return f / 1_000_000 if f > 10_000 else f


def _decode_gnss(v: Any) -> float | None:
    """Trả độ (degrees). Hỗ trợ float trực tiếp + scaled-int (deg * 1e7).

    Loại 0 vì decoder thường trả 0 khi chưa fix GPS.
    """
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f == 0.0:
        return None
    if abs(f) > _GNSS_SCALE_THRESHOLD:
        f = f / _GNSS_SCALE
    return f


def _parse_time(v: Any) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=UTC)
    if isinstance(v, str):
        try:
            s = v.replace("Z", "+00:00") if v.endswith("Z") else v
            dt = datetime.fromisoformat(s)
            return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
        except ValueError:
            return None
    if isinstance(v, int | float):
        ts = v / 1000 if v > 1e12 else v
        try:
            return datetime.fromtimestamp(ts, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    return None
