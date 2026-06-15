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
        gateway_coords: dict[tuple[str, str], tuple[float, float]] | None = None,
    ) -> None:
        self._quarantined: list[SurveyBatch] = []
        self._training: list[TrainingPoint] = list(training)
        self._devices: list[UserDevice] = list(devices)
        # Map (source_type, external_id) → (lat, lon) cho lookup_gateway_coords.
        self._gateway_coords: dict[tuple[str, str], tuple[float, float]] = dict(
            gateway_coords or {}
        )
        # Set các (timestamp, record_id) đã thấy → mô phỏng PK conflict.
        self._seen_ids: set[tuple[object, UUID]] = set()

    def write_quarantine(self, batch: SurveyBatch) -> SurveyBatchId:
        self._quarantined.append(batch)
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
        _ = (
            external_ids,
            source_type,
            linked_source_id,
            contributor_user_id,
            submitted_for_community,
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

    def lookup_gateway_coords(
        self,
        *,
        source_type: str,
        external_ids: Sequence[str],
    ) -> dict[str, tuple[float, float]]:
        return {
            ext: self._gateway_coords[(source_type, ext)]
            for ext in external_ids
            if (source_type, ext) in self._gateway_coords
        }

    def lookup_gateway_for_uplink(
        self,
        *,
        preferred_source_type: str,
        external_ids: Sequence[str],
    ) -> dict[str, tuple[UUID, float, float]]:
        # Fake: prefer match on preferred_source_type, fallback bất kỳ
        # source_type khác cho cùng external_id. UUID giả lập bằng uuid5
        # determined từ external_id để test verify ổn định.
        from uuid import NAMESPACE_OID, uuid5

        out: dict[str, tuple[UUID, float, float]] = {}
        for ext in external_ids:
            if (preferred_source_type, ext) in self._gateway_coords:
                lat, lon = self._gateway_coords[(preferred_source_type, ext)]
                out[ext] = (uuid5(NAMESPACE_OID, f"{preferred_source_type}:{ext}"), lat, lon)
                continue
            for (src, key), (lat, lon) in self._gateway_coords.items():
                if key == ext:
                    out[ext] = (uuid5(NAMESPACE_OID, f"{src}:{ext}"), lat, lon)
                    break
        return out

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
