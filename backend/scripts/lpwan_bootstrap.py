"""
scripts/lpwan_bootstrap.py

Khởi tạo DB từ metadata lpwanmapper:
  1. Tạo 1 project
  2. INSERT 11 gateways từ response_get_data.json
  3. INSERT 3 devices từ response_devices_latest.json
  4. Tạo sẵn 4 campaigns theo tháng (Nov 2025, Dec 2025, Jan 2026, Feb 2026)

Chỉ chạy 1 LẦN khi setup DB mới.
Chạy lại sẽ SKIP các record đã tồn tại.

Cách chạy:
  docker exec -it lora_api python scripts/lpwan_bootstrap.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import date
from pathlib import Path

# Cho phép import từ backend root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal as async_session
from models.orm import Campaign, Device, Gateway, Project


# ─── Paths ──────────────────────────────────────────────────────
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "lpwan"

# File từ API lpwanmapper GET /get_data: chứa metadata gateways
GET_DATA_FILE = DATA_DIR / "response_get_data.json"
# File từ API lpwanmapper POST /devices/latest: có chi tiết devices
LATEST_FILE   = DATA_DIR / "response_devices_latest.json"


# ─── Project cố định (có thể đổi tên sau) ───────────────────────
PROJECT_ID   = uuid.UUID("a0000000-0000-0000-0000-000000000001")
PROJECT_NAME = "LoRa Da Nang Coverage"


# ─── Campaigns mặc định theo tháng ──────────────────────────────
# Đặt tên rõ ràng để dễ chọn trong UI
CAMPAIGNS = [
    {"id": "c0000000-0000-0000-0000-000000000011", "name": "Data 2025-11 (Tháng 11/2025)",
     "start": date(2025, 11, 1), "end": date(2025, 11, 30), "env": "urban"},
    {"id": "c0000000-0000-0000-0000-000000000012", "name": "Data 2025-12 (Tháng 12/2025)",
     "start": date(2025, 12, 1), "end": date(2025, 12, 31), "env": "urban"},
    {"id": "c0000000-0000-0000-0000-000000000001", "name": "Data 2026-01 (Tháng 1/2026)",
     "start": date(2026, 1, 1),  "end": date(2026, 1, 31), "env": "urban"},
    {"id": "c0000000-0000-0000-0000-000000000002", "name": "Data 2026-02 (Tháng 2/2026)",
     "start": date(2026, 2, 1),  "end": date(2026, 2, 28), "env": "urban"},
]


# ─── Device metadata thủ công (từ file latest) ──────────────────
# Tên các device lấy từ deviceNames trong response_get_data.json
DEVICE_NAMES = ["board01", "node01", "node3"]


async def upsert_project(db: AsyncSession) -> uuid.UUID:
    existing = (await db.execute(
        select(Project).where(Project.id == PROJECT_ID)
    )).scalars().first()

    if existing:
        print(f"  [skip] project đã tồn tại: {existing.name}")
        return existing.id

    db.add(Project(
        id=PROJECT_ID,
        name=PROJECT_NAME,
        description="Project tự động tạo từ lpwanmapper bootstrap",
        organization="DNIIT",
    ))
    await db.flush()
    print(f"  [insert] project: {PROJECT_NAME}")
    return PROJECT_ID


async def upsert_gateways(db: AsyncSession, gateways_raw: list[dict]):
    inserted = skipped = 0
    for gw in gateways_raw:
        eui = gw["gatewayId"].lower()

        existing = (await db.execute(
            select(Gateway).where(Gateway.gateway_eui == eui)
        )).scalars().first()

        if existing:
            skipped += 1
            continue

        lat = gw.get("latitude")
        lon = gw.get("longitude")
        alt = gw.get("altitude")

        location_wkt = None
        if lat is not None and lon is not None:
            location_wkt = f"SRID=4326;POINT({lon} {lat})"

        db.add(Gateway(
            project_id   = PROJECT_ID,
            gateway_eui  = eui,
            name         = f"GW-{eui[-6:].upper()}",
            location     = location_wkt,
            altitude_m   = alt,
            # Không có thông tin antenna/tx_power từ lpwanmapper → để NULL
        ))
        inserted += 1

    print(f"  gateways: +{inserted} inserted, {skipped} skipped (đã tồn tại)")


async def upsert_devices(db: AsyncSession, devices_from_latest: list[dict]):
    """Lấy dev_eui từ deviceInfo trong file /devices/latest."""
    inserted = skipped = 0
    seen_euis = set()

    for rec in devices_from_latest:
        dev_info = rec.get("deviceInfo", {})
        dev_eui  = dev_info.get("devEui", "").lower()
        dev_name = dev_info.get("deviceName")
        profile  = dev_info.get("deviceProfileName")  # GPS, GPS2, GPSdecode

        if not dev_eui or dev_eui in seen_euis:
            continue
        seen_euis.add(dev_eui)

        existing = (await db.execute(
            select(Device).where(Device.dev_eui == dev_eui)
        )).scalars().first()

        if existing:
            skipped += 1
            continue

        db.add(Device(
            project_id  = PROJECT_ID,
            dev_eui     = dev_eui,
            name        = dev_name,
            device_type = profile or "lora_tracker",
        ))
        inserted += 1

    print(f"  devices: +{inserted} inserted, {skipped} skipped")


async def upsert_campaigns(db: AsyncSession):
    inserted = skipped = 0
    for c in CAMPAIGNS:
        cid = uuid.UUID(c["id"])
        existing = (await db.execute(
            select(Campaign).where(Campaign.id == cid)
        )).scalars().first()

        if existing:
            skipped += 1
            continue

        db.add(Campaign(
            id                = cid,
            project_id        = PROJECT_ID,
            name              = c["name"],
            environment_type  = c["env"],
            start_date        = c["start"],
            end_date          = c["end"],
            weather_condition = "clear",
        ))
        inserted += 1

    print(f"  campaigns: +{inserted} inserted, {skipped} skipped")


async def main():
    # Load files
    if not GET_DATA_FILE.exists():
        print(f"❌ Không thấy {GET_DATA_FILE}")
        print(f"   Đặt file response_get_data.json (từ lpwanmapper GET /get_data) vào folder này.")
        sys.exit(1)

    if not LATEST_FILE.exists():
        print(f"❌ Không thấy {LATEST_FILE}")
        print(f"   Đặt file response_devices_latest.json (từ POST /devices/latest).")
        sys.exit(1)

    with open(GET_DATA_FILE) as f:
        get_data = json.load(f)

    with open(LATEST_FILE) as f:
        latest_data = json.load(f)

    gateways_raw = get_data.get("gateways", [])
    print(f"\n📂 Loaded: {len(gateways_raw)} gateways, {len(latest_data)} latest records")

    print("\n🚀 Bootstrap DB from lpwanmapper data...")
    async with async_session() as db:
        await upsert_project(db)
        await upsert_gateways(db, gateways_raw)
        await upsert_devices(db, latest_data)
        await upsert_campaigns(db)
        await db.commit()

    print("\n✅ Bootstrap xong!")
    print("   Bước tiếp theo: chạy `python scripts/lpwan_import.py` để import measurements.")


if __name__ == "__main__":
    asyncio.run(main())
