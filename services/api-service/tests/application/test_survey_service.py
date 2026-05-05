"""SurveyIngestService.ingest_batch — receipt mapping + side effect.

Mọi record trong batch đã pass __post_init__ (domain layer). Service chỉ:
  1. Ghi batch vào quarantine (qua repo).
  2. Trả receipt với accepted_count = số records, status = QUARANTINED.
"""

from __future__ import annotations

from lora_coverage_api.application.survey_service import SurveyIngestService
from lora_coverage_api.domain.survey import SurveyBatchStatus

from ..factories import make_survey_batch, make_survey_record
from ..fakes.survey_ingest import FakeSurveyIngest


def test_ingest_batch_writes_batch_to_quarantine_repo():
    repo = FakeSurveyIngest()
    service = SurveyIngestService(repository=repo)
    batch = make_survey_batch(n_records=3)

    service.ingest_batch(batch)

    assert len(repo.quarantined_batches) == 1
    assert repo.quarantined_batches[0].batch_id == batch.batch_id


def test_ingest_batch_returns_receipt_with_status_quarantined():
    service = SurveyIngestService(repository=FakeSurveyIngest())

    receipt = service.ingest_batch(make_survey_batch(n_records=3))

    assert receipt.status == SurveyBatchStatus.QUARANTINED


def test_ingest_batch_accepted_count_matches_record_count():
    records = [make_survey_record() for _ in range(5)]
    batch = make_survey_batch(records=records)
    service = SurveyIngestService(repository=FakeSurveyIngest())

    receipt = service.ingest_batch(batch)

    assert receipt.accepted_count == 5
    assert receipt.rejected_count == 0


def test_ingest_batch_returns_batch_id_matching_input_batch():
    batch = make_survey_batch(n_records=2)
    service = SurveyIngestService(repository=FakeSurveyIngest())

    receipt = service.ingest_batch(batch)

    assert receipt.batch_id == batch.batch_id


def test_ingest_batch_receipt_includes_review_eta_24_hours():
    service = SurveyIngestService(repository=FakeSurveyIngest())

    receipt = service.ingest_batch(make_survey_batch(n_records=1))

    assert receipt.estimated_review_hours == 24
