"""TrustValidator — 3-layer pipeline cho community measurement contribution.

Plan community-data-contribution. Mỗi measurement đánh dấu
`submitted_for_community=true` (CSV upload checkbox / linked_source opt-in)
phải pass cả 3 lớp dưới mới được promote vào ts.survey_training:

  L1 hard gates:
    - lat/lng ∈ VIETNAM_BBOX (Scope Vietnam only)
    - serving_gateway_id resolve về geo.gateways row hiện hữu
    (RSSI/SNR/SF/lat-lng bounds đã enforce ở SurveyRecord.__post_init__ →
    không bao giờ tới validator; deduplicate qua DB unique index trên
    (timestamp, source_type, external_id).)

  L2 ITU physics plausibility:
    - so |observed_rssi - Stage1ItuModel.predict(target, gateway)| với
      threshold động (do L3 quyết định).
    - Reject reason "physics_outlier" nếu vượt threshold.

  L3 contributor reputation:
    - KHÔNG phải hard gate — chỉ điều chỉnh threshold L2.
    - Score 0..1 từ email_verified + account age + history accepted/rejected.
    - Threshold = 15 + 15 * score (dB). User mới strict (15 dB), user uy tín
      lỏng (30 dB) — đúng spirit "auto-promote tất cả nếu pass hard checks"
      kết hợp với "reputation as soft layer".

Deep module (Ousterhout Ch4): interface 1 method `validate(record, user_id)`
+ 1 method `update_stats(user_id, passed)`. Hidden: gateway lookup, ITU
prediction, JSONB atomic increment, reputation formula.

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


# ── Reputation tuning constants ─────────────────────────────────────────────
# Threshold range: 15 dB (new user, no history) → 30 dB (verified, mature,
# clean history). Tuned theo Stage 1 ITU shadow-fading σ ~ 6-8 dB → 2σ ~ 16 dB
# là ngưỡng "outlier" thông thường; verified user được cho phép 4σ.
_THRESHOLD_DB_MIN = 15.0
_THRESHOLD_DB_MAX = 30.0
_ACCOUNT_AGE_DAYS_FOR_BOOST = 30  # > 30 ngày = "mature" → +0.2
_ACCEPTED_SATURATION = 100  # 100 accepted = max history boost
_VERIFIED_BOOST = 0.3
_MATURE_BOOST = 0.2
_HISTORY_BOOST_MAX = 0.5
_REJECTION_PENALTY_MAX = 0.5


@dataclass(frozen=True, slots=True)
class ContributorContext:
    """Snapshot reputation của 1 user tại thời điểm validate.

    Loaded từ auth.users (email_verified, created_at, contribution_stats).
    Immutable per-validate-call để L3 thresh không phụ thuộc thứ tự record
    trong batch (nếu cập nhật stats sau từng record, threshold sẽ drift
    giữa các record cùng batch — không mong muốn).
    """

    user_id: UUID
    email_verified: bool
    created_at: datetime
    accepted: int
    rejected: int


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Output của TrustValidator.validate.

    `passed=True` → caller copy record sang ts.survey_training.
    `passed=False` → caller ghi reject_reason vào quarantine row + KHÔNG promote.

    Debugging fields (`predicted_rssi_dbm`, `delta_db`, `threshold_db`,
    `reputation_score`) phục vụ log/admin UI; tất cả None khi reject sớm ở L1.
    """

    passed: bool
    reject_reason: str | None
    layer: str  # "L1_bbox" | "L1_gateway" | "L2_physics" | "passed"
    predicted_rssi_dbm: float | None = None
    delta_db: float | None = None
    threshold_db: float | None = None
    reputation_score: float | None = None


# ── SQL ──────────────────────────────────────────────────────────────────────

_SELECT_CONTRIBUTOR = text(
    """
    SELECT id, email_verified, created_at, contribution_stats
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
        to_jsonb(:now::text),
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
        to_jsonb(:now::text),
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
        """Snapshot reputation 1 lần đầu batch. Caller pass lại context cho
        mọi record cùng batch để L3 thresh ổn định.

        Raises:
            UnknownContributorError: user_id không tồn tại.
        """
        row = conn.execute(_SELECT_CONTRIBUTOR, {"user_id": user_id}).one_or_none()
        if row is None:
            raise UnknownContributorError(f"user_id {user_id} không tồn tại")
        stats = row.contribution_stats or {}
        return ContributorContext(
            user_id=row.id,
            email_verified=bool(row.email_verified),
            created_at=row.created_at,
            accepted=int(stats.get("accepted", 0)),
            rejected=int(stats.get("rejected", 0)),
        )

    def validate(
        self,
        record: SurveyRecord,
        contributor: ContributorContext,
    ) -> ValidationResult:
        """Run 3-layer pipeline. KHÔNG raise — failure → ValidationResult.

        `contributor` đã được load 1 lần ở đầu batch; method này không touch
        DB nữa (trừ gateway directory lookup là singleton-cached read).
        """
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

        # ── L3 first: compute threshold để gating L2 ──────────────────────
        score = _reputation_score(contributor)
        threshold_db = _THRESHOLD_DB_MIN + (_THRESHOLD_DB_MAX - _THRESHOLD_DB_MIN) * score

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
                reputation_score=round(score, 3),
            )

        predicted_rssi = float(prediction.rssi_dbm)
        delta = abs(record.rssi_dbm - predicted_rssi)
        if delta > threshold_db:
            return ValidationResult(
                passed=False,
                reject_reason="physics_outlier",
                layer="L2_physics",
                predicted_rssi_dbm=predicted_rssi,
                delta_db=round(delta, 2),
                threshold_db=round(threshold_db, 2),
                reputation_score=round(score, 3),
            )

        return ValidationResult(
            passed=True,
            reject_reason=None,
            layer="passed",
            predicted_rssi_dbm=predicted_rssi,
            delta_db=round(delta, 2),
            threshold_db=round(threshold_db, 2),
            reputation_score=round(score, 3),
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


# ── private helpers ─────────────────────────────────────────────────────────


def _reputation_score(c: ContributorContext) -> float:
    """Tính reputation [0, 1] từ ContributorContext.

    Formula (xem plan §L3):
      +0.3 nếu email_verified
      +0.2 nếu account > 30 ngày
      +0.5 * min(1, accepted/100)
      -0.5 * (rejected / max(1, accepted + rejected))   ← tỉ lệ reject penalty

    Clamp về [0, 1]. Penalty pure ratio (không saturate theo absolute count)
    để 1 user reject 100% tất cả → score đáy bất kể history dài.
    """
    score = 0.0
    if c.email_verified:
        score += _VERIFIED_BOOST
    age_days = (datetime.now(UTC) - c.created_at).total_seconds() / 86400.0
    if age_days >= _ACCOUNT_AGE_DAYS_FOR_BOOST:
        score += _MATURE_BOOST
    score += _HISTORY_BOOST_MAX * min(1.0, c.accepted / _ACCEPTED_SATURATION)
    total = c.accepted + c.rejected
    if total > 0:
        rejection_ratio = c.rejected / total
        score -= _REJECTION_PENALTY_MAX * rejection_ratio
    return max(0.0, min(1.0, score))


__all__ = [
    "ContributorContext",
    "TrustValidator",
    "UnknownContributorError",
    "ValidationResult",
]
