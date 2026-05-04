"""
services/uplink_ingest.py — Logic persist uplink ChirpStack dùng chung.

Tách từ routers/webhook.py để cả HTTP webhook và MQTT listener gọi
cùng một code path. Không phụ thuộc vào FastAPI Request — nhận body
JSON đã parse và data_source string.
"""

from __future__ import annotations

import base64
import logging
import struct
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from models.orm import Device, Gateway, Measurement

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# GPS decoder — configurable format theo firmware
# Default: lat(4B int32 /1e4) + lon(4B int32 /1e4) + alt(2B uint16 cm)
# ─────────────────────────────────────────────────────────────

GPS_PAYLOAD_FORMATS = {
    # name       fmt      (lat_div, lon_div, alt_div)
    "default":  (">iiH",  (1e4, 1e4, 100.0)),
    "cayenne":  (">iiH",  (1e4, 1e4, 100.0)),
    "precise7": (">iiH",  (1e7, 1e7, 100.0)),    # lat/lon 1e-7
}


def decode_gps_payload(raw: bytes, fmt_name: str = "default") -> Optional[dict]:
    """Decode GPS từ bytes. Trả None nếu không decode được."""
    fmt_tuple = GPS_PAYLOAD_FORMATS.get(fmt_name, GPS_PAYLOAD_FORMATS["default"])
    fmt, (lat_div, lon_div, alt_div) = fmt_tuple

    try:
        size = struct.calcsize(fmt)
        if len(raw) < size:
            return None
        lat_raw, lon_raw, alt_raw = struct.unpack(fmt, raw[:size])
        return {
            "latitude":   lat_raw / lat_div,
            "longitude":  lon_raw / lon_div,
            "altitude_m": alt_raw / alt_div,
        }
    except Exception as e:
        logger.warning("gps_decode_failed", extra={"reason": str(e), "fmt": fmt_name})
        return None


# ─────────────────────────────────────────────────────────────
# Persist uplink — shared core
# ─────────────────────────────────────────────────────────────

class InvalidUplinkError(ValueError):
    """Body thiếu field bắt buộc (devEui, rxInfo)."""


async def persist_chirpstack_uplink(
    db:          AsyncSession,
    body:        dict,
    data_source: str,
) -> dict:
    """
    Parse 1 uplink ChirpStack JSON và lưu measurement.

    Idempotency theo (device_id, gateway_id, frame_count) trong cửa sổ 5 phút
    (LoRaWAN DedupWindow). Cùng uplink đến nhiều gateway → mỗi gateway 1 record.

    Args:
        db:          async session đã mở.
        body:        ChirpStack uplink JSON đã parse.
        data_source: ghi vào measurements.data_source (ví dụ "webhook:slug",
                     "mqtt"). Không commit — caller tự commit.

    Returns:
        {"devEui", "saved", "deduplicated", "gps", "errors"}.

    Raises:
        InvalidUplinkError: thiếu devEui hoặc rxInfo.
    """
    device_info  = body.get("deviceInfo", {})
    dev_eui      = device_info.get("devEui", "").replace(":", "").lower()
    rx_info_list = body.get("rxInfo", [])

    if not dev_eui or not rx_info_list:
        raise InvalidUplinkError("missing devEui or rxInfo")

    # GPS (nếu có payload)
    gps = None
    data_b64 = body.get("data")
    if data_b64:
        try:
            raw = base64.b64decode(data_b64)
            gps = decode_gps_payload(raw)
        except Exception as e:
            logger.warning("gps_base64_failed", extra={"reason": str(e)})

    tx_info     = body.get("txInfo", {})
    lora_mod    = tx_info.get("modulation", {}).get("lora", {})
    sf          = lora_mod.get("spreadingFactor")
    bw_hz       = lora_mod.get("bandwidth")
    bw_khz      = int(bw_hz / 1000) if bw_hz else None
    frame_count = body.get("fCnt")

    device = (await db.execute(
        select(Device).where(Device.dev_eui == dev_eui)
    )).scalars().first()

    saved        = 0
    deduplicated = 0
    errors: list = []

    for rx in rx_info_list:
        gw_eui = rx.get("gatewayId", "").replace(":", "").lower()
        rssi   = rx.get("rssi")
        snr    = rx.get("snr")
        if rssi is None:
            continue

        gateway = (await db.execute(
            select(Gateway).where(Gateway.gateway_eui == gw_eui)
        )).scalars().first()

        if not gateway:
            errors.append({"gatewayEui": gw_eui, "reason": "not_found"})
            continue

        # Idempotency (LoRaWAN DedupWindow 5 phút)
        if frame_count is not None and device:
            dup = (await db.execute(text("""
                SELECT 1 FROM measurements
                WHERE device_id = :did
                  AND gateway_id = :gid
                  AND frame_count = :fc
                  AND deleted_at IS NULL
                  AND measured_at > NOW() - INTERVAL '5 minutes'
                LIMIT 1
            """), {
                "did": str(device.id), "gid": str(gateway.id), "fc": frame_count,
            })).first()
            if dup:
                deduplicated += 1
                continue

        location_wkt = None
        altitude_m   = None
        if gps:
            location_wkt = f"SRID=4326;POINT({gps['longitude']} {gps['latitude']})"
            altitude_m   = gps.get("altitude_m")

        db.add(Measurement(
            gateway_id       = gateway.id,
            device_id        = device.id if device else None,
            location         = location_wkt,
            altitude_m       = altitude_m,
            rssi_dbm         = float(rssi),
            snr_db           = float(snr) if snr is not None else None,
            spreading_factor = sf,
            bandwidth_khz    = bw_khz,
            frame_count      = frame_count,
            measured_at      = datetime.now(timezone.utc),
            data_source      = data_source,
        ))
        saved += 1

    return {
        "devEui":       dev_eui,
        "saved":        saved,
        "deduplicated": deduplicated,
        "gps":          gps,
        "errors":       errors,
    }
