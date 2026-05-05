"""SurveyIngestService — application use case.

Theo system-architecture.md §4.2:
  1. Schema validation đã được Pydantic + SurveyRecord __post_init__ enforce.
  2. Geographic plausibility (not-in-water) — DEFER (cần raster, làm ở
     worker khi có).
  3. Write vào ts.survey_quarantine.
  4. Trả 202 Accepted với batch_id.

v2 KHÔNG có Celery worker → batch ở quarantine cho đến khi có job promote.
"""

from __future__ import annotations

from .repositories import SurveyIngest
from ..domain.survey import (
    SurveyBatch,
    SurveyBatchReceipt,
    SurveyBatchStatus,
)


class SurveyIngestService:
    def __init__(self, repository: SurveyIngest) -> None:
        self._repo = repository

    def ingest_batch(self, batch: SurveyBatch) -> SurveyBatchReceipt:
        """Ghi batch vào quarantine. Tất cả record đã pass validation ở
        domain layer (SurveyRecord.__post_init__).
        """
        batch_id = self._repo.write_quarantine(batch)
        return SurveyBatchReceipt(
            batch_id=batch_id,
            status=SurveyBatchStatus.QUARANTINED,
            accepted_count=len(batch.records),
            rejected_count=0,
            estimated_review_hours=24,
        )
