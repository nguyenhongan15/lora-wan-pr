"""PostGIS-backed GatewayDirectory implementation.

Read path (find_serving_candidates): <-> operator + ST_DWithin.
List/CRUD: thêm cho v2 để admin endpoint hoạt động.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Engine, text

from ..application.repositories import ContributorSpec
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
        "rx_antenna_gain_dbi",
        "rx_sensitivity_dbm",
        "noise_floor_dbm",
        "manual_state_override",
    }
)


def _opt_float(v: Any) -> float | None:
    return float(v) if v is not None else None


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
        rx_antenna_gain_dbi=_opt_float(r.get("rx_antenna_gain_dbi")),
        rx_sensitivity_dbm=_opt_float(r.get("rx_sensitivity_dbm")),
        noise_floor_dbm=_opt_float(r.get("noise_floor_dbm")),
        is_public=bool(r.get("is_public", True)),
        manual_state_override=r.get("manual_state_override"),
    )


_SELECT_COLS = """
    id, code, name,
    ST_Y(location::geometry) AS lat,
    ST_X(location::geometry) AS lon,
    altitude_m, antenna_height_m, antenna_gain_dbi,
    tx_power_dbm, frequency_mhz,
    rx_antenna_gain_dbi, rx_sensitivity_dbm,
    noise_floor_dbm, is_public, manual_state_override
"""


class PgGatewayDirectory:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # ── Read paths ────────────────────────────────────────────────────────
    def find_serving_candidates(
        self, target: Target, max_distance_km: float = 30.0, limit: int = 5
    ) -> Sequence[Gateway]:
        # Không filter theo frequency_mhz: LoRa gateway listen full AS923-2 band
        # (8 channel 923-925 MHz), `gateways.frequency_mhz` chỉ là nominal center,
        # không phải channel filter. Target.frequency_mhz vẫn dùng cho path-loss
        # tính toán xuôi sau khi đã chọn được gateway.
        sql = text(
            f"""
            SELECT {_SELECT_COLS}
            FROM geo.gateways
            WHERE is_public = true
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
        contributor: ContributorSpec | None = None,
    ) -> Sequence[Gateway]:
        clauses: list[str] = []
        params: dict[str, Any] = {"lim": limit}
        join_sql = ""
        # `g.` qualifier dùng cho mọi cột để khi JOIN ts.survey_training
        # (trùng tên cột `location`) không bị ambiguous.

        if is_public is not None:
            clauses.append("g.is_public = :is_public")
            params["is_public"] = is_public

        if bbox is not None:
            min_lon, min_lat, max_lon, max_lat = bbox
            clauses.append(
                "ST_Intersects(g.location, ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326)::geography)"
            )
            params.update(min_lon=min_lon, min_lat=min_lat, max_lon=max_lon, max_lat=max_lat)

        # Mode self/user: trả gateway "thuộc về" user đó. UNION 3 nguồn:
        #   1. ts.survey_training — gateway từng phục vụ survey đã duyệt.
        #   2. ts.survey_quarantine — gateway từng phục vụ survey còn pending.
        #   3. geo.gateway_quarantine — gateway DO user đóng góp (đã được
        #      promote vào geo.gateways) → user vẫn thấy gateway của mình
        #      kể cả khi (a) chưa có survey nào dùng nó, (b) admin đã ẩn
        #      khỏi bản đồ chung (is_public=false).
        # linked_source filter chỉ áp lên 2 nguồn survey; nguồn gateway
        # contribution không có khái niệm "linked source per gateway".
        if contributor is not None and contributor.mode in ("self", "user"):
            ls_clause = ""
            if contributor.linked_source_id is not None:
                ls_clause = "AND t.linked_source_id = :linked_source_id"
                params["linked_source_id"] = contributor.linked_source_id
            join_sql = (
                "INNER JOIN ("
                "  SELECT serving_gateway_id AS gid FROM ts.survey_training t"
                f"  WHERE t.contributor_user_id = :contributor_user_id {ls_clause}"
                "  UNION"
                "  SELECT serving_gateway_id AS gid FROM ts.survey_quarantine t"
                f"  WHERE t.contributor_user_id = :contributor_user_id {ls_clause}"
                "  UNION"
                "  SELECT gq.promoted_gateway_id AS gid"
                "  FROM geo.gateway_quarantine gq"
                "  WHERE gq.contributor_user_id = :contributor_user_id"
                "    AND gq.review_status = 'approved'"
                "    AND gq.promoted_gateway_id IS NOT NULL"
                ") t ON t.gid = g.id"
            )
            params["contributor_user_id"] = contributor.target_user_id

        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        distinct = "DISTINCT" if join_sql else ""
        select_cols = """
            g.id, g.code, g.name,
            ST_Y(g.location::geometry) AS lat,
            ST_X(g.location::geometry) AS lon,
            g.altitude_m, g.antenna_height_m, g.antenna_gain_dbi,
            g.tx_power_dbm, g.frequency_mhz,
            g.rx_antenna_gain_dbi, g.rx_sensitivity_dbm,
            g.noise_floor_dbm, g.is_public, g.manual_state_override
        """
        sql = text(
            f"""
            SELECT {distinct} {select_cols}
            FROM geo.gateways g
            {join_sql}
            {where}
            ORDER BY g.code
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

    def get_by_code(self, code: str) -> Gateway | None:
        sql = text(
            f"""
            SELECT {_SELECT_COLS}
            FROM geo.gateways
            WHERE code = :code
            """
        )
        with self._engine.connect() as conn:
            row = conn.execute(sql, {"code": code}).mappings().first()
        return _row_to_gateway(dict(row)) if row else None

    # ── Write paths ───────────────────────────────────────────────────────
    def create(self, gateway: Gateway) -> Gateway:
        sql = text(
            """
            INSERT INTO geo.gateways (
                code, name, location,
                altitude_m, antenna_height_m, antenna_gain_dbi,
                tx_power_dbm, frequency_mhz, owner_org, is_public,
                rx_antenna_gain_dbi, rx_sensitivity_dbm, noise_floor_dbm
            )
            VALUES (
                :code, :name,
                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
                :altitude_m, :antenna_height_m, :antenna_gain_dbi,
                :tx_power_dbm, :frequency_mhz, :owner_org, true,
                :rx_antenna_gain_dbi, :rx_sensitivity_dbm, :noise_floor_dbm
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
                        "rx_antenna_gain_dbi": gateway.rx_antenna_gain_dbi,
                        "rx_sensitivity_dbm": gateway.rx_sensitivity_dbm,
                        "noise_floor_dbm": gateway.noise_floor_dbm,
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
            rx_antenna_gain_dbi=gateway.rx_antenna_gain_dbi,
            rx_sensitivity_dbm=gateway.rx_sensitivity_dbm,
            noise_floor_dbm=gateway.noise_floor_dbm,
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
