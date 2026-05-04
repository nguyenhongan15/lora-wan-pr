"""
routers/campaigns.py
─────────────────────
GET  /campaigns/              — list tất cả campaign
POST /campaigns/import-config — upsert gateway + device từ JSON config

Sửa theo TS002: DevEUI PHẢI là 16 hex chars thật (8 bytes),
không fake bằng pad '0'.
"""

import re
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import ValidationError
from core.responses import ok
from database import get_db
from models.orm import Device, Gateway

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


# ── Schemas ──────────────────────────────────────────────────────────────────

_EUI_RE = re.compile(r"^[0-9a-fA-F]{16}$")


class DeviceInfo(BaseModel):
    """Device PHẢI có dev_eui hợp lệ (16 hex, LoRaWAN TS002 spec)."""
    name:     str
    dev_eui:  str = Field(..., alias="devEui")

    @field_validator("dev_eui")
    @classmethod
    def _validate_eui(cls, v: str) -> str:
        v = v.replace(":", "").lower()
        if not _EUI_RE.match(v):
            raise ValueError("devEui phải là 16 ký tự hex (8 bytes theo LoRaWAN TS002)")
        return v


class GatewayInfo(BaseModel):
    gateway_id: str            = Field(..., alias="gatewayId")
    latitude:   float
    longitude:  float
    altitude:   Optional[float] = None

    @field_validator("gateway_id")
    @classmethod
    def _validate_gw_eui(cls, v: str) -> str:
        v = v.replace(":", "").lower()
        if not _EUI_RE.match(v):
            raise ValueError("gatewayId phải là 16 ký tự hex (EUI)")
        return v


class ImportConfigRequest(BaseModel):
    token:       str
    webhook_url: str                 = Field(..., alias="webhookUrl")
    devices:     List[DeviceInfo]   # ĐỔI: phải truyền devEui thật
    gateways:    List[GatewayInfo]
    project_id:  str                 = Field(..., alias="projectId")


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/")
async def list_campaigns(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("SELECT id, name, environment_type, start_date, end_date, "
             "weather_condition FROM campaigns "
             "WHERE deleted_at IS NULL "
             "ORDER BY start_date DESC NULLS LAST")
    )
    items = [
        {
            "id":               str(r["id"]),
            "name":             r["name"],
            "environmentType":  r["environment_type"],
            "startDate":        r["start_date"].isoformat() if r["start_date"] else None,
            "endDate":          r["end_date"].isoformat()   if r["end_date"]   else None,
            "weatherCondition": r["weather_condition"],
        }
        for r in result.mappings().all()
    ]
    return ok(items, meta={"total": len(items)})


@router.post("/import-config", status_code=status.HTTP_201_CREATED)
async def import_config(
    body: ImportConfigRequest,
    db:   AsyncSession = Depends(get_db),
):
    """
    Upsert gateway + device từ JSON config đã đăng ký.

    Lưu ý: devEui phải là EUI-64 thật (16 hex chars), không chấp nhận placeholder.
    """
    try:
        project_id = uuid.UUID(body.project_id)
    except ValueError:
        raise ValidationError("projectId không phải UUID hợp lệ.", code="INVALID_PROJECT_ID")

    # ── Upsert Gateways ─────────────────────────────────────────────────────
    gw_results = []
    for gw in body.gateways:
        existing = (await db.execute(
            select(Gateway).where(Gateway.gateway_eui == gw.gateway_id)
        )).scalars().first()

        wkt = f"SRID=4326;POINT({gw.longitude} {gw.latitude})"

        if existing:
            existing.location   = wkt
            existing.altitude_m = gw.altitude
            gw_results.append({"gatewayEui": gw.gateway_id, "action": "updated"})
        else:
            db.add(Gateway(
                project_id   = project_id,
                gateway_eui  = gw.gateway_id,
                name         = f"Gateway-{gw.gateway_id[-6:].upper()}",
                location     = wkt,
                altitude_m   = gw.altitude,
                installed_at = datetime.now(timezone.utc),
            ))
            gw_results.append({"gatewayEui": gw.gateway_id, "action": "created"})

    # ── Upsert Devices ──────────────────────────────────────────────────────
    dev_results = []
    for dev in body.devices:
        existing = (await db.execute(
            select(Device).where(Device.dev_eui == dev.dev_eui)
        )).scalars().first()

        if existing:
            dev_results.append({"devEui": dev.dev_eui, "action": "already_exists"})
        else:
            db.add(Device(
                project_id  = project_id,
                dev_eui     = dev.dev_eui,       # EUI thật, không fake
                name        = dev.name,
                device_type = "lora_node",
                created_at  = datetime.now(timezone.utc),
            ))
            dev_results.append({"devEui": dev.dev_eui, "action": "created"})

    await db.commit()

    return ok({
        "token":      body.token,
        "webhookUrl": body.webhook_url,
        "gateways":   gw_results,
        "devices":    dev_results,
    })
