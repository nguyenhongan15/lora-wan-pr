"""
services/measurement_repo.py — Query measurement + gateway join logic.

Tách SQL khỏi router (Dependency Inversion).
"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def fetch_training_rows(
    db: AsyncSession,
    campaign_id: uuid.UUID,
    *,
    default_sf: int = 9,
) -> list[dict]:
    """
    Lấy measurements của campaign + JOIN gateways + environment_zones
    để có đủ feature cho training.
    """
    rows = (await db.execute(text("""
        SELECT
            ST_Y(m.location::geometry)  AS lat_rx,
            ST_X(m.location::geometry)  AS lng_rx,
            m.altitude_m                AS device_altitude_m,
            m.rssi_dbm,
            m.snr_db,
            COALESCE(m.spreading_factor, :default_sf)  AS spreading_factor,
            COALESCE(m.tx_power_dbm, g.tx_power_dbm)   AS tx_power_dbm,
            ST_Y(g.location::geometry)  AS lat_tx,
            ST_X(g.location::geometry)  AS lng_tx,
            g.altitude_m                AS gw_altitude_m,
            g.antenna_height_m,
            ez.building_density,
            ez.land_use
        FROM measurements m
        JOIN gateways g ON g.id = m.gateway_id
        LEFT JOIN environment_zones ez ON ez.id = m.zone_id
        WHERE m.campaign_id = :cid
          AND m.rssi_dbm IS NOT NULL
          AND m.location IS NOT NULL
          AND m.deleted_at IS NULL
        ORDER BY m.measured_at DESC
    """), {"cid": str(campaign_id), "default_sf": default_sf})).mappings().all()
    return [dict(r) for r in rows]


async def fetch_measurement_points(
    db: AsyncSession,
    campaign_id: uuid.UUID,
) -> list[dict]:
    """Lấy (lat, lng, rssi) — chỉ các field cần cho interpolation."""
    rows = (await db.execute(text("""
        SELECT
            ST_Y(location::geometry) AS lat,
            ST_X(location::geometry) AS lng,
            rssi_dbm
        FROM measurements
        WHERE campaign_id = :cid
          AND rssi_dbm IS NOT NULL
          AND location IS NOT NULL
          AND deleted_at IS NULL
        ORDER BY measured_at DESC
    """), {"cid": str(campaign_id)})).mappings().all()
    return [dict(r) for r in rows]


async def fetch_first_gateway_for_campaign(
    db: AsyncSession,
    campaign_id: uuid.UUID,
) -> dict | None:
    """Lấy gateway đầu tiên xuất hiện trong measurements của campaign."""
    row = (await db.execute(text("""
        SELECT
            ST_Y(g.location::geometry) AS lat,
            ST_X(g.location::geometry) AS lng,
            g.altitude_m,
            g.antenna_height_m
        FROM gateways g
        JOIN measurements m ON m.gateway_id = g.id
        WHERE m.campaign_id = :cid
          AND g.deleted_at IS NULL
          AND m.deleted_at IS NULL
        LIMIT 1
    """), {"cid": str(campaign_id)})).mappings().first()
    return dict(row) if row else None


async def fetch_all_gateways_for_campaign(
    db: AsyncSession,
    campaign_id: uuid.UUID,
) -> list[dict]:
    """
    Lấy tất cả gateway distinct có measurements trong campaign.
    Dùng cho multi-gateway ML inference (TS002 §6 — star-of-stars topology:
    end-device được nhiều gateway nghe → coverage = max RSSI per điểm).
    """
    rows = (await db.execute(text("""
        SELECT
            ST_Y(g.location::geometry) AS lat,
            ST_X(g.location::geometry) AS lng,
            g.altitude_m,
            g.antenna_height_m
        FROM gateways g
        WHERE g.deleted_at IS NULL
          AND EXISTS (
              SELECT 1 FROM measurements m
              WHERE m.gateway_id = g.id
                AND m.campaign_id = :cid
                AND m.deleted_at IS NULL
          )
        ORDER BY g.id
    """), {"cid": str(campaign_id)})).mappings().all()
    return [dict(r) for r in rows]