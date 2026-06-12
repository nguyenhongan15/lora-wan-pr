"""TrustValidator pipeline cho community contribution.

Plan community-data-contribution: measurement pass 2 lớp (L1 hard gate +
L2 ITU physics 15 dB) mới vào hàng đợi admin duyệt thủ công.

Public API: TrustValidator, ValidationResult, ContributorContext.
"""

from __future__ import annotations

from .promotion import (
    PromotionResult,
    mark_submitted_for_linked_source,
    promote_pending_for_linked_source,
)
from .validator import (
    ContributorContext,
    TrustValidator,
    UnknownContributorError,
    ValidationResult,
)

__all__ = [
    "ContributorContext",
    "PromotionResult",
    "TrustValidator",
    "UnknownContributorError",
    "ValidationResult",
    "mark_submitted_for_linked_source",
    "promote_pending_for_linked_source",
]
