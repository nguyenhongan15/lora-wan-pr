"""Promotion helpers — quarantine → pending-review queue với TrustValidator gating.

Pipeline 2-stage (admin manual gate, migration 0018):
  1. Auto-validate L1/L2/L3: Pass → set review_status='pending_review' chờ
     admin duyệt. Fail → set reject_reason (rác hiển nhiên, không vào queue).
  2. Admin xem queue → approve (INSERT training + stats.accepted++) hoặc
     reject (review_note + stats.rejected++).

Bump stats.rejected NGAY khi auto-reject (rác hiển nhiên là tín hiệu reputation
thật); stats.accepted CHỈ bump khi admin approve (auto-pass chưa phải accept).

Hai entry points:
  * `promote_pending_for_linked_source(ls_id)` — backfill khi user PATCH
    contribute_to_community=true HOẶC sau mỗi sync batch.
  * `promote_pending_for_uploader(uploader_id, since)` — CSV upload không
    có linked_source_id; lọc theo uploader + uploaded_at window.

Caller wrap transaction. KHÔNG raise: validator failure → `physics_unavailable`
reject_reason, vẫn count vào `PromotionResult.rejected`.

Filter cứng:
  * `submitted_for_community = true` (đã opt-in cộng đồng — personal-only
    không bao giờ promote).
  * `reject_reason IS NULL` (đã reject lần trước không retry).
  * `review_status IS NULL` (chưa auto-validate; rows pending_review/approved/
    rejected không re-process).
  * `external_id IS NOT NULL` (cần key idempotent; CSV upload đã gen
    deterministic hash → mọi community-eligible row đều có).
  * `NOT EXISTS` ở training (đã promote rồi không re-insert).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import Connection, text

from ...domain.coverage import GatewayId
from ...domain.survey import SurveyRecord
from .validator import (
    ContributorContext,
    TrustValidator,
    ValidationResult,
)

logger = structlog.get_logger("lora_coverage_api.trust.promotion")


@dataclass(frozen=True, slots=True)
class PromotionResult:
    """Count buckets sau khi loop promote 1 batch.

    `accepted` + `rejected` = số rows thực xử lý lần này. Rows đã ở training
    (NOT EXISTS filter) hoặc đã reject trước (reject_reason IS NOT NULL)
    không count — định nghĩa: PromotionResult phản ánh "decision mới phát
    sinh trong call này", không phải lifetime total.
    """

    accepted: int
    rejected: int
    by_reason: dict[str, int] = field(default_factory=dict)


# ── SQL ──────────────────────────────────────────────────────────────────
# Lọc q.external_id IS NOT NULL: ON CONFLICT (timestamp, source_type,
# external_id) WHERE external_id IS NOT NULL chỉ guard khi external_id có
# giá trị; NULL external_id sẽ insert lặp → CHỈ promote rows có external_id.
# CSV upload bắt buộc gen deterministic hash trước khi gọi write_quarantine.
_SELECT_BASE = """
    SELECT
        q.id, q.timestamp,
        ST_Y(q.location::geometry) AS lat,
        ST_X(q.location::geometry) AS lon,
        q.rssi_dbm, q.snr_db, q.spreading_factor, q.frequency_mhz,
        q.device_id, q.serving_gateway_id
    FROM ts.survey_quarantine q
    WHERE q.submitted_for_community = true
      AND q.reject_reason IS NULL
      AND q.review_status IS NULL
      AND q.external_id IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM ts.survey_training t
          WHERE t.timestamp = q.timestamp
            AND t.source_type = q.source_type
            AND t.external_id = q.external_id
      )
"""

_SELECT_PENDING_FOR_LS = text(
    _SELECT_BASE + " AND q.linked_source_id = :ls_id ORDER BY q.timestamp ASC"
)

# CSV upload filter: uploader + uploaded_at window (caller pass `since`
# trước khi insert batch để không match rows cũ của user).
_SELECT_PENDING_FOR_UPLOADER = text(
    _SELECT_BASE
    + " AND q.uploader_id = :uploader_id AND q.uploaded_at >= :since ORDER BY q.timestamp ASC"
)

# Variant per-batch: chỉ rows trong 1 lần upload (uploader_id + uploaded_at).
# Dùng cho "đóng góp từng file riêng" (POST /me/uploads/csv/batches/promote).
_SELECT_PENDING_CSV_FOR_BATCH = text(
    _SELECT_BASE
    + " AND q.uploader_id = :uploader_id AND q.source_type = 'csv_upload'"
    + " AND q.uploaded_at = :uploaded_at"
    + " ORDER BY q.timestamp ASC"
)

# Flip submitted_for_community false→true cho rows của 1 batch cụ thể (file).
# Filter cứng theo uploaded_at để không động vào file khác cùng user.
_MARK_SUBMITTED_FOR_CSV_BATCH = text(
    """
    UPDATE ts.survey_quarantine
    SET submitted_for_community = true
    WHERE uploader_id = :uploader_id
      AND source_type = 'csv_upload'
      AND uploaded_at = :uploaded_at
      AND submitted_for_community = false
      AND reject_reason IS NULL
    """
)

# List batch CSV của 1 user (group by uploaded_at). PostgreSQL `now()` =
# start-of-transaction → mọi row trong 1 lần upload share cùng uploaded_at,
# nên đây là batch key tự nhiên (không cần thêm batch_id column).
_LIST_CSV_BATCHES = text(
    """
    SELECT
        q.uploaded_at,
        COUNT(*)::int AS total,
        SUM(
            CASE WHEN q.reject_reason IS NOT NULL
                OR q.review_status = 'rejected'
            THEN 1 ELSE 0 END
        )::int AS rejected,
        SUM(
            CASE WHEN q.review_status = 'pending_review'
                AND q.reject_reason IS NULL
                AND NOT EXISTS (
                    SELECT 1 FROM ts.survey_training t
                    WHERE t.timestamp = q.timestamp
                      AND t.source_type = q.source_type
                      AND t.external_id = q.external_id
                )
            THEN 1 ELSE 0 END
        )::int AS pending_review,
        SUM(
            CASE WHEN EXISTS (
                SELECT 1 FROM ts.survey_training t
                WHERE t.timestamp = q.timestamp
                  AND t.source_type = q.source_type
                  AND t.external_id = q.external_id
            ) THEN 1 ELSE 0 END
        )::int AS promoted
    FROM ts.survey_quarantine q
    WHERE q.uploader_id = :uploader_id
      AND q.source_type = 'csv_upload'
    GROUP BY q.uploaded_at
    ORDER BY q.uploaded_at DESC
    """
)

# Xoá 1 batch CSV: trước tiên xoá rows ở training (nếu đã promote) theo
# (timestamp, source_type, external_id) match quarantine row; rồi xoá quarantine.
# 2-step để cascade promoted data (community dataset cũng mất khi user xoá file
# — quyền xoá dữ liệu cá nhân).
_DELETE_CSV_BATCH_TRAINING = text(
    """
    DELETE FROM ts.survey_training t
    USING ts.survey_quarantine q
    WHERE t.timestamp = q.timestamp
      AND t.source_type = q.source_type
      AND t.external_id = q.external_id
      AND q.uploader_id = :uploader_id
      AND q.source_type = 'csv_upload'
      AND q.uploaded_at = :uploaded_at
    """
)

_DELETE_CSV_BATCH_QUARANTINE = text(
    """
    DELETE FROM ts.survey_quarantine
    WHERE uploader_id = :uploader_id
      AND source_type = 'csv_upload'
      AND uploaded_at = :uploaded_at
    """
)

# Stats cho card "Tải lên CSV của tôi": tổng / promoted / rejected / pending_review.
# `pending` (limbo) derive ở caller = total - promoted - rejected - pending_review.
_CSV_STATS_FOR_UPLOADER = text(
    """
    SELECT
        COUNT(*)::int AS total,
        SUM(
            CASE WHEN q.reject_reason IS NOT NULL
                OR q.review_status = 'rejected'
            THEN 1 ELSE 0 END
        )::int AS rejected,
        SUM(
            CASE WHEN q.review_status = 'pending_review'
                AND q.reject_reason IS NULL
                AND NOT EXISTS (
                    SELECT 1 FROM ts.survey_training t
                    WHERE t.timestamp = q.timestamp
                      AND t.source_type = q.source_type
                      AND t.external_id = q.external_id
                )
            THEN 1 ELSE 0 END
        )::int AS pending_review,
        SUM(
            CASE WHEN EXISTS (
                SELECT 1 FROM ts.survey_training t
                WHERE t.timestamp = q.timestamp
                  AND t.source_type = q.source_type
                  AND t.external_id = q.external_id
            ) THEN 1 ELSE 0 END
        )::int AS promoted
    FROM ts.survey_quarantine q
    WHERE q.uploader_id = :uploader_id
      AND q.source_type = 'csv_upload'
    """
)

# Mark all submitted_for_community=false rows of an ls_id → true. Dùng khi
# user PATCH contribute_to_community=true lần đầu (backfill flag cho rows
# webhook đã pull về trước opt-in).
_MARK_SUBMITTED_FOR_LS = text(
    """
    UPDATE ts.survey_quarantine
    SET submitted_for_community = true
    WHERE linked_source_id = :ls_id
      AND submitted_for_community = false
    """
)

_MARK_REJECT = text(
    """
    UPDATE ts.survey_quarantine
    SET reject_reason = :reason
    WHERE timestamp = :ts AND id = :qid
    """
)

# Sau khi pass auto-validate L1/L2/L3: row chờ admin duyệt thủ công. Không
# INSERT training nữa — admin approve mới INSERT.
_MARK_PENDING_REVIEW = text(
    """
    UPDATE ts.survey_quarantine
    SET review_status = 'pending_review'
    WHERE timestamp = :ts AND id = :qid
    """
)

# Copy 1 quarantine row sang training (INSERT...SELECT theo (timestamp, id)
# primary key). ON CONFLICT DO NOTHING phòng race nếu cùng row được promote
# đồng thời (vd backfill chạy song song với sync — unlikely vì cả 2 lock
# qua engine.begin() nhưng defensive). gen_random_uuid() cho id mới vì
# training PK khác quarantine PK.
_INSERT_TRAINING_FROM_QUARANTINE = text(
    """
    INSERT INTO ts.survey_training (
        id, timestamp, location, rssi_dbm, snr_db,
        spreading_factor, frequency_mhz, device_id,
        serving_gateway_id, uploader_id,
        external_id, source_type, contributor_user_id, linked_source_id,
        submitted_for_community
    )
    SELECT
        gen_random_uuid(), q.timestamp, q.location, q.rssi_dbm, q.snr_db,
        q.spreading_factor, q.frequency_mhz, q.device_id,
        q.serving_gateway_id, q.uploader_id,
        q.external_id, q.source_type, q.contributor_user_id, q.linked_source_id,
        true
    FROM ts.survey_quarantine q
    WHERE q.timestamp = :ts AND q.id = :qid
    ON CONFLICT (timestamp, source_type, external_id) WHERE external_id IS NOT NULL
    DO NOTHING
    """
)


def mark_submitted_for_linked_source(conn: Connection, *, linked_source_id: UUID) -> int:
    """Set submitted_for_community=true cho tất cả rows của 1 linked_source
    đang ở false. Idempotent (re-run no-op).

    Trả số rows được flip (rowcount). Caller dùng cho logging.
    """
    result = conn.execute(_MARK_SUBMITTED_FOR_LS, {"ls_id": linked_source_id})
    return result.rowcount or 0


def promote_pending_for_linked_source(
    conn: Connection,
    validator: TrustValidator,
    contributor: ContributorContext,
    *,
    linked_source_id: UUID,
) -> PromotionResult:
    """Loop validate + promote mọi pending row của 1 linked_source.

    Caller (LinkingService.set_contribution hoặc sync orchestrator) đã ensure
    `contributor` được load 1 lần ở đầu — threshold ổn định cho mọi row
    trong batch.
    """
    rows = conn.execute(_SELECT_PENDING_FOR_LS, {"ls_id": linked_source_id}).all()
    return _run_loop(conn, validator, contributor, rows)


def promote_pending_for_uploader(
    conn: Connection,
    validator: TrustValidator,
    contributor: ContributorContext,
    *,
    uploader_id: UUID,
    since: datetime,
) -> PromotionResult:
    """Loop validate + promote mọi pending row của 1 uploader sau `since`.

    Dùng cho CSV upload (không có linked_source_id). `since` = thời điểm
    NGAY TRƯỚC khi gọi write_quarantine — tránh match rows cũ của user.
    """
    rows = conn.execute(
        _SELECT_PENDING_FOR_UPLOADER,
        {"uploader_id": uploader_id, "since": since},
    ).all()
    return _run_loop(conn, validator, contributor, rows)


@dataclass(frozen=True, slots=True)
class CsvUploaderStats:
    total: int
    promoted: int
    rejected: int
    pending_review: int

    @property
    def pending(self) -> int:
        """Rows trong quarantine chưa qua auto-validate (chưa promote, chưa
        reject, chưa pending_review). Distinct với pending_review = rows đã
        pass auto nhưng chờ admin duyệt thủ công.
        """
        return max(0, self.total - self.promoted - self.rejected - self.pending_review)


@dataclass(frozen=True, slots=True)
class CsvBatchSummary:
    """1 batch = 1 lần upload CSV, key = uploaded_at."""

    uploaded_at: datetime
    total: int
    promoted: int
    rejected: int
    pending_review: int

    @property
    def pending(self) -> int:
        return max(0, self.total - self.promoted - self.rejected - self.pending_review)


def list_csv_batches_for_uploader(
    conn: Connection,
    uploader_id: UUID,
) -> list[CsvBatchSummary]:
    """Liệt kê batch CSV (group by uploaded_at) — desc theo thời gian upload."""
    rows = conn.execute(_LIST_CSV_BATCHES, {"uploader_id": uploader_id}).all()
    return [
        CsvBatchSummary(
            uploaded_at=row.uploaded_at,
            total=int(row.total or 0),
            promoted=int(row.promoted or 0),
            rejected=int(row.rejected or 0),
            pending_review=int(row.pending_review or 0),
        )
        for row in rows
    ]


def delete_csv_batch_for_uploader(
    conn: Connection,
    *,
    uploader_id: UUID,
    uploaded_at: datetime,
) -> int:
    """Xoá tất cả rows của 1 batch CSV (kể cả đã promote sang training).

    Trả về số quarantine rows deleted (0 = batch không tồn tại / không thuộc
    uploader này).
    """
    conn.execute(
        _DELETE_CSV_BATCH_TRAINING,
        {"uploader_id": uploader_id, "uploaded_at": uploaded_at},
    )
    result = conn.execute(
        _DELETE_CSV_BATCH_QUARANTINE,
        {"uploader_id": uploader_id, "uploaded_at": uploaded_at},
    )
    return result.rowcount or 0


def fetch_csv_stats_for_uploader(conn: Connection, uploader_id: UUID) -> CsvUploaderStats:
    """Stats CSV upload của 1 user — dùng cho UI card hiển thị backlog."""
    row = conn.execute(_CSV_STATS_FOR_UPLOADER, {"uploader_id": uploader_id}).one()
    return CsvUploaderStats(
        total=int(row.total or 0),
        promoted=int(row.promoted or 0),
        rejected=int(row.rejected or 0),
        pending_review=int(row.pending_review or 0),
    )


def mark_and_promote_csv_batch_for_uploader(
    conn: Connection,
    validator: TrustValidator,
    contributor: ContributorContext,
    *,
    uploader_id: UUID,
    uploaded_at: datetime,
) -> PromotionResult:
    """Đóng góp 1 file CSV cụ thể (1 batch = 1 lần upload).

    Flow:
      1. UPDATE quarantine SET submitted_for_community=true cho mọi
         csv_upload row của user CÙNG uploaded_at, còn ở false + chưa reject.
      2. SELECT pending row của batch (filter uploaded_at).
      3. Run validator loop → mark pending_review hoặc set reject_reason.

    Idempotent: rerun chỉ chạy validator cho rows mới chưa xét — rows pass
    đã ở review_status='pending_review' (filter loại qua _SELECT_BASE),
    rows reject có reject_reason (cũng filter loại).
    """
    conn.execute(
        _MARK_SUBMITTED_FOR_CSV_BATCH,
        {"uploader_id": uploader_id, "uploaded_at": uploaded_at},
    )
    rows = conn.execute(
        _SELECT_PENDING_CSV_FOR_BATCH,
        {"uploader_id": uploader_id, "uploaded_at": uploaded_at},
    ).all()
    return _run_loop(conn, validator, contributor, rows)


# ── admin manual review ─────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class PendingContribution:
    """1 row đang chờ admin duyệt. Đủ field cho preview map + table."""

    id: UUID
    timestamp: datetime
    latitude: float
    longitude: float
    rssi_dbm: float
    snr_db: float
    spreading_factor: int
    frequency_mhz: float
    source_type: str | None
    contributor_user_id: UUID | None
    contributor_email: str | None
    serving_gateway_id: UUID | None
    gateway_code: str | None
    linked_source_id: UUID | None
    submitted_at: datetime


_LIST_PENDING_REVIEW = text(
    """
    SELECT
        q.id, q.timestamp,
        ST_Y(q.location::geometry) AS lat,
        ST_X(q.location::geometry) AS lon,
        q.rssi_dbm, q.snr_db, q.spreading_factor, q.frequency_mhz,
        q.source_type, q.contributor_user_id, q.serving_gateway_id,
        q.linked_source_id, q.uploaded_at,
        u.email AS contributor_email,
        g.code AS gateway_code
    FROM ts.survey_quarantine q
    LEFT JOIN auth.users u ON u.id = q.contributor_user_id
    LEFT JOIN geo.gateways g ON g.id = q.serving_gateway_id
    WHERE q.review_status = 'pending_review'
    ORDER BY q.timestamp DESC
    LIMIT :limit OFFSET :offset
    """
)

_COUNT_PENDING_REVIEW = text(
    "SELECT COUNT(*)::int AS total FROM ts.survey_quarantine WHERE review_status = 'pending_review'"
)

# Fetch 1 row pending để admin xem detail + so sánh với predicted RSSI.
_GET_PENDING_BY_ID = text(
    """
    SELECT
        q.id, q.timestamp,
        ST_Y(q.location::geometry) AS lat,
        ST_X(q.location::geometry) AS lon,
        q.rssi_dbm, q.snr_db, q.spreading_factor, q.frequency_mhz,
        q.source_type, q.contributor_user_id, q.serving_gateway_id,
        q.linked_source_id, q.uploaded_at,
        u.email AS contributor_email,
        g.code AS gateway_code
    FROM ts.survey_quarantine q
    LEFT JOIN auth.users u ON u.id = q.contributor_user_id
    LEFT JOIN geo.gateways g ON g.id = q.serving_gateway_id
    WHERE q.id = :qid AND q.review_status = 'pending_review'
    """
)

_APPROVE_PENDING = text(
    """
    UPDATE ts.survey_quarantine
    SET review_status = 'approved',
        reviewed_by_user_id = :reviewer_id,
        reviewed_at = now()
    WHERE id = :qid AND review_status = 'pending_review'
    RETURNING timestamp, contributor_user_id
    """
)

_REJECT_PENDING = text(
    """
    UPDATE ts.survey_quarantine
    SET review_status = 'rejected',
        reviewed_by_user_id = :reviewer_id,
        reviewed_at = now(),
        review_note = :note
    WHERE id = :qid AND review_status = 'pending_review'
    RETURNING timestamp, contributor_user_id
    """
)


# ── batch (file) review ──────────────────────────────────────────────────
# Group quarantine rows by (uploader_id, uploaded_at) — đây là key tự nhiên
# cho 1 lần upload CSV. Chỉ list batch có ít nhất 1 row pending_review (admin
# không cần thấy file đã duyệt xong hoặc chưa promote).
_LIST_PENDING_REVIEW_BATCHES = text(
    """
    SELECT
        q.uploader_id,
        u.email AS uploader_email,
        q.uploaded_at,
        COUNT(*) FILTER (
            WHERE q.review_status = 'pending_review'
        )::int AS pending_review_count,
        COUNT(*)::int AS total_count,
        MIN(q.timestamp) AS earliest_ts,
        MAX(q.timestamp) AS latest_ts
    FROM ts.survey_quarantine q
    LEFT JOIN auth.users u ON u.id = q.uploader_id
    WHERE q.source_type = 'csv_upload'
      AND q.uploader_id IS NOT NULL
    GROUP BY q.uploader_id, u.email, q.uploaded_at
    HAVING COUNT(*) FILTER (WHERE q.review_status = 'pending_review') > 0
    ORDER BY q.uploaded_at DESC
    """
)

_SELECT_PENDING_REVIEW_FOR_BATCH = text(
    """
    SELECT
        q.id, q.timestamp,
        ST_Y(q.location::geometry) AS lat,
        ST_X(q.location::geometry) AS lon,
        q.rssi_dbm, q.snr_db, q.spreading_factor, q.frequency_mhz,
        q.source_type, q.contributor_user_id, q.serving_gateway_id,
        q.linked_source_id, q.uploaded_at,
        u.email AS contributor_email,
        g.code AS gateway_code
    FROM ts.survey_quarantine q
    LEFT JOIN auth.users u ON u.id = q.contributor_user_id
    LEFT JOIN geo.gateways g ON g.id = q.serving_gateway_id
    WHERE q.review_status = 'pending_review'
      AND q.uploader_id = :uploader_id
      AND q.uploaded_at = :uploaded_at
      AND q.source_type = 'csv_upload'
    ORDER BY q.timestamp ASC
    """
)


@dataclass(frozen=True, slots=True)
class PendingReviewBatch:
    """1 batch CSV (uploader + uploaded_at) có ≥1 row đang chờ duyệt."""

    uploader_id: UUID
    uploader_email: str | None
    uploaded_at: datetime
    pending_review_count: int
    total_count: int
    earliest_timestamp: datetime
    latest_timestamp: datetime


def _row_to_pending(row: Any) -> PendingContribution:
    """Convert SQL row (alias `lat`/`lon` + LEFT JOIN) → PendingContribution."""
    return PendingContribution(
        id=row.id,
        timestamp=row.timestamp,
        latitude=float(row.lat),
        longitude=float(row.lon),
        rssi_dbm=float(row.rssi_dbm),
        snr_db=float(row.snr_db),
        spreading_factor=int(row.spreading_factor),
        frequency_mhz=float(row.frequency_mhz),
        source_type=row.source_type,
        contributor_user_id=row.contributor_user_id,
        contributor_email=row.contributor_email,
        serving_gateway_id=row.serving_gateway_id,
        gateway_code=row.gateway_code,
        linked_source_id=row.linked_source_id,
        submitted_at=row.uploaded_at,
    )


def list_pending_review(
    conn: Connection, *, limit: int = 50, offset: int = 0
) -> tuple[list[PendingContribution], int]:
    """Admin queue: rows đã pass auto-validate, chờ duyệt thủ công."""
    total = conn.execute(_COUNT_PENDING_REVIEW).scalar_one()
    rows = conn.execute(_LIST_PENDING_REVIEW, {"limit": limit, "offset": offset}).all()
    return [_row_to_pending(r) for r in rows], int(total or 0)


def get_pending_review(conn: Connection, qid: UUID) -> PendingContribution | None:
    """Lấy 1 row pending để admin xem detail."""
    row = conn.execute(_GET_PENDING_BY_ID, {"qid": qid}).first()
    if row is None:
        return None
    return _row_to_pending(row)


def list_pending_review_batches(conn: Connection) -> list[PendingReviewBatch]:
    """List các file (uploader + uploaded_at) còn ≥1 row pending_review."""
    rows = conn.execute(_LIST_PENDING_REVIEW_BATCHES).all()
    return [
        PendingReviewBatch(
            uploader_id=row.uploader_id,
            uploader_email=row.uploader_email,
            uploaded_at=row.uploaded_at,
            pending_review_count=int(row.pending_review_count or 0),
            total_count=int(row.total_count or 0),
            earliest_timestamp=row.earliest_ts,
            latest_timestamp=row.latest_ts,
        )
        for row in rows
    ]


def list_pending_review_for_batch(
    conn: Connection, *, uploader_id: UUID, uploaded_at: datetime
) -> list[PendingContribution]:
    """Detail rows pending_review của 1 batch — admin drill-in xem trước duyệt."""
    rows = conn.execute(
        _SELECT_PENDING_REVIEW_FOR_BATCH,
        {"uploader_id": uploader_id, "uploaded_at": uploaded_at},
    ).all()
    return [_row_to_pending(r) for r in rows]


def approve_pending_review_batch(
    conn: Connection,
    validator: TrustValidator,
    *,
    uploader_id: UUID,
    uploaded_at: datetime,
    reviewer_id: UUID,
) -> list[PendingContribution]:
    """Approve mọi pending_review row của 1 batch trong cùng txn.

    Trả về list rows đã approve thành công (caller dùng để gửi email summary).
    Row đã bị reject hoặc đã approve trước = không count.
    """
    rows = conn.execute(
        _SELECT_PENDING_REVIEW_FOR_BATCH,
        {"uploader_id": uploader_id, "uploaded_at": uploaded_at},
    ).all()
    approved: list[PendingContribution] = []
    for row in rows:
        ok = approve_pending_contribution(conn, validator, qid=row.id, reviewer_id=reviewer_id)
        if ok:
            approved.append(_row_to_pending(row))
    return approved


def reject_pending_review_batch(
    conn: Connection,
    validator: TrustValidator,
    *,
    uploader_id: UUID,
    uploaded_at: datetime,
    reviewer_id: UUID,
    note: str | None,
) -> list[PendingContribution]:
    """Reject mọi pending_review row của 1 batch trong cùng txn.

    Trả về list rows đã reject thành công (caller dùng để gửi email summary
    cho user — 1 email/batch chứa lý do từ admin, không spam per-row).
    """
    rows = conn.execute(
        _SELECT_PENDING_REVIEW_FOR_BATCH,
        {"uploader_id": uploader_id, "uploaded_at": uploaded_at},
    ).all()
    rejected: list[PendingContribution] = []
    for row in rows:
        ok = reject_pending_contribution(
            conn, validator, qid=row.id, reviewer_id=reviewer_id, note=note
        )
        if ok:
            rejected.append(_row_to_pending(row))
    return rejected


def approve_pending_contribution(
    conn: Connection,
    validator: TrustValidator,
    *,
    qid: UUID,
    reviewer_id: UUID,
) -> bool:
    """Admin approve: INSERT training + mark approved + bump stats.accepted.

    Trả False nếu row không tồn tại / không phải pending_review (race với
    reject hoặc đã xử lý). Idempotent: gọi lần 2 = no-op return False.
    """
    updated = conn.execute(_APPROVE_PENDING, {"qid": qid, "reviewer_id": reviewer_id}).first()
    if updated is None:
        return False
    conn.execute(
        _INSERT_TRAINING_FROM_QUARANTINE,
        {"ts": updated.timestamp, "qid": qid},
    )
    if updated.contributor_user_id is not None:
        validator.update_stats(conn, updated.contributor_user_id, passed=True)
    logger.info(
        "admin_contribution_approved",
        qid=str(qid),
        reviewer_id=str(reviewer_id),
        contributor_user_id=(
            str(updated.contributor_user_id) if updated.contributor_user_id else None
        ),
    )
    return True


def reject_pending_contribution(
    conn: Connection,
    validator: TrustValidator,
    *,
    qid: UUID,
    reviewer_id: UUID,
    note: str | None,
) -> bool:
    """Admin reject: mark rejected + review_note + bump stats.rejected."""
    updated = conn.execute(
        _REJECT_PENDING,
        {"qid": qid, "reviewer_id": reviewer_id, "note": note},
    ).first()
    if updated is None:
        return False
    if updated.contributor_user_id is not None:
        validator.update_stats(conn, updated.contributor_user_id, passed=False)
    logger.info(
        "admin_contribution_rejected",
        qid=str(qid),
        reviewer_id=str(reviewer_id),
        contributor_user_id=(
            str(updated.contributor_user_id) if updated.contributor_user_id else None
        ),
        has_note=bool(note),
    )
    return True


# ── private helpers ─────────────────────────────────────────────────────


def _row_to_record(row: Any) -> SurveyRecord:
    """Convert SELECT row → SurveyRecord. submitted_for_community=true vì
    pipeline chỉ chạy qua rows đã set flag (xem _SELECT_BASE).
    """
    return SurveyRecord(
        timestamp=row.timestamp,
        latitude=float(row.lat),
        longitude=float(row.lon),
        rssi_dbm=float(row.rssi_dbm),
        snr_db=float(row.snr_db),
        spreading_factor=int(row.spreading_factor),
        frequency_mhz=float(row.frequency_mhz),
        device_id=row.device_id,
        serving_gateway_id=GatewayId(row.serving_gateway_id) if row.serving_gateway_id else None,
        submitted_for_community=True,
    )


def _promote_one(
    conn: Connection,
    validator: TrustValidator,
    contributor: ContributorContext,
    row: Any,
) -> ValidationResult:
    """Validate 1 row → đẩy vào pending-review (pass) hoặc set reject_reason (fail).

    Migration 0018: pass KHÔNG INSERT training nữa — chờ admin approve. Stats
    chỉ bump khi rejected (auto-reject = rác thật). Accepted bump ở
    approve_pending_contribution (admin gate) chứ không phải lúc này.
    """
    record = _row_to_record(row)
    result = validator.validate(record, contributor)
    if result.passed:
        conn.execute(
            _MARK_PENDING_REVIEW,
            {"ts": row.timestamp, "qid": row.id},
        )
    else:
        conn.execute(
            _MARK_REJECT,
            {
                "ts": row.timestamp,
                "qid": row.id,
                "reason": result.reject_reason,
            },
        )
        validator.update_stats(conn, contributor.user_id, passed=False)
    return result


def _run_loop(
    conn: Connection,
    validator: TrustValidator,
    contributor: ContributorContext,
    rows: Sequence[Any],
) -> PromotionResult:
    accepted = rejected = 0
    by_reason: dict[str, int] = {}
    for row in rows:
        result = _promote_one(conn, validator, contributor, row)
        if result.passed:
            accepted += 1
        else:
            rejected += 1
            reason = result.reject_reason or "unknown"
            by_reason[reason] = by_reason.get(reason, 0) + 1
    if accepted or rejected:
        logger.info(
            "trust_promotion_completed",
            user_id=str(contributor.user_id),
            accepted=accepted,
            rejected=rejected,
            by_reason=by_reason,
        )
    return PromotionResult(accepted=accepted, rejected=rejected, by_reason=by_reason)


__all__ = [
    "CsvBatchSummary",
    "CsvUploaderStats",
    "PendingContribution",
    "PromotionResult",
    "approve_pending_contribution",
    "delete_csv_batch_for_uploader",
    "fetch_csv_stats_for_uploader",
    "get_pending_review",
    "list_csv_batches_for_uploader",
    "list_pending_review",
    "mark_and_promote_csv_batch_for_uploader",
    "mark_submitted_for_linked_source",
    "promote_pending_for_linked_source",
    "promote_pending_for_uploader",
    "reject_pending_contribution",
]
