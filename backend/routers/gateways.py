"""routers/gateways.py — CRUD cho Gateway."""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.responses import ok
from database import get_db

router = APIRouter(prefix="/gateways", tags=["gateways"])


@router.get("/")
async def list_gateways(db: AsyncSession = Depends(get_db)):
    """Liệt kê tất cả gateway kèm tọa độ."""
    result = await db.execute(text("""
        SELECT
            id,
            name,
            gateway_eui,
            altitude_m,
            antenna_height_m,
            tx_power_dbm,
            antenna_type,
            ST_X(location::geometry) AS longitude,
            ST_Y(location::geometry) AS latitude,
            installed_at
        FROM gateways
        WHERE deleted_at IS NULL
        ORDER BY installed_at DESC NULLS LAST
    """))
    rows = result.mappings().all()

    items = [
        {
            "id":              str(r["id"]),
            "name":            r["name"],
            "gatewayEui":      r["gateway_eui"],
            "altitudeM":       r["altitude_m"],
            "antennaHeightM":  r["antenna_height_m"],
            "txPowerDbm":      r["tx_power_dbm"],
            "antennaType":     r["antenna_type"],
            "longitude":       r["longitude"],
            "latitude":        r["latitude"],
            "installedAt":     r["installed_at"].isoformat() if r["installed_at"] else None,
        }
        for r in rows
    ]
    return ok(items, meta={"total": len(items)})
