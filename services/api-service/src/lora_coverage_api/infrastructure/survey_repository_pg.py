"""PostGIS-backed SurveyIngest implementation.

Insert batch vào ts.survey_quarantine bằng executemany. Mỗi record dùng
ST_SetSRID(ST_MakePoint, 4326)::geography để chuyển lat/lng → geography.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import Engine, text

from ..application.repositories import ContributorSpec, TrainingPoint, UserDevice
from ..domain.survey import SurveyBatch, SurveyBatchId

# Mapping sort_by → SQL column. Whitelist để tránh SQL injection qua
# concat (sort_by là Literal nhưng vẫn whitelist để defense-in-depth).
_SORT_COLUMN: dict[str, str] = {
    "timestamp": "t.timestamp",
    "rssi": "t.rssi_dbm",
    "snr": "t.snr_db",
}


class PgSurveyRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # SQL dùng chung cho cả 2 path; ON CONFLICT DO NOTHING vô hại với uuid4
    # (xác suất collide ~0) và là yêu cầu cứng cho idempotent path.
    # Provenance cols (plan ChirpStack webhook): NULL khi caller không cung cấp
    # (legacy /survey upload path); set khi webhook ingest đẩy WebhookContext.
    _INSERT_SQL = text(
        """
        INSERT INTO ts.survey_quarantine (
            id, timestamp, location, rssi_dbm, snr_db,
            spreading_factor, frequency_mhz, device_id,
            serving_gateway_id, uploader_id,
            external_id, source_type, contributor_user_id, linked_source_id,
            submitted_for_community, code_rate
        )
        VALUES (
            :id, :ts,
            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
            :rssi, :snr, :sf, :freq, :device_id,
            :gw_id, :uploader_id,
            :external_id, :source_type, :contributor_user_id, :linked_source_id,
            :submitted_for_community, :code_rate
        )
        ON CONFLICT (timestamp, id) DO NOTHING
        """
    )

    def _row(
        self,
        batch: SurveyBatch,
        rec_id: UUID,
        r: Any,
        *,
        external_id: str | None = None,
        source_type: str | None = None,
        linked_source_id: UUID | None = None,
        contributor_user_id: UUID | None = None,
        submitted_for_community: bool = False,
    ) -> dict[str, Any]:
        return {
            "id": rec_id,
            "ts": r.timestamp,
            "lat": r.latitude,
            "lon": r.longitude,
            "rssi": r.rssi_dbm,
            "snr": r.snr_db,
            "sf": r.spreading_factor,
            "freq": r.frequency_mhz,
            "device_id": r.device_id,
            "gw_id": r.serving_gateway_id,
            "uploader_id": batch.uploader_id,
            "external_id": external_id,
            "source_type": source_type,
            "linked_source_id": linked_source_id,
            "contributor_user_id": contributor_user_id,
            "submitted_for_community": submitted_for_community,
            "code_rate": r.code_rate,
        }

    def write_quarantine(self, batch: SurveyBatch) -> SurveyBatchId:
        if not batch.records:
            return batch.batch_id
        rows = [self._row(batch, uuid4(), r) for r in batch.records]
        with self._engine.begin() as conn:
            conn.execute(self._INSERT_SQL, rows)
        return batch.batch_id

    def write_quarantine_idempotent(
        self,
        batch: SurveyBatch,
        record_ids: Sequence[UUID],
        *,
        external_ids: Sequence[str | None] | None = None,
        source_type: str | None = None,
        linked_source_id: UUID | None = None,
        contributor_user_id: UUID | None = None,
        submitted_for_community: bool = False,
    ) -> int:
        if len(record_ids) != len(batch.records):
            raise ValueError(
                f"record_ids size ({len(record_ids)}) != records ({len(batch.records)})"
            )
        if external_ids is not None and len(external_ids) != len(batch.records):
            raise ValueError(
                f"external_ids size ({len(external_ids)}) != records ({len(batch.records)})"
            )
        if not batch.records:
            return 0
        ext_iter: Sequence[str | None] = (
            external_ids if external_ids is not None else [None] * len(batch.records)
        )
        rows = [
            self._row(
                batch,
                rid,
                r,
                external_id=ext,
                source_type=source_type,
                linked_source_id=linked_source_id,
                contributor_user_id=contributor_user_id,
                submitted_for_community=submitted_for_community,
            )
            for rid, r, ext in zip(record_ids, batch.records, ext_iter, strict=True)
        ]
        with self._engine.begin() as conn:
            result = conn.execute(self._INSERT_SQL, rows)
        # executemany với ON CONFLICT DO NOTHING: rowcount = số row thực sự
        # insert (psycopg trả tổng row affected qua statuses).
        rc = result.rowcount
        return rc if rc is not None and rc >= 0 else 0

    def list_quarantine(
        self, uploader_id: UUID | None = None, limit: int = 100
    ) -> Sequence[tuple[SurveyBatchId, int]]:
        # Note: v2 ko track batch_id trong DB (mỗi record là 1 row độc lập).
        # Khi cần track theo batch, thêm column batch_id vào table.
        # Tạm trả empty cho v2 — endpoint admin chưa expose.
        _ = uploader_id, limit
        return []

    def list_training(
        self,
        *,
        contributor: ContributorSpec,
        bbox: tuple[float, float, float, float] | None = None,
        offset: int = 0,
        limit: int = 1000,
        device_id: str | None = None,
        source_type: str | None = None,
        sf_list: Sequence[int] | None = None,
        rssi_min: float | None = None,
        rssi_max: float | None = None,
        snr_min: float | None = None,
        snr_max: float | None = None,
        time_from: datetime | None = None,
        time_to: datetime | None = None,
        since: datetime | None = None,
        sort_by: Literal["timestamp", "rssi", "snr"] = "timestamp",
        sort_order: Literal["asc", "desc"] = "desc",
    ) -> Sequence[TrainingPoint]:
        # Build WHERE clauses động — tránh string concat thô để giữ tham số hoá.
        # JOIN auth.linked_sources + auth.users CHỈ cho mode=community (cần
        # filter contribute + disabled). Mode self/user bypass — defense in
        # depth không cần thiết vì target_user_id đã do edge ép buộc.
        #
        # Mode self|user: UNION ts.survey_training (đã đóng góp) với
        # ts.survey_quarantine (CSV cá nhân + community-pending + rejected).
        # User upload CSV chưa nhấn "Đóng góp cộng đồng" thì row chỉ ở
        # quarantine — filter "Của tôi" cần thấy nên cả 2 bảng đều phải query.
        where: list[str] = []
        params: dict[str, object] = {"limit": limit, "offset": offset}

        if bbox is not None:
            where.append(
                "ST_Intersects(t.location::geometry, "
                "ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326))"
            )
            params.update(min_lon=bbox[0], min_lat=bbox[1], max_lon=bbox[2], max_lat=bbox[3])
        if device_id is not None:
            where.append("t.device_id = :device_id")
            params["device_id"] = device_id
        if source_type is not None:
            where.append("t.source_type = :source_type")
            params["source_type"] = source_type
        if sf_list:
            where.append("t.spreading_factor = ANY(:sf_list)")
            params["sf_list"] = list(sf_list)
        if rssi_min is not None:
            where.append("t.rssi_dbm >= :rssi_min")
            params["rssi_min"] = rssi_min
        if rssi_max is not None:
            where.append("t.rssi_dbm <= :rssi_max")
            params["rssi_max"] = rssi_max
        if snr_min is not None:
            where.append("t.snr_db >= :snr_min")
            params["snr_min"] = snr_min
        if snr_max is not None:
            where.append("t.snr_db <= :snr_max")
            params["snr_max"] = snr_max
        if time_from is not None:
            where.append("t.timestamp >= :time_from")
            params["time_from"] = time_from
        if time_to is not None:
            where.append("t.timestamp <= :time_to")
            params["time_to"] = time_to
        if since is not None:
            # Strict `>` để cursor không lặp lại row đã trả; caller advance
            # cursor = max(timestamp) sau mỗi lần fetch.
            where.append("t.timestamp > :since")
            params["since"] = since

        sort_column = _SORT_COLUMN[sort_by]
        sort_dir = "ASC" if sort_order == "asc" else "DESC"

        if contributor.mode == "community":
            where.append("ls.contribute_to_community = true")
            where.append("ls.status = 'active'")
            where.append("u.disabled = false")
            where_sql = "WHERE " + " AND ".join(where)
            # Tie-breaker: timestamp DESC để khi rssi/snr trùng giá trị, OFFSET
            # vẫn deterministic giữa các page.
            order_sql = (
                f"ORDER BY {sort_column} {sort_dir}, t.timestamp DESC"
                if sort_by != "timestamp"
                else f"ORDER BY {sort_column} {sort_dir}"
            )
            sql = text(
                f"""
                SELECT
                    ST_Y(t.location::geometry) AS lat,
                    ST_X(t.location::geometry) AS lon,
                    t.rssi_dbm, t.snr_db, t.spreading_factor, t.serving_gateway_id,
                    t.device_id, t.frequency_mhz, t.timestamp, t.code_rate
                FROM ts.survey_training t
                JOIN auth.linked_sources ls ON ls.id = t.linked_source_id
                JOIN auth.users u ON u.id = t.contributor_user_id
                {where_sql}
                {order_sql}
                LIMIT :limit OFFSET :offset
                """
            )
        else:  # self | user
            where.insert(0, "t.contributor_user_id = :contributor_user_id")
            params["contributor_user_id"] = contributor.target_user_id
            if contributor.linked_source_id is not None:
                where.append("t.linked_source_id = :linked_source_id")
                params["linked_source_id"] = contributor.linked_source_id
            where_sql = "WHERE " + " AND ".join(where)
            # Sort columns reference inner alias `t`; outer subquery aliases
            # cùng tên column (timestamp/rssi_dbm/snr_db) — đổi prefix `t.` →
            # `u.` để áp dụng trên unioned result.
            outer_sort_column = sort_column.replace("t.", "u.")
            outer_order_sql = (
                f"ORDER BY {outer_sort_column} {sort_dir}, u.timestamp DESC"
                if sort_by != "timestamp"
                else f"ORDER BY {outer_sort_column} {sort_dir}"
            )
            inner_select = (
                "SELECT "
                "ST_Y(t.location::geometry) AS lat, "
                "ST_X(t.location::geometry) AS lon, "
                "t.rssi_dbm, t.snr_db, t.spreading_factor, t.serving_gateway_id, "
                "t.device_id, t.frequency_mhz, t.timestamp, t.code_rate"
            )
            # Dedup quarantine vs training trên key (timestamp, source_type,
            # external_id) — promotion KHÔNG xoá quarantine row sau khi copy
            # sang training (giữ để re-promote / audit). Nếu UNION ALL thuần,
            # row promoted bị count 2 lần.
            #
            # Match thêm contributor_user_id: cùng external_id có thể ở
            # training dưới contributor khác (conflict winner trong ON
            # CONFLICT DO NOTHING). User hiện tại có quarantine copy chưa lên
            # training của họ → vẫn phải hiện. Tất cả source hiện hành đều
            # có external_id NOT NULL → key valid.
            sql = text(
                f"""
                SELECT lat, lon, rssi_dbm, snr_db, spreading_factor, serving_gateway_id,
                       device_id, frequency_mhz, timestamp, code_rate
                FROM (
                    {inner_select}
                    FROM ts.survey_training t
                    {where_sql}
                    UNION ALL
                    {inner_select}
                    FROM ts.survey_quarantine t
                    {where_sql}
                      AND NOT EXISTS (
                        SELECT 1 FROM ts.survey_training tr
                        WHERE tr.timestamp = t.timestamp
                          AND tr.source_type = t.source_type
                          AND tr.external_id = t.external_id
                          AND tr.contributor_user_id = t.contributor_user_id
                      )
                ) u
                {outer_order_sql}
                LIMIT :limit OFFSET :offset
                """
            )

        with self._engine.connect() as conn:
            rows = conn.execute(sql, params).mappings().all()

        return [
            TrainingPoint(
                latitude=float(r["lat"]),
                longitude=float(r["lon"]),
                rssi_dbm=float(r["rssi_dbm"]),
                snr_db=float(r["snr_db"]),
                spreading_factor=int(r["spreading_factor"]),
                serving_gateway_id=r["serving_gateway_id"],
                device_id=r["device_id"],
                frequency_mhz=float(r["frequency_mhz"]),
                timestamp=r["timestamp"],
                code_rate=r["code_rate"],
            )
            for r in rows
        ]

    def lookup_gateway_coords(
        self,
        *,
        source_type: str,
        external_ids: Sequence[str],
    ) -> dict[str, tuple[float, float]]:
        if not external_ids:
            return {}
        sql = text(
            """
            SELECT external_id,
                   ST_Y(location::geometry) AS lat,
                   ST_X(location::geometry) AS lon
            FROM geo.gateways
            WHERE source_type = :source_type
              AND external_id = ANY(:external_ids)
            """
        )
        with self._engine.connect() as conn:
            rows = (
                conn.execute(
                    sql,
                    {"source_type": source_type, "external_ids": list(external_ids)},
                )
                .mappings()
                .all()
            )
        return {r["external_id"]: (float(r["lat"]), float(r["lon"])) for r in rows}

    def list_user_devices(
        self,
        *,
        user_id: UUID,
        linked_source_id: UUID | None = None,
    ) -> Sequence[UserDevice]:
        # contributor_user_id = :user_id đã giới hạn data của user → an toàn
        # khi pass linked_source_id thẳng vào WHERE; nếu user truyền source
        # của người khác, intersection rỗng → không leak.
        #
        # UNION training + quarantine: dropdown filter phải parity với map
        # mode='me' (list_training cũng UNION 2 bảng). Device CSV chưa "Đóng
        # góp cộng đồng" hoặc pending_review chỉ ở quarantine — không union
        # thì dropdown thiếu so với map.
        params: dict[str, Any] = {"user_id": user_id}
        ls_clause = ""
        if linked_source_id is not None:
            ls_clause = "AND t.linked_source_id = :linked_source_id"
            params["linked_source_id"] = linked_source_id

        sql = text(
            f"""
            SELECT device_id, SUM(cnt)::bigint AS cnt
            FROM (
                SELECT t.device_id, COUNT(*) AS cnt
                FROM ts.survey_training t
                WHERE t.contributor_user_id = :user_id
                  AND t.device_id IS NOT NULL
                  {ls_clause}
                GROUP BY t.device_id
                UNION ALL
                SELECT t.device_id, COUNT(*) AS cnt
                FROM ts.survey_quarantine t
                WHERE t.contributor_user_id = :user_id
                  AND t.device_id IS NOT NULL
                  {ls_clause}
                  AND NOT EXISTS (
                    SELECT 1 FROM ts.survey_training tr
                    WHERE tr.timestamp = t.timestamp
                      AND tr.source_type = t.source_type
                      AND tr.external_id = t.external_id
                      AND tr.contributor_user_id = t.contributor_user_id
                  )
                GROUP BY t.device_id
            ) u
            GROUP BY device_id
            ORDER BY cnt DESC, device_id ASC
            LIMIT 200
            """
        )
        with self._engine.connect() as conn:
            rows = conn.execute(sql, params).mappings().all()
        return [UserDevice(device_id=r["device_id"], count=int(r["cnt"])) for r in rows]
