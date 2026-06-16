"""me.upload_batches CRUD + aggregate helpers.

Mỗi batch = 1 lần user "bắn data" vào hệ thống. Kind quy về 1 trong 4 nhãn
tương ứng UI "Loại file":

  * 'csv'             → "CSV"
  * 'json'            → "JSON"
  * 'sync_lpwanmapper'→ "Đồng bộ Lpwanmapper"
  * 'sync_chirpstack' → "Đồng bộ ChirpStack"

Filename cho upload = `UploadFile.filename`; cho sync = ISO timestamp lúc
click (vd "2026-06-11T15:42:31+07:00") — caller responsibility.

Status batch không cache: derive ở `UploadBatchSummary.status` từ count
quarantine/training rows trỏ về batch_id. Soft-delete = `deleted_at IS NOT
NULL`; "Quản lý dữ liệu" hide row deleted, "Lịch sử upload" show full.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

import structlog
from sqlalchemy import Connection, text

logger = structlog.get_logger("lora_coverage_api.uploads.batches")

UploadKind = Literal["csv", "json", "sync_lpwanmapper", "sync_chirpstack", "live_session"]

BatchStatus = Literal["private", "pending", "public", "rejected", "deleted"]


@dataclass(frozen=True, slots=True)
class UploadBatchSummary:
    """1 row UI table — Quản lý dữ liệu / Lịch sử upload."""

    id: UUID
    kind: UploadKind
    filename: str
    linked_source_id: UUID | None
    uploaded_at: datetime
    points_count: int
    deleted_at: datetime | None
    pending_count: int
    promoted_count: int
    rejected_count: int

    @property
    def status(self) -> BatchStatus:
        """Suy luận trạng thái theo thứ tự ưu tiên (deleted > public > pending
        > rejected > private). Hợp với spec UI:

          * deleted  → batch đã xoá (chỉ hiện trong Lịch sử upload).
          * public   → có ≥1 row đã admin duyệt vào training.
          * pending  → có ≥1 row chờ admin duyệt, chưa có row nào public.
          * rejected → tất cả các row đã reject (không còn pending, không
                       public).
          * private  → batch còn nguyên ở quarantine, user chưa bấm Đóng góp.
        """
        if self.deleted_at is not None:
            return "deleted"
        if self.promoted_count > 0:
            return "public"
        if self.pending_count > 0:
            return "pending"
        if self.rejected_count > 0 and self.rejected_count >= self.points_count:
            return "rejected"
        return "private"


_INSERT_BATCH = text(
    """
    INSERT INTO me.upload_batches (
        user_id, kind, filename, linked_source_id, uploaded_at, points_count
    )
    VALUES (
        :user_id, :kind, :filename, :linked_source_id,
        COALESCE(:uploaded_at, now()), :points_count
    )
    RETURNING id, uploaded_at
    """
)

_UPDATE_POINTS_COUNT = text(
    """
    UPDATE me.upload_batches
    SET points_count = :count
    WHERE id = :batch_id
    """
)

# Aggregate count quarantine + training per batch. LEFT JOIN LATERAL với 2
# subquery: Postgres planner đẩy `batch_id = b.id` filter vào trong, hit
# index ix_survey_quarantine_batch / ix_survey_training_batch nên O(rows
# của batch) thay vì O(tổng survey).
_LIST_BATCHES = text(
    """
    SELECT
        b.id, b.kind, b.filename, b.linked_source_id,
        b.uploaded_at, b.points_count, b.deleted_at,
        COALESCE(q.pending_count, 0)::int AS pending_count,
        COALESCE(q.rejected_count, 0)::int AS rejected_count,
        COALESCE(t.promoted_count, 0)::int AS promoted_count
    FROM me.upload_batches b
    LEFT JOIN LATERAL (
        SELECT
            COUNT(*) FILTER (
                WHERE review_status = 'pending_review'
                  AND reject_reason IS NULL
            ) AS pending_count,
            COUNT(*) FILTER (
                WHERE reject_reason IS NOT NULL
                   OR review_status = 'rejected'
            ) AS rejected_count
        FROM ts.survey_quarantine
        WHERE batch_id = b.id
    ) q ON true
    LEFT JOIN LATERAL (
        SELECT COUNT(*) AS promoted_count
        FROM ts.survey_training
        WHERE batch_id = b.id
    ) t ON true
    WHERE b.user_id = :user_id
      AND (:include_deleted OR b.deleted_at IS NULL)
    ORDER BY b.uploaded_at DESC
    """
)

# Mark + queue 1 batch cho admin review. 2 UPDATE liên tiếp:
#   1. submitted_for_community: false → true cho rows chưa flip.
#   2. review_status: NULL → 'pending_review' cho rows eligible.
# Filter `batch_id = :batch_id AND uploader_id = :user_id` defense-in-depth.
_MARK_SUBMITTED_FOR_BATCH = text(
    """
    UPDATE ts.survey_quarantine
    SET submitted_for_community = true
    WHERE batch_id = :batch_id
      AND uploader_id = :user_id
      AND submitted_for_community = false
      AND reject_reason IS NULL
    """
)

_QUEUE_PENDING_FOR_BATCH = text(
    """
    UPDATE ts.survey_quarantine q
    SET review_status = 'pending_review'
    WHERE q.batch_id = :batch_id
      AND q.uploader_id = :user_id
      AND q.submitted_for_community = true
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
)

# Xoá batch (user-side). Policy hiện tại: user xoá batch chỉ rút lại data
# CHƯA được admin duyệt (quarantine). Training rows (đã approve, đang ở bản
# đồ chung) GIỮ NGUYÊN — community visibility là quyết định của admin, user
# không revoke đơn phương được. Muốn xoá khỏi community → admin tab "Dữ liệu
# đã duyệt". "Của tôi" sẽ loại training rows thuộc batch deleted_at IS NOT
# NULL bằng filter ở repo layer.
_DELETE_QUARANTINE_FOR_BATCH = text("DELETE FROM ts.survey_quarantine WHERE batch_id = :batch_id")

_SOFT_DELETE_BATCH = text(
    """
    UPDATE me.upload_batches
    SET deleted_at = now()
    WHERE id = :batch_id
      AND user_id = :user_id
      AND deleted_at IS NULL
    RETURNING id
    """
)

# Overview cho card Tổng quan: đếm batch theo trạng thái suy diễn.
# Chỉ count batch chưa xoá (deleted_at IS NULL) — Lịch sử upload mới hiện
# deleted; phần "Tổng quan" mô tả data đang sống.
_OVERVIEW_COUNTS = text(
    """
    WITH per_batch AS (
        SELECT
            b.id,
            COALESCE(q.pending_count, 0) AS pending_count,
            COALESCE(t.promoted_count, 0) AS promoted_count,
            COALESCE(q.rejected_count, 0) AS rejected_count,
            b.points_count
        FROM me.upload_batches b
        LEFT JOIN LATERAL (
            SELECT
                COUNT(*) FILTER (
                    WHERE review_status = 'pending_review'
                      AND reject_reason IS NULL
                ) AS pending_count,
                COUNT(*) FILTER (
                    WHERE reject_reason IS NOT NULL
                       OR review_status = 'rejected'
                ) AS rejected_count
            FROM ts.survey_quarantine
            WHERE batch_id = b.id
        ) q ON true
        LEFT JOIN LATERAL (
            SELECT COUNT(*) AS promoted_count
            FROM ts.survey_training
            WHERE batch_id = b.id
        ) t ON true
        WHERE b.user_id = :user_id
          AND b.deleted_at IS NULL
    )
    SELECT
        COUNT(*)::int AS batches_total,
        COALESCE(SUM(points_count), 0)::bigint AS points_total,
        COUNT(*) FILTER (WHERE promoted_count > 0)::int AS public_batches,
        COUNT(*) FILTER (WHERE promoted_count = 0 AND pending_count > 0)::int AS pending_batches,
        COUNT(*) FILTER (
            WHERE promoted_count = 0 AND pending_count = 0
        )::int AS private_batches
    FROM per_batch
    """
)


@dataclass(frozen=True, slots=True)
class UploadOverview:
    """Tổng quan dùng cho header mục "Tổng quan" trên trang sources."""

    batches_total: int
    points_total: int
    public_batches: int
    pending_batches: int
    private_batches: int


def create_upload_batch(
    conn: Connection,
    *,
    user_id: UUID,
    kind: UploadKind,
    filename: str,
    linked_source_id: UUID | None,
    uploaded_at: datetime | None = None,
    points_count: int = 0,
) -> tuple[UUID, datetime]:
    """Insert 1 row vào `me.upload_batches`. Trả (batch_id, uploaded_at).

    `uploaded_at=None` → để DB tự fill `now()` (sync click). CSV/JSON cũng
    có thể pass None vì UploadFile không kèm timestamp client-side. Thời
    điểm transaction-scoped đồng nhất với `ts.survey_quarantine.uploaded_at`
    DEFAULT now() của cùng connection.
    """
    row = conn.execute(
        _INSERT_BATCH,
        {
            "user_id": user_id,
            "kind": kind,
            "filename": filename,
            "linked_source_id": linked_source_id,
            "uploaded_at": uploaded_at,
            "points_count": points_count,
        },
    ).one()
    return row.id, row.uploaded_at


def set_batch_points_count(conn: Connection, *, batch_id: UUID, count: int) -> None:
    """Cập nhật cache count sau khi biết số rows thực insert (sau ON CONFLICT)."""
    conn.execute(_UPDATE_POINTS_COUNT, {"batch_id": batch_id, "count": count})


def list_upload_batches(
    conn: Connection,
    *,
    user_id: UUID,
    include_deleted: bool = True,
) -> list[UploadBatchSummary]:
    """List batches của 1 user, mới nhất trước.

    `include_deleted=True` cho mục Lịch sử upload (đầy đủ); False cho
    mục Quản lý dữ liệu (chỉ batch còn sống).
    """
    rows = conn.execute(
        _LIST_BATCHES,
        {"user_id": user_id, "include_deleted": include_deleted},
    ).all()
    return [
        UploadBatchSummary(
            id=row.id,
            kind=row.kind,
            filename=row.filename,
            linked_source_id=row.linked_source_id,
            uploaded_at=row.uploaded_at,
            points_count=int(row.points_count or 0),
            deleted_at=row.deleted_at,
            pending_count=int(row.pending_count or 0),
            promoted_count=int(row.promoted_count or 0),
            rejected_count=int(row.rejected_count or 0),
        )
        for row in rows
    ]


def submit_batch_for_review(
    conn: Connection,
    *,
    user_id: UUID,
    batch_id: UUID,
) -> int:
    """User bấm "Đóng góp" trên 1 batch.

    Decision 2026-06-11: bỏ TrustValidator cho luồng CSV/JSON/sync. Mọi
    row eligible của batch flip submitted_for_community=true rồi chuyển
    review_status='pending_review' để admin duyệt thủ công.

    Trả số rows được đẩy vào queue lần gọi này. Idempotent: rerun → 0
    (rows đã pending_review không match filter).
    """
    conn.execute(
        _MARK_SUBMITTED_FOR_BATCH,
        {"batch_id": batch_id, "user_id": user_id},
    )
    result = conn.execute(
        _QUEUE_PENDING_FOR_BATCH,
        {"batch_id": batch_id, "user_id": user_id},
    )
    queued = result.rowcount or 0
    if queued:
        logger.info(
            "upload_batch_queued_for_admin_review",
            user_id=str(user_id),
            batch_id=str(batch_id),
            queued=queued,
        )
    return queued


def delete_batch(
    conn: Connection,
    *,
    user_id: UUID,
    batch_id: UUID,
) -> bool:
    """Soft-delete batch + hard-purge quarantine; GIỮ training (community).

    Trả True nếu batch tồn tại + thuộc user + chưa bị xoá; False ngược lại
    (gọi lặp → False idempotent). UI mục Lịch sử upload vẫn hiện row với
    nhãn "Đã xoá". Training rows đã được admin duyệt vẫn ở bản đồ chung;
    "Của tôi" loại chúng qua filter `upload_batches.deleted_at IS NULL`.
    """
    deleted = conn.execute(
        _SOFT_DELETE_BATCH,
        {"batch_id": batch_id, "user_id": user_id},
    ).first()
    if deleted is None:
        return False
    conn.execute(_DELETE_QUARANTINE_FOR_BATCH, {"batch_id": batch_id})
    logger.info(
        "upload_batch_deleted",
        user_id=str(user_id),
        batch_id=str(batch_id),
    )
    return True


def fetch_upload_overview(conn: Connection, user_id: UUID) -> UploadOverview:
    """Overview counts cho card "Tổng quan" (chỉ batch chưa xoá)."""
    row = conn.execute(_OVERVIEW_COUNTS, {"user_id": user_id}).one()
    return UploadOverview(
        batches_total=int(row.batches_total or 0),
        points_total=int(row.points_total or 0),
        public_batches=int(row.public_batches or 0),
        pending_batches=int(row.pending_batches or 0),
        private_batches=int(row.private_batches or 0),
    )
