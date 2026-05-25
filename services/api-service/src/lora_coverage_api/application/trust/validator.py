"""TrustValidator — 2-layer pipeline cho community measurement contribution.

Plan community-data-contribution. Mỗi measurement đánh dấu
`submitted_for_community=true` (CSV upload checkbox / linked_source opt-in)
phải pass cả 2 lớp dưới mới được vào hàng đợi admin duyệt thủ công:

  L1 hard gates:
    - lat/lng ∈ VIETNAM_BBOX (Scope Vietnam only)
    - serving_gateway_id resolve về geo.gateways row hiện hữu
    (RSSI/SNR/SF/lat-lng bounds đã enforce ở SurveyRecord.__post_init__ →
    không bao giờ tới validator; deduplicate qua DB unique index trên
    (timestamp, source_type, external_id).)

  L2 ITU physics plausibility:
    - so |observed_rssi - Stage1ItuModel.predict(target, gateway)| với
      threshold cố định PHYSICS_THRESHOLD_DB.
    - Reject reason "physics_outlier" nếu vượt threshold.

Threshold cố định 15 dB ~ 2σ Stage1 shadow-fading. Admin manual gate
(migration 0018) là lớp cuối — auto-validate chỉ chặn rác hiển nhiên;
admin xét sắc thái mọi row còn lại.

Deep module (Ousterhout Ch4): interface 1 method `validate(record, contributor)`
+ 1 method `update_stats(user_id, passed)`. Hidden: gateway lookup, ITU
prediction, JSONB atomic increment.

Caller (CSV upload endpoint / survey_repository hook) wrap transaction; validator
nhận Connection per-call và KHÔNG raise (trừ unknown user). Failure mode mọi
trả về qua ValidationResult.passed=False + reject_reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import structlog
from sqlalchemy import Connection, text

from ...domain.coverage import GatewayId, Target
from ...domain.survey import SurveyRecord, is_in_vietnam
from ..itu.model import Stage1ItuModel
from ..repositories import GatewayDirectory

logger = structlog.get_logger("lora_coverage_api.trust")


# Threshold cố định: ~2σ Stage1 shadow-fading (σ ~ 6-8 dB → 2σ ~ 16 dB).
# Admin manual gate là lớp cuối, nên L2 chỉ cần chặn rác hiển nhiên.
PHYSICS_THRESHOLD_DB = 15.0


@dataclass(frozen=True, slots=True)
class ContributorContext:
    """Wrapper user_id để callers pass identity vào pipeline.

    Trước đây giữ snapshot reputation cho L3 — nay L3 đã bỏ, chỉ còn user_id
    để `update_stats` bump counter sau khi validate.
    """

    user_id: UUID


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Output của TrustValidator.validate.

    `passed=True` → caller copy record sang ts.survey_training.
    `passed=False` → caller ghi reject_reason vào quarantine row + KHÔNG promote.

    Debugging fields (`predicted_rssi_dbm`, `delta_db`, `threshold_db`)
    phục vụ log/admin UI; tất cả None khi reject sớm ở L1.
    """

    passed: bool
    reject_reason: str | None
    layer: str  # "L1_bbox" | "L1_gateway" | "L2_physics" | "passed"
    predicted_rssi_dbm: float | None = None
    delta_db: float | None = None
    threshold_db: float | None = None


# ── SQL ──────────────────────────────────────────────────────────────────────

_SELECT_CONTRIBUTOR = text(
    """
    SELECT id
    FROM auth.users
    WHERE id = :user_id
    """
)

# jsonb_set với create_if_missing=true: nếu key chưa tồn tại (user cũ chưa
# có default JSON populate đầy đủ) thì tạo mới. Cast về text rồi int để cộng
# tránh edge case JSON khác type.
_UPDATE_STATS_ACCEPTED = text(
    """
    UPDATE auth.users
    SET contribution_stats = jsonb_set(
        jsonb_set(
            contribution_stats,
            '{accepted}',
            to_jsonb(COALESCE((contribution_stats->>'accepted')::int, 0) + 1),
            true
        ),
        '{last_at}',
        to_jsonb(cast(:now AS text)),
        true
    )
    WHERE id = :user_id
    """
)

_UPDATE_STATS_REJECTED = text(
    """
    UPDATE auth.users
    SET contribution_stats = jsonb_set(
        jsonb_set(
            contribution_stats,
            '{rejected}',
            to_jsonb(COALESCE((contribution_stats->>'rejected')::int, 0) + 1),
            true
        ),
        '{last_at}',
        to_jsonb(cast(:now AS text)),
        true
    )
    WHERE id = :user_id
    """
)


class UnknownContributorError(Exception):
    """user_id không có trong auth.users — caller phải verify trước."""


class TrustValidator:
    """Stateless modulo (model, directory). Caller (edge/deps) inject 1
    instance per-process; per-call nhận Connection để load/update DB."""

    def __init__(
        self,
        *,
        model: Stage1ItuModel,
        directory: GatewayDirectory,
    ) -> None:
        self._model = model
        self._directory = directory

    # ── public ────────────────────────────────────────────────────────────

    def load_contributor(self, conn: Connection, user_id: UUID) -> ContributorContext:
        """Verify user tồn tại + trả wrapper user_id.

        Raises:
            UnknownContributorError: user_id không tồn tại.
        """
        row = conn.execute(_SELECT_CONTRIBUTOR, {"user_id": user_id}).one_or_none()
        if row is None:
            raise UnknownContributorError(f"user_id {user_id} không tồn tại")
        return ContributorContext(user_id=row.id)

    def validate(
        self,
        record: SurveyRecord,
        contributor: ContributorContext,
    ) -> ValidationResult:
        """Run 2-layer pipeline. KHÔNG raise — failure → ValidationResult."""
        # ── L1: VIETNAM bbox ──────────────────────────────────────────────
        if not is_in_vietnam(record.latitude, record.longitude):
            return ValidationResult(
                passed=False,
                reject_reason="out_of_region",
                layer="L1_bbox",
            )

        # ── L1: known gateway ────────────────────────────────────────────
        if record.serving_gateway_id is None:
            return ValidationResult(
                passed=False,
                reject_reason="unknown_gateway",
                layer="L1_gateway",
            )
        gateway = self._directory.get_by_id(GatewayId(record.serving_gateway_id))
        if gateway is None:
            return ValidationResult(
                passed=False,
                reject_reason="unknown_gateway",
                layer="L1_gateway",
            )

        # ── L2: ITU physics plausibility ─────────────────────────────────
        target = Target(
            latitude=record.latitude,
            longitude=record.longitude,
            spreading_factor=record.spreading_factor,
            frequency_mhz=record.frequency_mhz,
        )
        try:
            prediction = self._model.predict(target, gateway)
        except Exception as exc:  # defensive — Stage1ItuModel / DEM backend là 3rd party
            # Backend DEM lookup raise (vd lat/lng ngoài DEM coverage) → coi
            # như reject "physics_unavailable" thay vì 500. User upload sai
            # vùng không nên kill request.
            logger.warning(
                "trust_validator_physics_failed",
                user_id=str(contributor.user_id),
                lat=record.latitude,
                lon=record.longitude,
                error=type(exc).__name__,
            )
            return ValidationResult(
                passed=False,
                reject_reason="physics_unavailable",
                layer="L2_physics",
            )

        predicted_rssi = float(prediction.rssi_dbm)
        delta = abs(record.rssi_dbm - predicted_rssi)
        if delta > PHYSICS_THRESHOLD_DB:
            return ValidationResult(
                passed=False,
                reject_reason="physics_outlier",
                layer="L2_physics",
                predicted_rssi_dbm=predicted_rssi,
                delta_db=round(delta, 2),
                threshold_db=PHYSICS_THRESHOLD_DB,
            )

        return ValidationResult(
            passed=True,
            reject_reason=None,
            layer="passed",
            predicted_rssi_dbm=predicted_rssi,
            delta_db=round(delta, 2),
            threshold_db=PHYSICS_THRESHOLD_DB,
        )

    def update_stats(
        self,
        conn: Connection,
        user_id: UUID,
        *,
        passed: bool,
    ) -> None:
        """Atomic increment accepted hoặc rejected counter + set last_at.

        Caller wrap transaction; nếu txn rollback (vd insert training fail),
        stats cũng revert — consistent state.
        """
        sql = _UPDATE_STATS_ACCEPTED if passed else _UPDATE_STATS_REJECTED
        conn.execute(sql, {"user_id": user_id, "now": datetime.now(UTC).isoformat()})


__all__ = [
    "PHYSICS_THRESHOLD_DB",
    "ContributorContext",
    "TrustValidator",
    "UnknownContributorError",
    "ValidationResult",
]
