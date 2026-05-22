"""Promotion helpers — quarantine → training với TrustValidator gating.

Plan community-data-contribution §3.4: thay vì INSERT...SELECT bulk copy,
mỗi quarantine row chạy qua `TrustValidator.validate()` per-record. Pass →
INSERT training; fail → set `reject_reason` ngay tại quarantine để admin/
debug trace lý do. Stats accepted/rejected accumulate vào
auth.users.contribution_stats theo từng record.

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
  * `external_id IS NOT NULL` (cần key idempotent; CSV upload đã gen
    deterministic hash → mọi community-eligible row đều có).
  * `NOT EXISTS` ở training (đã promote rồi không re-insert).
"""

from __future__ import annotations

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

# Variant không lọc theo time window: dùng cho "đóng góp tất cả CSV đã upload"
# (POST /me/uploads/csv/promote). Filter `source_type='csv_upload'` để không
# nhầm với row webhook của cùng user (đã có cơ chế promote qua linked_source).
_SELECT_PENDING_CSV_FOR_UPLOADER = text(
    _SELECT_BASE
    + " AND q.uploader_id = :uploader_id AND q.source_type = 'csv_upload'"
    + " ORDER BY q.timestamp ASC"
)

# Mark all csv_upload rows của 1 uploader đang submitted_for_community=false →
# true (chỉ rows chưa reject để promote pipeline xét lại). Idempotent.
_MARK_SUBMITTED_FOR_CSV_UPLOADER = text(
    """
    UPDATE ts.survey_quarantine
    SET submitted_for_community = true
    WHERE uploader_id = :uploader_id
      AND source_type = 'csv_upload'
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
        SUM(CASE WHEN q.reject_reason IS NOT NULL THEN 1 ELSE 0 END)::int
            AS rejected,
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

# Stats cho card "Tải lên CSV của tôi": tổng / promoted / rejected. Pending
# derive ở caller = total - promoted - rejected (rows trong quarantine còn lại
# = candidate cho promote).
_CSV_STATS_FOR_UPLOADER = text(
    """
    SELECT
        COUNT(*)::int AS total,
        SUM(CASE WHEN q.reject_reason IS NOT NULL THEN 1 ELSE 0 END)::int
            AS rejected,
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

    @property
    def pending(self) -> int:
        """Rows còn lại trong quarantine (chưa promote, chưa reject)."""
        return max(0, self.total - self.promoted - self.rejected)


@dataclass(frozen=True, slots=True)
class CsvBatchSummary:
    """1 batch = 1 lần upload CSV, key = uploaded_at."""

    uploaded_at: datetime
    total: int
    promoted: int
    rejected: int

    @property
    def pending(self) -> int:
        return max(0, self.total - self.promoted - self.rejected)


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
    )


def mark_and_promote_csv_for_uploader(
    conn: Connection,
    validator: TrustValidator,
    contributor: ContributorContext,
    *,
    uploader_id: UUID,
) -> PromotionResult:
    """One-shot "đóng góp tất cả CSV đã upload" cho 1 user.

    Flow:
      1. UPDATE quarantine SET submitted_for_community=true cho mọi
         csv_upload row của user còn ở false + chưa reject.
      2. SELECT mọi csv_upload pending row của user (kể cả rows từ batch
         upload trước — không lọc theo `since`).
      3. Run validator loop → INSERT training hoặc set reject_reason.

    Idempotent: rerun chỉ chạy validator cho rows mới insert sau lần promote
    trước (rows đã pass nằm ở training, NOT EXISTS lọc; rows đã reject có
    reject_reason → filter loại).
    """
    conn.execute(_MARK_SUBMITTED_FOR_CSV_UPLOADER, {"uploader_id": uploader_id})
    rows = conn.execute(
        _SELECT_PENDING_CSV_FOR_UPLOADER,
        {"uploader_id": uploader_id},
    ).all()
    return _run_loop(conn, validator, contributor, rows)


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
    """Validate 1 row → insert training (pass) hoặc set reject_reason (fail).
    Cập nhật stats atomic cuối cùng (transaction wrap caller — rollback toàn
    batch khi raise).
    """
    record = _row_to_record(row)
    result = validator.validate(record, contributor)
    if result.passed:
        conn.execute(
            _INSERT_TRAINING_FROM_QUARANTINE,
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
    validator.update_stats(conn, contributor.user_id, passed=result.passed)
    return result


def _run_loop(
    conn: Connection,
    validator: TrustValidator,
    contributor: ContributorContext,
    rows: list[Any],
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
    "PromotionResult",
    "delete_csv_batch_for_uploader",
    "fetch_csv_stats_for_uploader",
    "list_csv_batches_for_uploader",
    "mark_and_promote_csv_for_uploader",
    "mark_submitted_for_linked_source",
    "promote_pending_for_linked_source",
    "promote_pending_for_uploader",
]
