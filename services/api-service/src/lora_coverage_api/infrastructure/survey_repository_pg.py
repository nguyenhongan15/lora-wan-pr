"""PostGIS-backed SurveyIngest implementation.

Insert batch vào ts.survey_quarantine bằng executemany. Mỗi record dùng
ST_SetSRID(ST_MakePoint, 4326)::geography để chuyển lat/lng → geography.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID, uuid4

from sqlalchemy import Engine, text

from ..application.repositories import TrainingPoint
from ..domain.survey import SurveyBatch, SurveyBatchId


class PgSurveyRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def write_quarantine(self, batch: SurveyBatch) -> SurveyBatchId:
        if not batch.records:
            return batch.batch_id

        sql = text(
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
            """
        )

        rows = [
            {
                "id": uuid4(),
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
            for r in batch.records
        ]

        with self._engine.begin() as conn:
            conn.execute(sql, rows)

        return batch.batch_id

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
        bbox: tuple[float, float, float, float] | None = None,
        limit: int = 1000,
    ) -> Sequence[TrainingPoint]:
        if bbox is not None:
            sql = text(
                """
                SELECT
                    ST_Y(location::geometry) AS lat,
                    ST_X(location::geometry) AS lon,
                    rssi_dbm, snr_db, spreading_factor, serving_gateway_id
                FROM ts.survey_training
                WHERE ST_Intersects(
                    location::geometry,
                    ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326)
                )
                ORDER BY timestamp DESC
                LIMIT :limit
                """
            )
            params = {
                "min_lon": bbox[0],
                "min_lat": bbox[1],
                "max_lon": bbox[2],
                "max_lat": bbox[3],
                "limit": limit,
            }
        else:
            sql = text(
                """
                SELECT
                    ST_Y(location::geometry) AS lat,
                    ST_X(location::geometry) AS lon,
                    rssi_dbm, snr_db, spreading_factor, serving_gateway_id
                FROM ts.survey_training
                ORDER BY timestamp DESC
                LIMIT :limit
                """
            )
            params = {"limit": limit}

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
