"""
scripts/lpwan_import.py

Import measurements từ file JSON lpwanmapper (POST /data) vào DB.

Logic:
  1. Đọc file response_data.json (list ChirpStack records)
  2. Với mỗi record:
     - Parse GPS từ object.gnss_latitude / gnss_longitude (skip nếu = 0 hoặc out-of-range)
     - Tìm device theo devEui trong DB (skip nếu chưa bootstrap)
     - Với mỗi rxInfo (1 packet có thể được nhiều gateway nhận):
       - Tìm gateway theo gatewayId
       - Tạo 1 measurement (gateway_id, device_id, location, rssi, snr, sf, bw, time)
     - Gắn campaign theo tháng của `time`

Dedup: (device_id, gateway_id, frame_count, measured_at) — skip nếu trùng.
Batch: commit sau mỗi 500 measurement để tránh OOM.

Chạy:
  docker exec -it lora_api python scripts/lpwan_import.py response_data.json
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal as async_session
from models.orm import Device, Gateway, Measurement


DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "lpwan"

# Campaign UUID theo tháng (khớp với lpwan_bootstrap.py)
CAMPAIGN_BY_MONTH = {
    (2025, 11): uuid.UUID("c0000000-0000-0000-0000-000000000011"),
    (2025, 12): uuid.UUID("c0000000-0000-0000-0000-000000000012"),
    (2026,  1): uuid.UUID("c0000000-0000-0000-0000-000000000001"),
    (2026,  2): uuid.UUID("c0000000-0000-0000-0000-000000000002"),
}

# Giới hạn GPS hợp lệ (Đà Nẵng ± vùng lân cận)
LAT_MIN, LAT_MAX = 15.5, 16.5
LON_MIN, LON_MAX = 107.5, 108.5

BATCH_SIZE = 500


def parse_gps(obj: dict) -> Optional[dict]:
    """Parse GPS từ field `object` của payload. Trả None nếu không hợp lệ."""
    lat = obj.get("gnss_latitude")
    lon = obj.get("gnss_longitude")
    alt = obj.get("gnss_altitude")

    if lat in (None, 0) or lon in (None, 0):
        return None

    # Một số packet lưu lat/lon dạng integer × 1e7 (hiếm trong file này nhưng xử lý cho chắc)
    if isinstance(lat, int) and abs(lat) > 1_000_000:
        lat = lat / 1e7
        lon = lon / 1e7

    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return None

    # Validate Đà Nẵng range
    if not (LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX):
        return None

    return {
        "latitude": lat,
        "longitude": lon,
        "altitude_m": float(alt) if alt not in (None, 0) else None,
    }


def pick_campaign(measured_at: datetime) -> Optional[uuid.UUID]:
    """Chọn campaign theo tháng của measured_at."""
    return CAMPAIGN_BY_MONTH.get((measured_at.year, measured_at.month))


async def load_dev_gw_maps(db: AsyncSession):
    """Load toàn bộ devices + gateways vào dict memory để tránh query từng lần."""
    devices = {
        d.dev_eui: d.id
        for d in (await db.execute(select(Device))).scalars().all()
    }
    gateways = {
        g.gateway_eui: g.id
        for g in (await db.execute(select(Gateway))).scalars().all()
    }
    return devices, gateways


async def import_file(db: AsyncSession, records: list[dict]):
    devices, gateways = await load_dev_gw_maps(db)
    print(f"   → DB có {len(devices)} devices, {len(gateways)} gateways")

    stats = {
        "total_records":    len(records),
        "skip_no_device":   0,
        "skip_no_gps":      0,
        "skip_no_gateway":  0,
        "skip_no_campaign": 0,
        "skip_duplicate":   0,
        "inserted":         0,
    }

    batch: list[Measurement] = []

    for rec in records:
        # 1. Parse time
        time_str = rec.get("time")
        if not time_str:
            continue
        try:
            measured_at = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
        except ValueError:
            continue

        # 2. Pick campaign theo tháng
        campaign_id = pick_campaign(measured_at)
        if not campaign_id:
            stats["skip_no_campaign"] += 1
            continue

        # 3. Parse GPS
        gps = parse_gps(rec.get("object", {}))
        if not gps:
            stats["skip_no_gps"] += 1
            continue

        # 4. Device
        dev_eui = rec.get("deviceInfo", {}).get("devEui", "").lower()
        device_id = devices.get(dev_eui)
        if not device_id:
            stats["skip_no_device"] += 1
            continue

        # 5. Lora params
        lora        = rec.get("txInfo", {}).get("modulation", {}).get("lora", {})
        sf          = lora.get("spreadingFactor")
        bw_hz       = lora.get("bandwidth")
        bw_khz      = int(bw_hz / 1000) if bw_hz else None
        code_rate_s = lora.get("codeRate", "")  # "CR_4_5" → 5
        coding_rate = None
        if code_rate_s.startswith("CR_4_"):
            try:
                coding_rate = int(code_rate_s.split("_")[-1])
            except ValueError:
                pass

        frame_count = rec.get("fCnt")

        # 6. Với mỗi gateway nhận được packet → 1 measurement
        for rx in rec.get("rxInfo", []):
            gw_eui    = rx.get("gatewayId", "").lower()
            gateway_id = gateways.get(gw_eui)
            if not gateway_id:
                stats["skip_no_gateway"] += 1
                continue

            rssi = rx.get("rssi")
            snr  = rx.get("snr")
            if rssi is None:
                continue

            # Location: ưu tiên GPS từ device, fallback gateway location
            batch.append(Measurement(
                gateway_id       = gateway_id,
                campaign_id      = campaign_id,
                device_id        = device_id,
                location         = f"SRID=4326;POINT({gps['longitude']} {gps['latitude']})",
                altitude_m       = gps.get("altitude_m"),
                rssi_dbm         = float(rssi),
                snr_db           = float(snr) if snr is not None else None,
                spreading_factor = sf,
                bandwidth_khz    = bw_khz,
                coding_rate      = coding_rate,
                frame_count      = frame_count,
                measured_at      = measured_at,
                data_source      = "lpwanmapper",
            ))

            # Commit batch
            if len(batch) >= BATCH_SIZE:
                db.add_all(batch)
                try:
                    await db.commit()
                    stats["inserted"] += len(batch)
                except Exception as e:
                    await db.rollback()
                    # Nhiều khả năng duplicate → thử từng cái 1
                    for m in batch:
                        try:
                            db.add(m)
                            await db.commit()
                            stats["inserted"] += 1
                        except Exception:
                            await db.rollback()
                            stats["skip_duplicate"] += 1
                batch.clear()

    # Commit phần còn lại
    if batch:
        db.add_all(batch)
        try:
            await db.commit()
            stats["inserted"] += len(batch)
        except Exception:
            await db.rollback()
            for m in batch:
                try:
                    db.add(m)
                    await db.commit()
                    stats["inserted"] += 1
                except Exception:
                    await db.rollback()
                    stats["skip_duplicate"] += 1

    return stats


async def main():
    # Lấy file từ argv hoặc default
    if len(sys.argv) > 1:
        json_file = Path(sys.argv[1])
        if not json_file.is_absolute():
            json_file = DATA_DIR / json_file
    else:
        json_file = DATA_DIR / "response_data.json"

    if not json_file.exists():
        print(f"❌ Không thấy {json_file}")
        print(f"   Cách chạy: python scripts/lpwan_import.py <tên_file.json>")
        print(f"   Default: response_data.json trong {DATA_DIR}")
        sys.exit(1)

    print(f"📂 Loading {json_file.name}...")
    with open(json_file) as f:
        records = json.load(f)

    if not isinstance(records, list):
        print(f"❌ File JSON phải là list (ChirpStack records), nhận được: {type(records).__name__}")
        sys.exit(1)

    print(f"   → {len(records)} records\n")
    print("🚀 Import vào DB...")

    async with async_session() as db:
        stats = await import_file(db, records)

    print("\n📊 Kết quả:")
    print(f"   ├─ Total records:        {stats['total_records']}")
    print(f"   ├─ Inserted:            {stats['inserted']}  ✓")
    print(f"   ├─ Skip: no GPS         {stats['skip_no_gps']}")
    print(f"   ├─ Skip: no device      {stats['skip_no_device']}")
    print(f"   ├─ Skip: no gateway     {stats['skip_no_gateway']}")
    print(f"   ├─ Skip: no campaign    {stats['skip_no_campaign']}")
    print(f"   └─ Skip: duplicate       {stats['skip_duplicate']}")
    print("\n✅ Done!")


if __name__ == "__main__":
    asyncio.run(main())
