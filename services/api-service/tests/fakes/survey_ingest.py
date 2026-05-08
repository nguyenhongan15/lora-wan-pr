"""In-memory SurveyIngest fake.

Quarantine = list batches. Training = explicitly seeded TrainingPoints
(simulating "đã promote" — promote logic vẫn chưa có service riêng v2).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Literal
from uuid import UUID

from lora_coverage_api.application.repositories import (
    ContributorSpec,
    TrainingPoint,
    UserDevice,
)
from lora_coverage_api.domain.survey import SurveyBatch, SurveyBatchId


class FakeSurveyIngest:
    def __init__(
        self,
        training: Sequence[TrainingPoint] = (),
        devices: Sequence[UserDevice] = (),
    ) -> None:
        self._quarantined: list[SurveyBatch] = []
        self._training: list[TrainingPoint] = list(training)
        self._devices: list[UserDevice] = list(devices)
        # Set các (timestamp, record_id) đã thấy → mô phỏng PK conflict.
        self._seen_ids: set[tuple[object, UUID]] = set()

    def write_quarantine(self, batch: SurveyBatch) -> SurveyBatchId:
        self._quarantined.append(batch)
        return batch.batch_id

    def write_quarantine_idempotent(self, batch: SurveyBatch, record_ids: Sequence[UUID]) -> int:
        if len(record_ids) != len(batch.records):
            raise ValueError(
                f"record_ids size ({len(record_ids)}) != records ({len(batch.records)})"
            )
        inserted = 0
        for rid, rec in zip(record_ids, batch.records, strict=True):
            key = (rec.timestamp, rid)
            if key in self._seen_ids:
                continue
            self._seen_ids.add(key)
            inserted += 1
        if inserted:
            self._quarantined.append(batch)
        return inserted

    def list_quarantine(
        self, uploader_id: UUID | None = None, limit: int = 100
    ) -> Sequence[tuple[SurveyBatchId, int]]:
        items = self._quarantined
        if uploader_id is not None:
            items = [b for b in items if b.uploader_id == uploader_id]
        return [(b.batch_id, len(b.records)) for b in items[:limit]]

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
        sort_by: Literal["timestamp", "rssi", "snr"] = "timestamp",
        sort_order: Literal["asc", "desc"] = "desc",
    ) -> Sequence[TrainingPoint]:
        items = list(self._training)
        if bbox is not None:
            min_lon, min_lat, max_lon, max_lat = bbox
            items = [
                p
                for p in items
                if min_lon <= p.longitude <= max_lon and min_lat <= p.latitude <= max_lat
            ]
        if sf_list:
            items = [p for p in items if p.spreading_factor in sf_list]
        if rssi_min is not None:
            items = [p for p in items if p.rssi_dbm >= rssi_min]
        if rssi_max is not None:
            items = [p for p in items if p.rssi_dbm <= rssi_max]
        if snr_min is not None:
            items = [p for p in items if p.snr_db >= snr_min]
        if snr_max is not None:
            items = [p for p in items if p.snr_db <= snr_max]

        if sort_by == "rssi":
            items.sort(key=lambda p: p.rssi_dbm, reverse=(sort_order == "desc"))
        elif sort_by == "snr":
            items.sort(key=lambda p: p.snr_db, reverse=(sort_order == "desc"))
        # timestamp/time_from/time_to + device_id + contributor + source_type
        # không track trên TrainingPoint dataclass — accept để giữ Protocol
        # signature, để integration test (PgRepo) verify SQL thật sự apply.
        _ = device_id, contributor, source_type, time_from, time_to
        return items[offset : offset + limit]

    def list_user_devices(
        self,
        *,
        user_id: UUID,
        linked_source_id: UUID | None = None,
    ) -> Sequence[UserDevice]:
        # Fake không track device_id trên TrainingPoint; trả seed list để
        # endpoint test có thể assert response shape mà không cần DB thật.
        _ = user_id, linked_source_id
        return list(self._devices)

    # --- Test helpers (không thuộc Protocol, để tests assert/seed) ---

    @property
    def quarantined_batches(self) -> Sequence[SurveyBatch]:
        return tuple(self._quarantined)
