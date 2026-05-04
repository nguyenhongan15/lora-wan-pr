"""
routers/lpwan_sync.py — Pull dữ liệu từ lpwanmapper.com → lưu vào measurement.

Endpoints:
  POST /sync/latest   → /devices/latest  (bản ghi mới nhất mỗi device)
  POST /sync/all      → /data            (toàn bộ, có limit)
  POST /sync/get      → /get_data        (webhook data của user)
  POST /sync/device   → /device/data     (1 device cụ thể)

Sửa theo chuẩn:
  - 1 auth header duy nhất: Authorization: Bearer <token>
  - Rate limit riêng cho endpoint sync (tốn bandwidth)
  - Trả 201 Created khi có measurement mới được lưu
  - camelCase JSON response
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from core.exceptions import AppError, ValidationError
from core.rate_limit import rate_limit_sync
from core.responses import ok
from database import get_db
from models.orm import Device, Gateway, Measurement

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sync", tags=["sync"])


class ExternalApiError(AppError):
    code        = "EXTERNAL_API_ERROR"
    http_status = 502


# ─────────────────────────────────────────────────────────────
# Build headers — 1 cách duy nhất, không spray 3 header cùng lúc
# ─────────────────────────────────────────────────────────────
def build_headers(token: Optional[str]) -> dict:
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


# ─────────────────────────────────────────────────────────────
# GPS parsing từ field `object` của lpwanmapper payload
# ─────────────────────────────────────────────────────────────
def parse_gps(obj: dict) -> Optional[dict]:
    lat = obj.get("gnss_latitude", 0)
    lon = obj.get("gnss_longitude", 0)
    alt = obj.get("gnss_altitude")

    if not lat or not lon:
        return None

    if isinstance(lat, int) and abs(lat) > 1_000_000:
        lat = lat / 1e7
        lon = lon / 1e7

    try:
        if not (5 < abs(float(lat)) < 90 and 100 < abs(float(lon)) < 180):
            return None
    except (TypeError, ValueError):
        return None

    return {
        "latitude":   float(lat),
        "longitude":  float(lon),
        "altitudeM":  float(alt) if alt else None,
    }


# ─────────────────────────────────────────────────────────────
# Persist 1 record
# ─────────────────────────────────────────────────────────────
async def save_record(record: dict, campaign_id: Optional[str], db: AsyncSession) -> dict:
    dev_info    = record.get("deviceInfo", {})
    dev_eui     = dev_info.get("devEui", "").lower()
    dev_name    = dev_info.get("deviceName", "unknown")
    gps         = parse_gps(record.get("object", {}))
    lora        = record.get("txInfo", {}).get("modulation", {}).get("lora", {})
    sf          = lora.get("spreadingFactor")
    bw_hz       = lora.get("bandwidth")
    bw_khz      = int(bw_hz / 1000) if bw_hz else None
    frame_count = record.get("fCnt")
    time_str    = record.get("time")
    measured_at = (
        datetime.fromisoformat(time_str.replace("Z", "+00:00"))
        if time_str else datetime.now(timezone.utc)
    )

    device = (await db.execute(
        select(Device).where(Device.dev_eui == dev_eui)
    )).scalars().first()

    saved    = 0
    skipped: list = []

    for rx in record.get("rxInfo", []):
        gw_eui = rx.get("gatewayId", "").lower()
        rssi   = rx.get("rssi")
        snr    = rx.get("snr")
        if rssi is None:
            continue

        gateway = (await db.execute(
            select(Gateway).where(Gateway.gateway_eui == gw_eui)
        )).scalars().first()
        if not gateway:
            skipped.append(gw_eui)
            continue

        location_wkt = None
        altitude_m   = None
        if gps:
            location_wkt = f"SRID=4326;POINT({gps['longitude']} {gps['latitude']})"
            altitude_m   = gps.get("altitudeM")

        db.add(Measurement(
            gateway_id       = gateway.id,
            device_id        = device.id if device else None,
            campaign_id      = campaign_id,
            location         = location_wkt,
            altitude_m       = altitude_m,
            rssi_dbm         = float(rssi),
            snr_db           = float(snr) if snr is not None else None,
            spreading_factor = sf,
            bandwidth_khz    = bw_khz,
            frame_count      = frame_count,
            measured_at      = measured_at,
            data_source      = "lpwanmapper",
        ))
        saved += 1

    return {
        "device":             dev_name,
        "devEui":             dev_eui,
        "gps":                gps,
        "measurementsSaved":  saved,
        "gatewaysNotInDb":    skipped,
    }


async def process_records(records, campaign_id, db) -> dict:
    if not isinstance(records, list):
        raise ExternalApiError("Response từ lpwanmapper không đúng định dạng.")
    results = [await save_record(r, campaign_id, db) for r in records]
    await db.commit()
    total_saved = sum(r["measurementsSaved"] for r in results)
    return {
        "status":             "ok",
        "recordsFetched":     len(records),
        "measurementsSaved":  total_saved,
        "detail":             results,
    }


# ─────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────
class SyncBase(BaseModel):
    token:       Optional[str] = Field(None, description="Token lpwanmapper")
    campaign_id: Optional[str] = Field(None, alias="campaignId")

    class Config:
        populate_by_name = True


class SyncAllRequest(SyncBase):
    limit: int = Field(1000, ge=1, le=10_000)


class SyncDeviceRequest(SyncBase):
    device_name: str = Field(..., alias="deviceName")


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
async def _call_upstream(
    method: str, url: str, *, token: Optional[str], json_body: dict | None = None,
    timeout: float = 15.0,
) -> list | dict:
    async with httpx.AsyncClient(timeout=timeout) as client:
        if method == "POST":
            resp = await client.post(url, headers=build_headers(token), json=json_body or {})
        else:
            resp = await client.get(url, headers=build_headers(token))

    if resp.status_code != 200:
        raise ExternalApiError(
            f"lpwanmapper trả về {resp.status_code}",
            details=[{"upstreamStatus": resp.status_code, "snippet": resp.text[:200]}],
        )
    return resp.json()


# ─────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────

@router.post("/latest", status_code=status.HTTP_201_CREATED)
async def sync_latest(
    body:    SyncBase,
    request: Request,
    db:      AsyncSession = Depends(get_db),
):
    rate_limit_sync(request)
    url  = f"{get_settings().lpwan_base_url}/devices/latest"
    data = await _call_upstream("POST", url, token=body.token, json_body={})
    return ok(await process_records(data, body.campaign_id, db))


@router.post("/all", status_code=status.HTTP_201_CREATED)
async def sync_all(
    body:    SyncAllRequest,
    request: Request,
    db:      AsyncSession = Depends(get_db),
):
    rate_limit_sync(request)
    url  = f"{get_settings().lpwan_base_url}/data"
    data = await _call_upstream("POST", url, token=body.token,
                                json_body={"limit": body.limit}, timeout=30.0)
    return ok(await process_records(data, body.campaign_id, db))


@router.post("/get", status_code=status.HTTP_201_CREATED)
async def sync_get(
    body:    SyncBase,
    request: Request,
    db:      AsyncSession = Depends(get_db),
):
    rate_limit_sync(request)
    url  = f"{get_settings().lpwan_base_url}/get_data"
    data = await _call_upstream("GET", url, token=body.token)
    return ok(await process_records(data, body.campaign_id, db))


@router.post("/device", status_code=status.HTTP_201_CREATED)
async def sync_device(
    body:    SyncDeviceRequest,
    request: Request,
    db:      AsyncSession = Depends(get_db),
):
    rate_limit_sync(request)
    url  = f"{get_settings().lpwan_base_url}/device/data"
    data = await _call_upstream(
        "POST", url, token=body.token,
        json_body={"deviceName": body.device_name}, timeout=30.0,
    )
    return ok(await process_records(data, body.campaign_id, db))
