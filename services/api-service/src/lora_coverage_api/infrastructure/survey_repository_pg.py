"""PostGIS-backed SurveyIngest implementation.

Insert batch vào ts.survey_quarantine bằng executemany. Mỗi record dùng
ST_SetSRID(ST_MakePoint, 4326)::geography để chuyển lat/lng → geography.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Engine, text

from ..application.repositories import ContributorSpec, TrainingPoint
from ..domain.survey import SurveyBatch, SurveyBatchId


class PgSurveyRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # SQL dùng chung cho cả 2 path; ON CONFLICT DO NOTHING vô hại với uuid4
    # (xác suất collide ~0) và là yêu cầu cứng cho idempotent path.
    _INSERT_SQL = text(
        """
        INSERT INTO ts.survey_quarantine (
            id, timestamp, location, rssi_dbm, snr_db,
            spreading_factor, frequency_mhz, device_id,
            serving_gateway_id, uploader_id
        )
        VALUES (
            :id, :ts,
            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
            :rssi, :snr, :sf, :freq, :device_id,
            :gw_id, :uploader_id
        )
        ON CONFLICT (timestamp, id) DO NOTHING
        """
    )

    def _row(self, batch: SurveyBatch, rec_id: UUID, r: Any) -> dict[str, Any]:
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
        }

    def write_quarantine(self, batch: SurveyBatch) -> SurveyBatchId:
        if not batch.records:
            return batch.batch_id
        rows = [self._row(batch, uuid4(), r) for r in batch.records]
        with self._engine.begin() as conn:
            conn.execute(self._INSERT_SQL, rows)
        return batch.batch_id

    def write_quarantine_idempotent(self, batch: SurveyBatch, record_ids: Sequence[UUID]) -> int:
        if len(record_ids) != len(batch.records):
            raise ValueError(
                f"record_ids size ({len(record_ids)}) != records ({len(batch.records)})"
            )
        if not batch.records:
            return 0
        rows = [self._row(batch, rid, r) for rid, r in zip(record_ids, batch.records, strict=True)]
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
        limit: int = 1000,
        device_id: str | None = None,
        source_type: str | None = None,
    ) -> Sequence[TrainingPoint]:
        # Build WHERE clauses động — tránh string concat thô để giữ tham số hoá.
        # JOIN auth.linked_sources + auth.users CHỈ cho mode=community (cần
        # filter contribute + disabled). Mode self/user bypass — defense in
        # depth không cần thiết vì target_user_id đã do edge ép buộc.
        where: list[str] = []
        params: dict[str, object] = {"limit": limit}
        join_sql = ""

        if contributor.mode == "community":
            join_sql = (
                "JOIN auth.linked_sources ls ON ls.id = t.linked_source_id "
                "JOIN auth.users u ON u.id = t.contributor_user_id"
            )
            where.append("ls.contribute_to_community = true")
            where.append("ls.status = 'active'")
            where.append("u.disabled = false")
        else:  # self | user
            where.append("t.contributor_user_id = :contributor_user_id")
            params["contributor_user_id"] = contributor.target_user_id
            if contributor.linked_source_id is not None:
                where.append("t.linked_source_id = :linked_source_id")
                params["linked_source_id"] = contributor.linked_source_id

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

        where_sql = "WHERE " + " AND ".join(where)
        sql = text(
            f"""
            SELECT
                ST_Y(t.location::geometry) AS lat,
                ST_X(t.location::geometry) AS lon,
                t.rssi_dbm, t.snr_db, t.spreading_factor, t.serving_gateway_id
            FROM ts.survey_training t
            {join_sql}
            {where_sql}
            ORDER BY t.timestamp DESC
            LIMIT :limit
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
            )
            for r in rows
        ]
