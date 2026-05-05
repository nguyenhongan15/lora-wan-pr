"""In-memory SurveyIngest fake.

Quarantine = list batches. Training = explicitly seeded TrainingPoints
(simulating "đã promote" — promote logic vẫn chưa có service riêng v2).
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from lora_coverage_api.application.repositories import TrainingPoint
from lora_coverage_api.domain.survey import SurveyBatch, SurveyBatchId


class FakeSurveyIngest:
    def __init__(self, training: Sequence[TrainingPoint] = ()) -> None:
        self._quarantined: list[SurveyBatch] = []
        self._training: list[TrainingPoint] = list(training)

    def write_quarantine(self, batch: SurveyBatch) -> SurveyBatchId:
        self._quarantined.append(batch)
        return batch.batch_id

    def list_quarantine(
        self, uploader_id: UUID | None = None, limit: int = 100
    ) -> Sequence[tuple[SurveyBatchId, int]]:
        items = self._quarantined
        if uploader_id is not None:
            items = [b for b in items if b.uploader_id == uploader_id]
        return [(b.batch_id, len(b.records)) for b in items[:limit]]

    def list_training(
        self,
        bbox: tuple[float, float, float, float] | None = None,
        limit: int = 1000,
    ) -> Sequence[TrainingPoint]:
        items = self._training
        if bbox is not None:
            min_lon, min_lat, max_lon, max_lat = bbox
            items = [
                p
                for p in items
                if min_lon <= p.longitude <= max_lon
                and min_lat <= p.latitude <= max_lat
            ]
        return items[:limit]

    # --- Test helpers (không thuộc Protocol, để tests assert/seed) ---

    @property
    def quarantined_batches(self) -> Sequence[SurveyBatch]:
        return tuple(self._quarantined)
