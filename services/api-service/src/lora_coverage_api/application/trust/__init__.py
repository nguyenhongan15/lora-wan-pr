"""TrustValidator pipeline cho community contribution.

Plan community-data-contribution: chỉ measurement pass cả 3 lớp (hard gate /
ITU physics / reputation-threshold) mới được promote sang ts.survey_training.

Public API: TrustValidator, ValidationResult, ContributorContext.
"""

from __future__ import annotations

from .promotion import (
    CsvBatchSummary,
    CsvUploaderStats,
    PromotionResult,
    delete_csv_batch_for_uploader,
    fetch_csv_stats_for_uploader,
    list_csv_batches_for_uploader,
    mark_and_promote_csv_for_uploader,
    mark_submitted_for_linked_source,
    promote_pending_for_linked_source,
    promote_pending_for_uploader,
)
from .validator import (
    ContributorContext,
    TrustValidator,
    UnknownContributorError,
    ValidationResult,
)

__all__ = [
    "ContributorContext",
    "CsvBatchSummary",
    "CsvUploaderStats",
    "PromotionResult",
    "TrustValidator",
    "UnknownContributorError",
    "ValidationResult",
    "delete_csv_batch_for_uploader",
    "fetch_csv_stats_for_uploader",
    "list_csv_batches_for_uploader",
    "mark_and_promote_csv_for_uploader",
    "mark_submitted_for_linked_source",
    "promote_pending_for_linked_source",
    "promote_pending_for_uploader",
]
