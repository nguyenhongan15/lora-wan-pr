"""PostGIS-backed GatewayDirectory implementation.

Read path (find_serving_candidates): <-> operator + ST_DWithin.
List/CRUD: thêm cho v2 để admin endpoint hoạt động.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Engine, text

from ..domain.coverage import Gateway, GatewayId, Target

# Subset cột được phép update (whitelist — KHÔNG cho update id/code).
_UPDATABLE_COLUMNS = frozenset(
    {
        "name",
        "altitude_m",
        "antenna_height_m",
        "antenna_gain_dbi",
        "tx_power_dbm",
        "frequency_mhz",
        "owner_org",
        "is_public",
    }
)


def _row_to_gateway(r: dict[str, Any]) -> Gateway:
    return Gateway(
        id=GatewayId(r["id"]),
        code=r["code"],
        name=r["name"],
        latitude=float(r["lat"]),
        longitude=float(r["lon"]),
        altitude_m=float(r["altitude_m"]),
        antenna_height_m=float(r["antenna_height_m"]),
        antenna_gain_dbi=float(r["antenna_gain_dbi"]),
        tx_power_dbm=float(r["tx_power_dbm"]),
        frequency_mhz=float(r["frequency_mhz"]),
    )


_SELECT_COLS = """
    id, code, name,
    ST_Y(location::geometry) AS lat,
    ST_X(location::geometry) AS lon,
    altitude_m, antenna_height_m, antenna_gain_dbi,
    tx_power_dbm, frequency_mhz
"""


class PgGatewayDirectory:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # ── Read paths ────────────────────────────────────────────────────────
    def find_serving_candidates(
        self, target: Target, max_distance_km: float = 30.0, limit: int = 5
    ) -> Sequence[Gateway]:
        sql = text(
            f"""
            SELECT {_SELECT_COLS}
            FROM geo.gateways
            WHERE is_public = true
              AND frequency_mhz = :freq
              AND ST_DWithin(
                    location,
                    ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
                    :radius_m
                  )
            ORDER BY location <-> ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography
            LIMIT :lim
            """
        )
        with self._engine.connect() as conn:
            rows = (
                conn.execute(
                    sql,
                    {
                        "lat": target.latitude,
                        "lon": target.longitude,
                        "freq": target.frequency_mhz,
                        "radius_m": max_distance_km * 1000.0,
                        "lim": limit,
                    },
                )
                .mappings()
                .all()
            )
        return [_row_to_gateway(dict(r)) for r in rows]

    def list_gateways(
        self,
        bbox: tuple[float, float, float, float] | None = None,
        is_public: bool | None = True,
        limit: int = 500,
    ) -> Sequence[Gateway]:
        clauses: list[str] = []
        params: dict[str, Any] = {"lim": limit}

        if is_public is not None:
            clauses.append("is_public = :is_public")
            params["is_public"] = is_public

        if bbox is not None:
            min_lon, min_lat, max_lon, max_lat = bbox
            clauses.append(
                "ST_Intersects(location, ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326)::geography)"
            )
            params.update(min_lon=min_lon, min_lat=min_lat, max_lon=max_lon, max_lat=max_lat)

        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        sql = text(
            f"""
            SELECT {_SELECT_COLS}
            FROM geo.gateways
            {where}
            ORDER BY code
            LIMIT :lim
            """
        )
        with self._engine.connect() as conn:
            rows = conn.execute(sql, params).mappings().all()
        return [_row_to_gateway(dict(r)) for r in rows]

    def get_by_id(self, gateway_id: GatewayId) -> Gateway | None:
        sql = text(
            f"""
            SELECT {_SELECT_COLS}
            FROM geo.gateways
            WHERE id = :id
            """
        )
        with self._engine.connect() as conn:
            row = conn.execute(sql, {"id": gateway_id}).mappings().first()
        return _row_to_gateway(dict(row)) if row else None

    # ── Write paths ───────────────────────────────────────────────────────
    def create(self, gateway: Gateway) -> Gateway:
        sql = text(
            """
            INSERT INTO geo.gateways (
                code, name, location,
                altitude_m, antenna_height_m, antenna_gain_dbi,
                tx_power_dbm, frequency_mhz, owner_org, is_public
            )
            VALUES (
                :code, :name,
                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
                :altitude_m, :antenna_height_m, :antenna_gain_dbi,
                :tx_power_dbm, :frequency_mhz, :owner_org, true
            )
            RETURNING id
            """
        )
        with self._engine.begin() as conn:
            row = (
                conn.execute(
                    sql,
                    {
                        "code": gateway.code,
                        "name": gateway.name,
                        "lat": gateway.latitude,
                        "lon": gateway.longitude,
                        "altitude_m": gateway.altitude_m,
                        "antenna_height_m": gateway.antenna_height_m,
                        "antenna_gain_dbi": gateway.antenna_gain_dbi,
                        "tx_power_dbm": gateway.tx_power_dbm,
                        "frequency_mhz": gateway.frequency_mhz,
                        "owner_org": None,
                    },
                )
                .mappings()
                .first()
            )
        if row is None:
            raise RuntimeError("INSERT RETURNING did not return id")
        return Gateway(
            id=GatewayId(row["id"]),
            code=gateway.code,
            name=gateway.name,
            latitude=gateway.latitude,
            longitude=gateway.longitude,
            altitude_m=gateway.altitude_m,
            antenna_height_m=gateway.antenna_height_m,
            antenna_gain_dbi=gateway.antenna_gain_dbi,
            tx_power_dbm=gateway.tx_power_dbm,
            frequency_mhz=gateway.frequency_mhz,
        )

    def update(self, gateway_id: GatewayId, patch: dict[str, object]) -> Gateway | None:
        # Whitelist: chỉ cho update các cột an toàn.
        clean = {k: v for k, v in patch.items() if k in _UPDATABLE_COLUMNS}
        if not clean:
            return self.get_by_id(gateway_id)

        # Build SET clause an toàn (key đã whitelist, không SQL injection).
        set_clause = ", ".join(f"{k} = :{k}" for k in clean)
        sql = text(
            f"""
            UPDATE geo.gateways
            SET {set_clause}
            WHERE id = :id
            RETURNING {_SELECT_COLS}
            """
        )
        params: dict[str, Any] = dict(clean)
        params["id"] = gateway_id

        with self._engine.begin() as conn:
            row = conn.execute(sql, params).mappings().first()
        return _row_to_gateway(dict(row)) if row else None
