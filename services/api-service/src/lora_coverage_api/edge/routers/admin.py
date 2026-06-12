"""admin routes — quản lý user + global sync + stats.

Plan-auth-v1 §3.5 + §11 step 8. Mỏng: SQL trực tiếp ở router (plan §4
"đừng over-engineer"), không tách AdminService. Lý do:
  * SQL khá đơn giản (SELECT + UPDATE), không invariant business cần ẩn.
  * Caller duy nhất là 3 route admin — không có code khác trong app dùng
    cùng 1 query → tách module sẽ tăng surface area mà không giảm coupling.

Mọi route gắn dep `require_admin` → InvalidCredentialsError 401 (thiếu
token), AdminRequiredError 403 (token hợp lệ nhưng không phải admin).

Audit log (plan §3.5 + rule-design-observability §16): emit structlog event
KHÔNG kèm email/PII. Chỉ admin_id + target_user_id + before/after toggle.

Self-protection: PATCH /admin/users/{id} với id == admin.id → 400
(AdminSelfModificationError). Lý do trong errors.py.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import text

from ...application.identity import (
    AdminSelfModificationError,
    Mailer,
    MailerError,
    User,
    UserNotFoundError,
)
from ...application.sync import SyncResult, SyncService
from ...application.trust import TrustValidator
from ...application.trust.promotion import (
    PendingContribution,
    approve_pending_contribution,
    approve_pending_review_batch,
    get_pending_review,
    list_pending_review,
    list_pending_review_batches,
    list_pending_review_for_batch,
    reject_pending_contribution,
    reject_pending_review_batch,
)
from ...config import get_settings
from ..deps import (
    _engine,
    mailer_dep,
    require_admin,
    require_super_admin,
    sync_service,
    trust_validator,
)
from ..schemas import (
    AdminStatsResponse,
    BatchReviewRequest,
    BatchReviewResponse,
    ContributionRejectRequest,
    ContributionReviewResponse,
    CoverageRebuildEnqueueResponse,
    CoverageRebuildJobListResponse,
    CoverageRebuildJobResponse,
    MlRetrainEnqueueResponse,
    MlRetrainJobListResponse,
    MlRetrainJobResponse,
    PendingContributionListResponse,
    PendingContributionResponse,
    PendingReviewBatchListResponse,
    PendingReviewBatchResponse,
    SyncReportResponse,
    SyncResultResponse,
    TrainingBatchDeleteResponse,
    TrainingBatchItem,
    TrainingBatchListResponse,
    UserAdminResponse,
    UserListResponse,
    UserPatchRequest,
)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

logger = structlog.get_logger("lora_coverage_api.admin")


# ── SQL ──────────────────────────────────────────────────────────────────
# contribution_count = LEFT JOIN GROUP BY trong 1 query (Decision C). Tránh
# N+1 nếu list từng user rồi count riêng.
_LIST_USERS = text("""
    SELECT u.id, u.email, u.is_admin, u.disabled, u.created_at,
           COUNT(ls.id) AS contribution_count
    FROM auth.users u
    LEFT JOIN auth.linked_sources ls ON ls.user_id = u.id
    GROUP BY u.id
    ORDER BY u.created_at ASC
""")

# Update động với COALESCE để giữ nguyên field None. Trả row sau update để
# response phản ánh state mới + contribution_count tái dùng query list.
_PATCH_USER = text("""
    UPDATE auth.users
    SET is_admin = COALESCE(:is_admin, is_admin),
        disabled = COALESCE(:disabled, disabled)
    WHERE id = :id
    RETURNING id, email, is_admin, disabled, created_at
""")

_SELECT_USER_BEFORE = text("""
    SELECT is_admin, disabled FROM auth.users WHERE id = :id
""")

_COUNT_CONTRIBUTIONS = text("""
    SELECT COUNT(*) AS c FROM auth.linked_sources WHERE user_id = :id
""")

# DELETE auth.users — CASCADE auto-clean refresh_tokens, password_reset_tokens,
# email_verification_tokens, linked_sources. SET NULL preserves
# survey_training, survey_quarantine, devices, gateways, coverage_rebuild_jobs,
# ml.active_models.promoted_by (migration 0023) → contribution data + audit
# trail giu nguyen, chi mat link toi user.
_DELETE_USER = text("""
    DELETE FROM auth.users WHERE id = :id
""")

# Stats — 1 query/aggregate. Acceptable cho v1 (gateway/measurement bảng
# chưa quá lớn). Future: materialised view nếu cần.
_STATS_QUERIES = {
    "user_count": "SELECT COUNT(*) FROM auth.users",
    "active_user_count": "SELECT COUNT(*) FROM auth.users WHERE disabled = false",
    "linked_source_count": "SELECT COUNT(*) FROM auth.linked_sources",
    "active_source_count": ("SELECT COUNT(*) FROM auth.linked_sources WHERE status = 'active'"),
    "gateway_count": "SELECT COUNT(*) FROM geo.gateways",
    # ts.survey_training là hypertable training (đã accept) — quarantine
    # KHÔNG count vì không phải đóng góp confirm.
    "measurement_count": "SELECT COUNT(*) FROM ts.survey_training",
    # Migration 0018: admin queue size — rows passed auto-validate, đang chờ
    # admin duyệt thủ công.
    "pending_review_count": (
        "SELECT COUNT(*) FROM ts.survey_quarantine WHERE review_status = 'pending_review'"
    ),
}


# ── Helpers ──────────────────────────────────────────────────────────────


def _sync_to_response(r: SyncResult) -> SyncResultResponse:
    return SyncResultResponse(
        linked_source_id=r.linked_source_id,
        gateways_inserted=r.gateways_inserted,
        gateways_updated=r.gateways_updated,
        measurements_inserted=r.measurements_inserted,
        measurements_updated=r.measurements_updated,
        devices_inserted=r.devices_inserted,
        devices_updated=r.devices_updated,
        last_sync_at=r.last_sync_at,
        error=r.error,
    )


# ── Routes ───────────────────────────────────────────────────────────────


@router.get("/users", response_model=UserListResponse)
def list_users(
    admin: Annotated[User, Depends(require_admin)],
) -> UserListResponse:
    super_admin_email = get_settings().super_admin_email.lower()
    caller_is_super = admin.email.lower() == super_admin_email
    with _engine().begin() as conn:
        rows = conn.execute(_LIST_USERS).all()
    items: list[UserAdminResponse] = []
    for r in rows:
        row_is_super = (r.email or "").lower() == super_admin_email
        # Caller admin thường KHÔNG được thấy super admin trong list.
        if row_is_super and not caller_is_super:
            continue
        items.append(
            UserAdminResponse(
                id=r.id,
                email=r.email,
                is_admin=r.is_admin,
                is_super_admin=row_is_super,
                disabled=r.disabled,
                created_at=r.created_at,
                contribution_count=int(r.contribution_count),
            )
        )
    return UserListResponse(items=items, total=len(items))


@router.patch("/users/{user_id}", response_model=UserAdminResponse)
def patch_user(
    user_id: UUID,
    body: UserPatchRequest,
    admin: Annotated[User, Depends(require_super_admin)],
) -> UserAdminResponse:
    if user_id == admin.id:
        # Self-protection: chặn cả flip is_admin và flip disabled. Lý do
        # trong AdminSelfModificationError docstring.
        raise AdminSelfModificationError("Admin không thể tự sửa is_admin/disabled của chính mình")

    with _engine().begin() as conn:
        before = conn.execute(_SELECT_USER_BEFORE, {"id": user_id}).one_or_none()
        if before is None:
            raise UserNotFoundError(f"User {user_id} không tồn tại")

        row = conn.execute(
            _PATCH_USER,
            {"id": user_id, "is_admin": body.is_admin, "disabled": body.disabled},
        ).one()
        contribution_count = int(conn.execute(_COUNT_CONTRIBUTIONS, {"id": user_id}).scalar_one())

    # Audit log — KHÔNG kèm email (PII). Chỉ admin_id + target_user_id +
    # before/after cho field thay đổi.
    log_payload: dict[str, object] = {
        "admin_id": str(admin.id),
        "target_user_id": str(user_id),
    }
    if body.is_admin is not None:
        log_payload["is_admin_before"] = before.is_admin
        log_payload["is_admin_after"] = body.is_admin
    if body.disabled is not None:
        log_payload["disabled_before"] = before.disabled
        log_payload["disabled_after"] = body.disabled
    logger.info("admin_user_patched", **log_payload)

    super_admin_email = get_settings().super_admin_email.lower()
    return UserAdminResponse(
        id=row.id,
        email=row.email,
        is_admin=row.is_admin,
        is_super_admin=(row.email or "").lower() == super_admin_email,
        disabled=row.disabled,
        created_at=row.created_at,
        contribution_count=contribution_count,
    )


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: UUID,
    admin: Annotated[User, Depends(require_super_admin)],
) -> Response:
    """Xoa hard 1 user khoi DB. CHI super admin co quyen — destructive.

    Self-protection: super admin khong xoa duoc chinh minh (tranh khoa cua).
    CASCADE FK xu ly tokens + linked_sources; SET NULL FK giu lai contribution
    data (survey rows, gateways, devices) voi contributor_user_id = NULL.
    """
    if user_id == admin.id:
        raise AdminSelfModificationError("Admin khong the xoa chinh minh")

    with _engine().begin() as conn:
        before = conn.execute(_SELECT_USER_BEFORE, {"id": user_id}).one_or_none()
        if before is None:
            raise UserNotFoundError(f"User {user_id} khong ton tai")
        conn.execute(_DELETE_USER, {"id": user_id})

    logger.info(
        "admin_user_deleted",
        admin_id=str(admin.id),
        target_user_id=str(user_id),
        was_admin=before.is_admin,
        was_disabled=before.disabled,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sync", response_model=SyncReportResponse)
def admin_sync_all(
    admin: Annotated[User, Depends(require_admin)],
    sync: Annotated[SyncService, Depends(sync_service)],
) -> SyncReportResponse:
    """Trigger global sync mọi linked_source eligible (plan §3.4).

    v1 limitation: synchronous — caller chờ tới khi mọi source xong. Có thể
    timeout nếu nhiều source chậm. Plan §10 ghi nhận: production scale → v2
    chuyển sang background queue. Step 8 không thêm queue.

    Audit + observability: 1 structlog event với count + duration. Chi tiết
    per-source đã log ở SyncService (source_sync_completed/_failed).
    """
    started = time.monotonic()
    with _engine().begin() as conn:
        report = sync.sync_all_eligible(conn)
    duration_ms = int((time.monotonic() - started) * 1000)

    logger.info(
        "admin_global_sync_triggered",
        admin_id=str(admin.id),
        eligible_count=len(report.items),
        successes=report.successes,
        failures=report.failures,
        duration_ms=duration_ms,
    )

    return SyncReportResponse(
        items=[_sync_to_response(r) for r in report.items],
        total=len(report.items),
        successes=report.successes,
        failures=report.failures,
    )


@router.get("/stats", response_model=AdminStatsResponse)
def admin_stats(
    admin: Annotated[User, Depends(require_admin)],
) -> AdminStatsResponse:
    with _engine().begin() as conn:
        values = {
            key: int(conn.execute(text(sql)).scalar_one()) for key, sql in _STATS_QUERIES.items()
        }
    return AdminStatsResponse(**values)


# ── Manual review queue (migration 0018) ────────────────────────────────


def _pending_to_response(p: PendingContribution) -> PendingContributionResponse:
    return PendingContributionResponse(
        id=p.id,
        timestamp=p.timestamp,
        submitted_at=p.submitted_at,
        latitude=p.latitude,
        longitude=p.longitude,
        rssi_dbm=p.rssi_dbm,
        snr_db=p.snr_db,
        spreading_factor=p.spreading_factor,
        frequency_mhz=p.frequency_mhz,
        source_type=p.source_type,
        contributor_user_id=p.contributor_user_id,
        contributor_email=p.contributor_email,
        serving_gateway_id=p.serving_gateway_id,
        gateway_code=p.gateway_code,
        linked_source_id=p.linked_source_id,
    )


@router.get("/contributions/pending", response_model=PendingContributionListResponse)
def list_pending_contributions(
    admin: Annotated[User, Depends(require_admin)],
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> PendingContributionListResponse:
    """Liệt kê đóng góp đang chờ admin duyệt (đã pass auto-validate)."""
    with _engine().begin() as conn:
        items, total = list_pending_review(conn, limit=limit, offset=offset)
    return PendingContributionListResponse(
        items=[_pending_to_response(p) for p in items],
        total=total,
    )


# ── Batch (file-level) review ───────────────────────────────────────────
# Group quarantine rows theo (uploader_id, uploaded_at) — 1 batch = 1 file
# user upload. Admin xét cả file thay vì từng row (UX: file 100 điểm cùng
# user upload cùng thời điểm thường có cùng độ tin cậy).
#
# Per-row reject vẫn giữ (endpoint `/contributions/{id}/reject` bên dưới) để
# admin loại row xấu trước rồi approve phần còn lại.
#
# ROUTE ORDER MATTERS: batch routes (`/contributions/batches/...`) phải đăng
# ký TRƯỚC per-id routes (`/contributions/{contribution_id}/...`), nếu không
# FastAPI sẽ match path param trước và parse `"batches"` thành UUID → 422.


@router.get(
    "/contributions/batches",
    response_model=PendingReviewBatchListResponse,
)
def list_pending_batches(
    admin: Annotated[User, Depends(require_admin)],
) -> PendingReviewBatchListResponse:
    """List các file CSV (uploader + uploaded_at) còn ≥1 row chờ duyệt."""
    with _engine().begin() as conn:
        items = list_pending_review_batches(conn)
    return PendingReviewBatchListResponse(
        items=[
            PendingReviewBatchResponse(
                uploader_id=b.uploader_id,
                uploader_email=b.uploader_email,
                uploaded_at=b.uploaded_at,
                pending_review_count=b.pending_review_count,
                total_count=b.total_count,
                earliest_timestamp=b.earliest_timestamp,
                latest_timestamp=b.latest_timestamp,
            )
            for b in items
        ]
    )


@router.get(
    "/contributions/batches/rows",
    response_model=PendingContributionListResponse,
)
def list_batch_rows(
    admin: Annotated[User, Depends(require_admin)],
    uploader_id: UUID,
    uploaded_at: datetime,
) -> PendingContributionListResponse:
    """Detail rows pending_review của 1 batch — admin drill-in xem trước duyệt.

    `uploaded_at` truyền ISO 8601 datetime (vd `2026-05-25T08:30:00+00:00`).
    """
    with _engine().begin() as conn:
        items = list_pending_review_for_batch(
            conn, uploader_id=uploader_id, uploaded_at=uploaded_at
        )
    return PendingContributionListResponse(
        items=[_pending_to_response(p) for p in items],
        total=len(items),
    )


@router.post(
    "/contributions/batches/approve",
    response_model=BatchReviewResponse,
)
def approve_batch(
    body: BatchReviewRequest,
    admin: Annotated[User, Depends(require_admin)],
    trust: Annotated[TrustValidator, Depends(trust_validator)],
    mailer: Annotated[Mailer, Depends(mailer_dep)],
) -> BatchReviewResponse:
    """Duyệt cả file: approve mọi pending_review row của batch trong 1 txn.

    Sau approve: gửi 1 email cảm ơn tổng kết (Option B — 1 email/batch,
    không phải 1 email/row, tránh spam khi batch lớn).
    """
    with _engine().begin() as conn:
        approved = approve_pending_review_batch(
            conn,
            trust,
            uploader_id=body.uploader_id,
            uploaded_at=body.uploaded_at,
            reviewer_id=admin.id,
        )

    if not approved:
        raise HTTPException(
            status_code=404,
            detail="Không có row nào chờ duyệt trong batch này (đã xử lý hoặc batch không tồn tại).",
        )

    # Email gộp — gửi tới contributor_email của row đầu (tất cả rows trong
    # batch cùng 1 uploader → cùng email). Skip nếu email null.
    contributor_email = approved[0].contributor_email
    if contributor_email:
        timestamps = [p.timestamp for p in approved]
        try:
            mailer.send_contribution_batch_approved(
                contributor_email,
                uploaded_at=body.uploaded_at,
                approved_count=len(approved),
                earliest_timestamp=min(timestamps),
                latest_timestamp=max(timestamps),
            )
        except MailerError as exc:
            logger.warning(
                "contribution_batch_thanks_email_failed",
                uploader_id=str(body.uploader_id),
                uploaded_at=body.uploaded_at.isoformat(),
                approved_count=len(approved),
                error=str(exc),
            )

    logger.info(
        "admin_batch_approved",
        uploader_id=str(body.uploader_id),
        uploaded_at=body.uploaded_at.isoformat(),
        reviewer_id=str(admin.id),
        approved_count=len(approved),
    )

    return BatchReviewResponse(
        uploader_id=body.uploader_id,
        uploaded_at=body.uploaded_at,
        approved_count=len(approved),
    )


@router.post(
    "/contributions/batches/reject",
    response_model=BatchReviewResponse,
)
def reject_batch(
    body: BatchReviewRequest,
    admin: Annotated[User, Depends(require_admin)],
    trust: Annotated[TrustValidator, Depends(trust_validator)],
    mailer: Annotated[Mailer, Depends(mailer_dep)],
) -> BatchReviewResponse:
    """Từ chối cả file: reject mọi pending_review row của batch.

    Sau reject: gửi 1 email thông báo tổng kết cho user kèm lý do admin nhập
    (note). Per-row reject ở dưới KHÔNG gửi email (drill-in escape hatch —
    admin có thể loại nhiều row noise sẽ spam inbox).
    """
    with _engine().begin() as conn:
        rejected = reject_pending_review_batch(
            conn,
            trust,
            uploader_id=body.uploader_id,
            uploaded_at=body.uploaded_at,
            reviewer_id=admin.id,
            note=body.note,
        )

    if not rejected:
        raise HTTPException(
            status_code=404,
            detail="Không có row nào chờ duyệt trong batch này (đã xử lý hoặc batch không tồn tại).",
        )

    # Email gộp — 1 email/batch tới contributor (mọi row trong batch cùng
    # uploader → cùng email). Skip nếu email null. Fire-and-forget: SMTP fail
    # log warning nhưng KHÔNG fail response (rows đã reject trong DB rồi).
    contributor_email = rejected[0].contributor_email
    if contributor_email:
        timestamps = [p.timestamp for p in rejected]
        try:
            mailer.send_contribution_batch_rejected(
                contributor_email,
                uploaded_at=body.uploaded_at,
                rejected_count=len(rejected),
                earliest_timestamp=min(timestamps),
                latest_timestamp=max(timestamps),
                note=body.note,
            )
        except MailerError as exc:
            logger.warning(
                "contribution_batch_reject_email_failed",
                uploader_id=str(body.uploader_id),
                uploaded_at=body.uploaded_at.isoformat(),
                rejected_count=len(rejected),
                error=str(exc),
            )

    logger.info(
        "admin_batch_rejected",
        uploader_id=str(body.uploader_id),
        uploaded_at=body.uploaded_at.isoformat(),
        reviewer_id=str(admin.id),
        rejected_count=len(rejected),
    )

    return BatchReviewResponse(
        uploader_id=body.uploader_id,
        uploaded_at=body.uploaded_at,
        rejected_count=len(rejected),
    )


# ── Per-row review ──────────────────────────────────────────────────────
# Drill-in escape hatch: admin loại từng row xấu trước, rồi approve cả batch
# phần còn lại. Phải đăng ký SAU batch routes (xem note ở trên).


@router.post(
    "/contributions/{contribution_id}/approve",
    response_model=ContributionReviewResponse,
)
def approve_contribution(
    contribution_id: UUID,
    admin: Annotated[User, Depends(require_admin)],
    trust: Annotated[TrustValidator, Depends(trust_validator)],
    mailer: Annotated[Mailer, Depends(mailer_dep)],
) -> ContributionReviewResponse:
    """Approve: row đẩy sang survey_training, hiển thị trên bản đồ cộng đồng."""
    with _engine().begin() as conn:
        # Detail PHẢI lấy trước approve — sau khi approve, review_status đổi
        # sang 'approved' nên _GET_PENDING_BY_ID (filter pending_review) sẽ miss.
        detail = get_pending_review(conn, contribution_id)
        ok = approve_pending_contribution(conn, trust, qid=contribution_id, reviewer_id=admin.id)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy đóng góp đang chờ duyệt (đã xử lý hoặc không tồn tại).",
        )

    # Thanks email — fire-and-forget. SMTP fail KHÔNG fail approve (row đã
    # vào training, response 200 vẫn đúng). Cũng skip nếu contributor_email
    # null (vd row csv không gắn user, hoặc user bị xoá).
    if detail is not None and detail.contributor_email:
        try:
            mailer.send_contribution_approved(
                detail.contributor_email,
                point_timestamp=detail.timestamp,
                latitude=detail.latitude,
                longitude=detail.longitude,
                gateway_code=detail.gateway_code,
                rssi_dbm=detail.rssi_dbm,
            )
        except MailerError as exc:
            logger.warning(
                "contribution_thanks_email_failed",
                contribution_id=str(contribution_id),
                contributor_email=detail.contributor_email,
                error=str(exc),
            )

    return ContributionReviewResponse(id=contribution_id, review_status="approved")


# ── Coverage map rebuild (admin "Rebuild bản đồ ước lượng") ─────────────
# Producer: enqueue Celery task, INSERT row vào audit.coverage_rebuild_jobs.
# Worker: lora-wan-celery xử lý task incremental (xem tasks/rebuild_coverage.py).
# Frontend poll `GET /admin/coverage/rebuild/{job_id}` mỗi 5s tới khi
# status ∈ {succeeded, failed}.


_INSERT_REBUILD_JOB = text("""
    INSERT INTO audit.coverage_rebuild_jobs (status, triggered_by)
    VALUES ('queued', :uid)
    RETURNING id
""")

_SELECT_REBUILD_JOB = text("""
    SELECT id, status, triggered_by, triggered_at, started_at, finished_at,
           gateways_total, gateways_rebuilt, gateways_skipped,
           per_gw_log, error_text, celery_task_id
    FROM audit.coverage_rebuild_jobs
    WHERE id = :id
""")

_LIST_REBUILD_JOBS = text("""
    SELECT id, status, triggered_by, triggered_at, started_at, finished_at,
           gateways_total, gateways_rebuilt, gateways_skipped,
           per_gw_log, error_text, celery_task_id
    FROM audit.coverage_rebuild_jobs
    ORDER BY triggered_at DESC
""")


def _row_to_rebuild_response(r: Any) -> CoverageRebuildJobResponse:
    return CoverageRebuildJobResponse(
        id=r.id,
        status=r.status,
        triggered_by=r.triggered_by,
        triggered_at=r.triggered_at,
        started_at=r.started_at,
        finished_at=r.finished_at,
        gateways_total=r.gateways_total,
        gateways_rebuilt=int(r.gateways_rebuilt),
        gateways_skipped=int(r.gateways_skipped),
        per_gw_log=dict(r.per_gw_log or {}),
        error_text=r.error_text,
        celery_task_id=r.celery_task_id,
    )


@router.post(
    "/coverage/rebuild",
    response_model=CoverageRebuildEnqueueResponse,
    status_code=202,
)
def enqueue_coverage_rebuild(
    admin: Annotated[User, Depends(require_admin)],
) -> CoverageRebuildEnqueueResponse:
    """Tạo job + enqueue task rebuild composite/per-gw RSSI heatmap.

    Idempotency: KHÔNG dedupe — admin có thể bấm liên tục (worker concurrency=1
    nên job mới chờ job cũ xong; nếu không có data mới, mỗi job ~vài giây skip).
    """
    # Import trễ — celery_app khởi tạo Settings + redis client tốn ~50ms,
    # cộng với việc Celery broker (Valkey) phải sẵn sàng. Lazy giữ FastAPI
    # startup nhẹ.
    from ...tasks.rebuild_coverage import rebuild_coverage_map

    with _engine().begin() as conn:
        job_id = conn.execute(_INSERT_REBUILD_JOB, {"uid": admin.id}).scalar_one()

    rebuild_coverage_map.delay(str(job_id))
    logger.info(
        "admin_coverage_rebuild_enqueued",
        admin_id=str(admin.id),
        job_id=str(job_id),
    )
    return CoverageRebuildEnqueueResponse(job_id=job_id, status="queued")


@router.get(
    "/coverage/rebuild/latest",
    response_model=CoverageRebuildJobListResponse,
)
def list_recent_coverage_rebuilds(
    admin: Annotated[User, Depends(require_admin)],
) -> CoverageRebuildJobListResponse:
    """Toàn bộ lịch sử rebuild bản đồ ước lượng (mới → cũ)."""
    with _engine().begin() as conn:
        rows = conn.execute(_LIST_REBUILD_JOBS).all()
    return CoverageRebuildJobListResponse(items=[_row_to_rebuild_response(r) for r in rows])


@router.get(
    "/coverage/rebuild/{job_id}",
    response_model=CoverageRebuildJobResponse,
)
def get_coverage_rebuild(
    job_id: UUID,
    admin: Annotated[User, Depends(require_admin)],
) -> CoverageRebuildJobResponse:
    """Poll status 1 job — frontend gọi mỗi 5s tới khi succeeded/failed."""
    with _engine().begin() as conn:
        row = conn.execute(_SELECT_REBUILD_JOB, {"id": job_id}).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} không tồn tại.")
    return _row_to_rebuild_response(row)


@router.post(
    "/contributions/{contribution_id}/reject",
    response_model=ContributionReviewResponse,
)
def reject_contribution(
    contribution_id: UUID,
    body: ContributionRejectRequest,
    admin: Annotated[User, Depends(require_admin)],
    trust: Annotated[TrustValidator, Depends(trust_validator)],
) -> ContributionReviewResponse:
    """Reject: row giữ trong quarantine, không bao giờ lên map cộng đồng."""
    with _engine().begin() as conn:
        ok = reject_pending_contribution(
            conn,
            trust,
            qid=contribution_id,
            reviewer_id=admin.id,
            note=body.note,
        )
    if not ok:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy đóng góp đang chờ duyệt (đã xử lý hoặc không tồn tại).",
        )
    return ContributionReviewResponse(id=contribution_id, review_status="rejected")


# ── Admin trace-back: data đã duyệt vào ts.survey_training ──────────────
# Mục đích: admin có thể audit + xoá batch đã được approve trước đó (vd phát
# hiện data sai lệch sau khi đã promote). Sau khi xoá → admin trigger rebuild
# bản đồ + retrain ML qua endpoint riêng.
#
# Chỉ list batch có batch_id (mig 0024+). Legacy training rows (~13k row trước
# 2026-06-11) không trace được — admin biết qua hint UI; không cần backfill
# vì data đó là seed/sync history, không phải user contribution.

_LIST_TRAINING_BATCHES = text("""
    SELECT
        t.batch_id,
        b.user_id AS uploader_id,
        u.email AS uploader_email,
        b.kind,
        b.filename,
        b.uploaded_at,
        COUNT(*)::int AS promoted_count,
        MAX(t.promoted_at) AS latest_approved_at,
        b.deleted_at AS batch_deleted_at
    FROM ts.survey_training t
    LEFT JOIN me.upload_batches b ON b.id = t.batch_id
    LEFT JOIN auth.users u ON u.id = b.user_id
    WHERE t.batch_id IS NOT NULL
    GROUP BY t.batch_id, b.user_id, u.email, b.kind, b.filename,
             b.uploaded_at, b.deleted_at
    ORDER BY latest_approved_at DESC
""")

# Xoá hết training rows của 1 batch. KHÔNG đụng quarantine — quarantine có thể
# vẫn còn rows pending/approved của batch đó; admin xoá training = "rút lại
# quyết định duyệt", không phải xoá toàn bộ batch (user side delete đã có
# riêng và mạnh hơn — purge cả 2 table).
_DELETE_TRAINING_FOR_BATCH = text("""
    DELETE FROM ts.survey_training
    WHERE batch_id = :batch_id
""")


@router.get(
    "/training/batches",
    response_model=TrainingBatchListResponse,
    summary="Danh sách batch đã duyệt vào ts.survey_training (admin audit)",
)
def list_training_batches(
    admin: Annotated[User, Depends(require_admin)],
) -> TrainingBatchListResponse:
    """Trace-back các batch đã được admin approve. Sort mới-nhất trước theo
    `latest_approved_at` (max promoted_at trong batch).

    Note: chỉ trả batch có `batch_id` không NULL trong training. Row legacy
    từ trước migration 0024 (~13k row) không xuất hiện ở đây.
    """
    with _engine().begin() as conn:
        rows = conn.execute(_LIST_TRAINING_BATCHES).all()
    return TrainingBatchListResponse(
        items=[
            TrainingBatchItem(
                batch_id=r.batch_id,
                uploader_id=r.uploader_id,
                uploader_email=r.uploader_email,
                kind=r.kind,
                filename=r.filename,
                uploaded_at=r.uploaded_at,
                promoted_count=int(r.promoted_count),
                latest_approved_at=r.latest_approved_at,
                batch_deleted_at=r.batch_deleted_at,
            )
            for r in rows
        ]
    )


@router.delete(
    "/training/batches/{batch_id}",
    response_model=TrainingBatchDeleteResponse,
    summary="Xoá hết training rows của 1 batch (admin rút lại duyệt)",
    responses={
        404: {"description": "Batch không có row nào trong training"},
    },
)
def delete_training_batch(
    batch_id: UUID,
    admin: Annotated[User, Depends(require_admin)],
) -> TrainingBatchDeleteResponse:
    """Hard-delete `ts.survey_training` của batch. Quarantine giữ nguyên
    (user vẫn thấy batch trong "Lịch sử upload", nhưng status hiển thị về
    "private" do không còn promoted row).

    Sau khi xoá → admin tự bấm "Rebuild + Retrain" để propagate ảnh hưởng
    sang bản đồ ước lượng + ML model.
    """
    with _engine().begin() as conn:
        result = conn.execute(_DELETE_TRAINING_FOR_BATCH, {"batch_id": batch_id})
    deleted = result.rowcount or 0
    if deleted == 0:
        raise HTTPException(
            status_code=404,
            detail=f"Batch {batch_id} không có row nào trong training (đã bị xoá hoặc chưa bao giờ promote).",
        )
    logger.info(
        "admin_training_batch_deleted",
        admin_id=str(admin.id),
        batch_id=str(batch_id),
        deleted_count=deleted,
    )
    return TrainingBatchDeleteResponse(batch_id=batch_id, deleted_count=deleted)


# ── ML retrain (admin "Retrain mô hình học máy") ────────────────────────
# Mirror pattern coverage rebuild — producer enqueue Celery, worker chạy
# scripts/train_extra_trees.py atomic-swap + ghi metrics.json. Frontend poll
# `GET /admin/ml/retrain/{job_id}` mỗi 5s.

_INSERT_RETRAIN_JOB = text("""
    INSERT INTO audit.ml_retrain_jobs (status, triggered_by)
    VALUES ('queued', :uid)
    RETURNING id
""")

_SELECT_RETRAIN_JOB = text("""
    SELECT id, status, triggered_by, triggered_at, started_at, finished_at,
           rows_trained, artifact_path, metrics, error_text, celery_task_id
    FROM audit.ml_retrain_jobs
    WHERE id = :id
""")

_LIST_RETRAIN_JOBS = text("""
    SELECT id, status, triggered_by, triggered_at, started_at, finished_at,
           rows_trained, artifact_path, metrics, error_text, celery_task_id
    FROM audit.ml_retrain_jobs
    ORDER BY triggered_at DESC
    LIMIT 5
""")


def _row_to_retrain_response(r: Any) -> MlRetrainJobResponse:
    return MlRetrainJobResponse(
        id=r.id,
        status=r.status,
        triggered_by=r.triggered_by,
        triggered_at=r.triggered_at,
        started_at=r.started_at,
        finished_at=r.finished_at,
        rows_trained=r.rows_trained,
        artifact_path=r.artifact_path,
        metrics=dict(r.metrics or {}),
        error_text=r.error_text,
        celery_task_id=r.celery_task_id,
    )


@router.post(
    "/ml/retrain",
    response_model=MlRetrainEnqueueResponse,
    status_code=202,
)
def enqueue_ml_retrain(
    admin: Annotated[User, Depends(require_admin)],
) -> MlRetrainEnqueueResponse:
    """Tạo job + enqueue task retrain Extra Trees ML model.

    Idempotency: KHÔNG dedupe — worker concurrency=1 nên job mới chờ job cũ
    xong. Train chạy ~vài phút (Extra Trees 1500 trees trên ~10k row).
    """
    from ...tasks.retrain_ml import retrain_ml_model

    with _engine().begin() as conn:
        job_id = conn.execute(_INSERT_RETRAIN_JOB, {"uid": admin.id}).scalar_one()

    retrain_ml_model.delay(str(job_id))
    logger.info(
        "admin_ml_retrain_enqueued",
        admin_id=str(admin.id),
        job_id=str(job_id),
    )
    return MlRetrainEnqueueResponse(job_id=job_id, status="queued")


@router.get(
    "/ml/retrain/latest",
    response_model=MlRetrainJobListResponse,
)
def list_recent_ml_retrains(
    admin: Annotated[User, Depends(require_admin)],
) -> MlRetrainJobListResponse:
    """5 lần retrain gần nhất — frontend hiển thị lịch sử."""
    with _engine().begin() as conn:
        rows = conn.execute(_LIST_RETRAIN_JOBS).all()
    return MlRetrainJobListResponse(items=[_row_to_retrain_response(r) for r in rows])


@router.get(
    "/ml/retrain/{job_id}",
    response_model=MlRetrainJobResponse,
)
def get_ml_retrain(
    job_id: UUID,
    admin: Annotated[User, Depends(require_admin)],
) -> MlRetrainJobResponse:
    """Poll status 1 job — frontend gọi mỗi 5s tới khi succeeded/failed."""
    with _engine().begin() as conn:
        row = conn.execute(_SELECT_RETRAIN_JOB, {"id": job_id}).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} không tồn tại.")
    return _row_to_retrain_response(row)
