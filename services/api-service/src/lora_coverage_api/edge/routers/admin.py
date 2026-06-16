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
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
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
    BatchGateway,
    PendingContribution,
    approve_pending_review_batch,
    approve_points_only_for_batch,
    cascade_reject_deferred_for_gateway,
    list_known_gateways_for_batch,
    list_pending_gateways_for_batch,
    list_pending_review,
    list_pending_review_batches,
    list_quarantine_for_batch_display,
    promote_deferred_for_gateway,
    reject_quarantine_for_batch,
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
    BatchGatewayResponse,
    BatchReviewRequest,
    BatchReviewResponse,
    BatchRowsResponse,
    CoverageRebuildEnqueueResponse,
    CoverageRebuildJobListResponse,
    CoverageRebuildJobResponse,
    DataFreshnessResponse,
    MlRetrainEnqueueResponse,
    MlRetrainJobListResponse,
    MlRetrainJobResponse,
    PendingContributionListResponse,
    PendingContributionResponse,
    PendingGatewayListResponse,
    PendingGatewayResponse,
    PendingReviewBatchListResponse,
    PendingReviewBatchResponse,
    SyncReportResponse,
    SyncResultResponse,
    TimeseriesPoint,
    TimeseriesResponse,
    TopGatewayItem,
    TopGatewayResponse,
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
    # "User online" = distinct user co last_seen_at trong 5 phut gan nhat.
    # current_user() dep touch last_seen_at (throttle 30s) tren moi authenticated
    # request — count theo user, khong theo session (1 user 2 tab = 1).
    "online_user_count": (
        "SELECT COUNT(*) FROM auth.users "
        "WHERE last_seen_at > now() - interval '5 minutes' "
        "AND is_admin = false"
    ),
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
        gateways_quarantined=r.gateways_quarantined,
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


@router.get(
    "/contributions/batches",
    response_model=PendingReviewBatchListResponse,
)
def list_pending_batches(
    admin: Annotated[User, Depends(require_admin)],
) -> PendingReviewBatchListResponse:
    """List các batch (uploader + uploaded_at) còn ≥1 row chờ duyệt HOẶC ≥1
    gateway pending. `new_gateway_count` count gateway pending của batch."""
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
                new_gateway_count=b.new_gateway_count,
            )
            for b in items
        ]
    )


def _batch_gateway_to_response(g: BatchGateway) -> BatchGatewayResponse:
    return BatchGatewayResponse(
        id=g.id,
        code=g.code,
        name=g.name,
        latitude=g.latitude,
        longitude=g.longitude,
        frequency_mhz=g.frequency_mhz,
        source_type=g.source_type,
        is_new=g.is_new,
    )


@router.get(
    "/contributions/batches/rows",
    response_model=BatchRowsResponse,
)
def list_batch_rows(
    admin: Annotated[User, Depends(require_admin)],
    uploader_id: UUID,
    uploaded_at: datetime,
) -> BatchRowsResponse:
    """Map preview của 1 batch: điểm đo (pending_review + pending_gateway) +
    gateway (cả pending lẫn đã promoted mà batch tham chiếu).

    `uploaded_at` truyền ISO 8601 datetime (vd `2026-05-25T08:30:00+00:00`).
    """
    with _engine().begin() as conn:
        points = list_quarantine_for_batch_display(
            conn, uploader_id=uploader_id, uploaded_at=uploaded_at
        )
        pending_gw = list_pending_gateways_for_batch(
            conn, uploader_id=uploader_id, uploaded_at=uploaded_at
        )
        known_gw = list_known_gateways_for_batch(
            conn, uploader_id=uploader_id, uploaded_at=uploaded_at
        )
    return BatchRowsResponse(
        points=[_pending_to_response(p) for p in points],
        gateways=[_batch_gateway_to_response(g) for g in pending_gw + known_gw],
        total_points=len(points),
        new_gateway_count=len(pending_gw),
    )


def _invalidate_rebuild_for_gateways(conn: Any, gateway_ids: Iterable[UUID]) -> None:
    """Đặt last_rebuild_at = NULL cho các trạm bị ảnh hưởng bởi mutate điểm đo.

    Lý do: rebuild_coverage_map dùng `MAX(timestamp) > last_rebuild_at` để
    skip gateway "không có data mới". Logic giả định data chỉ tăng theo thời
    gian — sai ở 2 chỗ:
      * Admin xoá batch → MAX(timestamp) không tăng (có khi giảm) → rebuild
        SKIP dù điểm đo đã đổi.
      * Admin duyệt batch chứa timestamp historical (upload CSV survey cũ) →
        MAX có thể không vượt qua last_rebuild_at → cũng SKIP.

    Đặt NULL → rebuild query ép coi như "chưa từng dựng" (vế
    `last_rebuild_at IS NULL` ở rebuild_coverage.py:87) → lần Rebuild kế tiếp
    luôn trigger. Sau khi dựng xong, task tự ghi lại `last_rebuild_at = now()`.

    Gọi trong cùng transaction với mutate để atomic — nếu mutate rollback thì
    invalidate cũng rollback.
    """
    ids = [gid for gid in gateway_ids if gid is not None]
    if not ids:
        return
    conn.execute(
        text("UPDATE geo.gateways SET last_rebuild_at = NULL WHERE id = ANY(:ids)"),
        {"ids": ids},
    )


def _approve_batch_gateways(
    conn: Any,
    trust: TrustValidator,
    *,
    uploader_id: UUID,
    uploaded_at: datetime,
    reviewer_id: UUID,
) -> tuple[list[UUID], int]:
    """Promote mọi gateway pending của batch → geo.gateways + backfill + auto-
    promote deferred rows. Trả (gw_ids_đã_promote, tổng_deferred_promoted)."""
    pending = list_pending_gateways_for_batch(
        conn, uploader_id=uploader_id, uploaded_at=uploaded_at
    )
    gw_ids: list[UUID] = []
    total_deferred = 0
    for g in pending:
        gw_id, _backfilled, deferred = _promote_one_gateway_quarantine(
            conn, trust, quarantine_id=g.id, code=g.code, reviewer_id=reviewer_id
        )
        gw_ids.append(gw_id)
        total_deferred += deferred
    return gw_ids, total_deferred


def _reject_batch_gateways(
    conn: Any,
    trust: TrustValidator,
    *,
    uploader_id: UUID,
    uploaded_at: datetime,
    reviewer_id: UUID,
    note: str | None,
) -> int:
    """Reject mọi gateway pending của batch + cascade reject pending_gateway
    rows cùng EUI. Trả số gateway bị reject."""
    pending = list_pending_gateways_for_batch(
        conn, uploader_id=uploader_id, uploaded_at=uploaded_at
    )
    for g in pending:
        conn.execute(
            _MARK_GATEWAY_REJECTED,
            {"qid": g.id, "reviewer_id": reviewer_id, "note": note},
        )
        cascade_reject_deferred_for_gateway(
            conn, trust, gateway_code=g.code, reviewer_id=reviewer_id, note=note
        )
    return len(pending)


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
    """Duyệt batch theo 3 mode:
    * "all" — duyệt cả file: điểm pending_review → training, gateway pending →
      geo.gateways, deferred rows cùng EUI → training.
    * "points_only" — duyệt điểm đo (không duyệt gateway): điểm trỏ gateway cũ
      → training; điểm trỏ gateway mới → defer (pending_gateway). Gateway
      pending giữ nguyên ở queue chờ admin click duyệt sau.
    * "gateways_only" — duyệt gateway (không duyệt điểm đo): mọi gateway pending
      → geo.gateways; mọi điểm đo của batch → rejected.

    Email gộp gửi cho contributor cuối mỗi mode.
    """
    approved: list[PendingContribution] = []
    rejected: list[PendingContribution] = []
    deferred_count = 0
    gw_approved_count = 0
    gw_rejected_count = 0

    with _engine().begin() as conn:
        if body.mode == "all":
            approved = approve_pending_review_batch(
                conn,
                trust,
                uploader_id=body.uploader_id,
                uploaded_at=body.uploaded_at,
                reviewer_id=admin.id,
            )
            gw_ids, deferred_count = _approve_batch_gateways(
                conn,
                trust,
                uploader_id=body.uploader_id,
                uploaded_at=body.uploaded_at,
                reviewer_id=admin.id,
            )
            gw_approved_count = len(gw_ids)
            _invalidate_rebuild_for_gateways(
                conn,
                {p.serving_gateway_id for p in approved if p.serving_gateway_id} | set(gw_ids),
            )
        elif body.mode == "points_only":
            approved, deferred_count = approve_points_only_for_batch(
                conn,
                trust,
                uploader_id=body.uploader_id,
                uploaded_at=body.uploaded_at,
                reviewer_id=admin.id,
            )
            _invalidate_rebuild_for_gateways(
                conn, {p.serving_gateway_id for p in approved if p.serving_gateway_id}
            )
        elif body.mode == "gateways_only":
            rejected = reject_quarantine_for_batch(
                conn,
                trust,
                uploader_id=body.uploader_id,
                uploaded_at=body.uploaded_at,
                reviewer_id=admin.id,
                note=body.note,
            )
            gw_ids, deferred_count = _approve_batch_gateways(
                conn,
                trust,
                uploader_id=body.uploader_id,
                uploaded_at=body.uploaded_at,
                reviewer_id=admin.id,
            )
            gw_approved_count = len(gw_ids)
            _invalidate_rebuild_for_gateways(conn, set(gw_ids))

    if not approved and not rejected and gw_approved_count == 0 and deferred_count == 0:
        raise HTTPException(
            status_code=404,
            detail="Không có row/gateway nào chờ duyệt trong batch này (đã xử lý hoặc batch không tồn tại).",
        )

    contributor_email = (
        approved[0].contributor_email
        if approved
        else (rejected[0].contributor_email if rejected else None)
    )
    if contributor_email and approved:
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
        mode=body.mode,
        approved_count=len(approved),
        rejected_count=len(rejected),
        deferred_count=deferred_count,
        gateways_approved=gw_approved_count,
        gateways_rejected=gw_rejected_count,
    )

    return BatchReviewResponse(
        uploader_id=body.uploader_id,
        uploaded_at=body.uploaded_at,
        approved_count=len(approved),
        deferred_count=deferred_count,
        rejected_count=len(rejected),
        gateways_approved_count=gw_approved_count,
        gateways_rejected_count=gw_rejected_count,
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
    """Từ chối cả file: reject mọi rows quarantine (cả pending_review và
    pending_gateway) + reject mọi gateway pending của batch.

    Sau reject: gửi 1 email thông báo tổng kết cho user kèm lý do admin nhập
    (note). Per-row reject ở dưới KHÔNG gửi email (drill-in escape hatch —
    admin có thể loại nhiều row noise sẽ spam inbox).
    """
    with _engine().begin() as conn:
        rejected = reject_quarantine_for_batch(
            conn,
            trust,
            uploader_id=body.uploader_id,
            uploaded_at=body.uploaded_at,
            reviewer_id=admin.id,
            note=body.note,
        )
        gw_rejected_count = _reject_batch_gateways(
            conn,
            trust,
            uploader_id=body.uploader_id,
            uploaded_at=body.uploaded_at,
            reviewer_id=admin.id,
            note=body.note,
        )

    if not rejected and gw_rejected_count == 0:
        raise HTTPException(
            status_code=404,
            detail="Không có row/gateway nào chờ duyệt trong batch này (đã xử lý hoặc batch không tồn tại).",
        )

    contributor_email = rejected[0].contributor_email if rejected else None
    if contributor_email and rejected:
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
        gateways_rejected=gw_rejected_count,
    )

    return BatchReviewResponse(
        uploader_id=body.uploader_id,
        uploaded_at=body.uploaded_at,
        rejected_count=len(rejected),
        gateways_rejected_count=gw_rejected_count,
    )


# ── Gateway moderation (mig 0029) ───────────────────────────────────────
# Gateway từ sync (lpwanmapper/chirpstack) ban đầu chỉ vào geo.gateway_quarantine.
# Admin duyệt → INSERT geo.gateways + backfill FK measurement có cùng EUI.
# Admin trực tiếp tạo (form "Tạo mới gateway") → bypass quarantine, INSERT
# thẳng geo.gateways (admin đã trusted).

_LIST_PENDING_GATEWAYS = text("""
    SELECT
        q.id, q.code, q.name,
        ST_Y(q.location::geometry) AS latitude,
        ST_X(q.location::geometry) AS longitude,
        q.altitude_m, q.frequency_mhz, q.source_type,
        q.contributor_user_id, q.linked_source_id,
        q.created_at, q.updated_at,
        u.email AS contributor_email
    FROM geo.gateway_quarantine q
    LEFT JOIN auth.users u ON u.id = q.contributor_user_id
    WHERE q.review_status = 'pending_review'
    ORDER BY q.created_at DESC
""")

_COUNT_PENDING_GATEWAYS = text(
    "SELECT COUNT(*)::int AS total "
    "FROM geo.gateway_quarantine WHERE review_status = 'pending_review'"
)

# Promote quarantine row → geo.gateways. INSERT...SELECT đảm bảo atomic.
# ON CONFLICT (code) DO NOTHING: phòng race nếu admin click 2 lần hoặc EUI
# đã tồn tại trong geo.gateways từ luồng khác (vd seed). Promoter sau đó
# UPDATE quarantine review_status + lưu promoted_gateway_id.
_PROMOTE_GATEWAY = text("""
    INSERT INTO geo.gateways (
        code, name, location, altitude_m, frequency_mhz,
        external_id, source_type, contributor_user_id, linked_source_id
    )
    SELECT
        q.code, q.name, q.location, q.altitude_m, q.frequency_mhz,
        q.external_id, q.source_type, q.contributor_user_id, q.linked_source_id
    FROM geo.gateway_quarantine q
    WHERE q.id = :qid
    ON CONFLICT (code) DO NOTHING
    RETURNING id
""")

_RESOLVE_GATEWAY_ID_FOR_QUARANTINE = text("""
    SELECT g.id
    FROM geo.gateway_quarantine q
    JOIN geo.gateways g ON g.code = q.code
    WHERE q.id = :qid
""")

_MARK_GATEWAY_APPROVED = text("""
    UPDATE geo.gateway_quarantine
    SET review_status = 'approved',
        reviewed_by_user_id = :reviewer_id,
        reviewed_at = now(),
        promoted_gateway_id = :gw_id
    WHERE id = :qid AND review_status = 'pending_review'
""")

_MARK_GATEWAY_REJECTED = text("""
    UPDATE geo.gateway_quarantine
    SET review_status = 'rejected',
        reviewed_by_user_id = :reviewer_id,
        reviewed_at = now(),
        review_note = :note
    WHERE id = :qid AND review_status = 'pending_review'
    RETURNING id
""")

# Backfill measurement FK: rows ngoài ts.survey_quarantine có
# serving_gateway_eui = code mới + serving_gateway_id NULL → set FK.
# survey_training cũng update để các bản ghi đã promote trước được liên kết
# về gateway mới (trường hợp hiếm: measurement promote trước khi gateway
# duyệt; ngày nay validator yêu cầu serving_gateway_id non-null nên không
# xảy ra, nhưng defensive).
_BACKFILL_QUARANTINE_FK = text("""
    UPDATE ts.survey_quarantine
    SET serving_gateway_id = :gw_id
    WHERE serving_gateway_eui = :code AND serving_gateway_id IS NULL
""")


def _pending_gw_to_response(row: Any) -> PendingGatewayResponse:
    return PendingGatewayResponse(
        id=row.id,
        code=row.code,
        name=row.name,
        latitude=row.latitude,
        longitude=row.longitude,
        altitude_m=row.altitude_m,
        frequency_mhz=row.frequency_mhz,
        source_type=row.source_type,
        contributor_user_id=row.contributor_user_id,
        contributor_email=row.contributor_email,
        linked_source_id=row.linked_source_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get(
    "/gateway-contributions/pending",
    response_model=PendingGatewayListResponse,
)
def list_pending_gateways(
    admin: Annotated[User, Depends(require_admin)],
) -> PendingGatewayListResponse:
    """List gateway chờ admin duyệt (geo.gateway_quarantine review_status=pending)."""
    with _engine().begin() as conn:
        rows = conn.execute(_LIST_PENDING_GATEWAYS).all()
        total = conn.execute(_COUNT_PENDING_GATEWAYS).scalar_one()
    return PendingGatewayListResponse(
        items=[_pending_gw_to_response(r) for r in rows],
        total=int(total),
    )


def _promote_one_gateway_quarantine(
    conn: Any,
    trust: TrustValidator,
    *,
    quarantine_id: UUID,
    code: str,
    reviewer_id: UUID,
) -> tuple[UUID, int, int]:
    """Promote 1 row gateway_quarantine → geo.gateways + backfill FK survey
    rows + auto-promote rows pending_gateway cùng EUI → training.

    Trả (gateway_id, measurements_backfilled, deferred_promoted). Caller wrap
    transaction. KHÔNG raise — assume caller đã verify status='pending_review'.
    """
    promoted = conn.execute(_PROMOTE_GATEWAY, {"qid": quarantine_id}).one_or_none()
    if promoted is not None:
        gw_id = promoted.id
    else:
        gw_id = conn.execute(
            _RESOLVE_GATEWAY_ID_FOR_QUARANTINE, {"qid": quarantine_id}
        ).scalar_one()
    conn.execute(
        _MARK_GATEWAY_APPROVED,
        {"qid": quarantine_id, "reviewer_id": reviewer_id, "gw_id": gw_id},
    )
    backfill = conn.execute(_BACKFILL_QUARANTINE_FK, {"gw_id": gw_id, "code": code})
    backfilled = backfill.rowcount or 0
    deferred_promoted = promote_deferred_for_gateway(
        conn, trust, gateway_code=code, reviewer_id=reviewer_id
    )
    return gw_id, backfilled, deferred_promoted


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
        u.is_admin AS uploader_is_admin,
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
    GROUP BY t.batch_id, b.user_id, u.email, u.is_admin, b.kind, b.filename,
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
    super_email = get_settings().super_admin_email.lower()
    with _engine().begin() as conn:
        rows = conn.execute(_LIST_TRAINING_BATCHES).all()
    return TrainingBatchListResponse(
        items=[
            TrainingBatchItem(
                batch_id=r.batch_id,
                uploader_id=r.uploader_id,
                uploader_email=r.uploader_email,
                uploader_is_admin=bool(r.uploader_is_admin),
                uploader_is_super_admin=(
                    r.uploader_email is not None and r.uploader_email.lower() == super_email
                ),
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
        # Lấy tập gw bị ảnh hưởng TRƯỚC khi DELETE — sau DELETE là mất dấu.
        affected = (
            conn.execute(
                text(
                    "SELECT DISTINCT serving_gateway_id FROM ts.survey_training "
                    "WHERE batch_id = :id AND serving_gateway_id IS NOT NULL"
                ),
                {"id": batch_id},
            )
            .scalars()
            .all()
        )
        result = conn.execute(_DELETE_TRAINING_FOR_BATCH, {"batch_id": batch_id})
        _invalidate_rebuild_for_gateways(conn, affected)
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
           rows_trained, artifact_path, metrics, error_text, celery_task_id,
           report_dir
    FROM audit.ml_retrain_jobs
    WHERE id = :id
""")

_LIST_RETRAIN_JOBS = text("""
    SELECT id, status, triggered_by, triggered_at, started_at, finished_at,
           rows_trained, artifact_path, metrics, error_text, celery_task_id,
           report_dir
    FROM audit.ml_retrain_jobs
    ORDER BY triggered_at DESC
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
        report_dir=r.report_dir,
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
    """Toàn bộ lịch sử retrain (mới → cũ) — frontend hiển thị lịch sử đầy đủ."""
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


# Reports thư mục mount RO trong api-service (xem docker-compose.yml).
_REPORTS_ROOT = Path("/app/reports")


def _resolve_report_path(job_id: UUID, filename: str) -> Path:
    """Resolve + validate path tránh path-traversal (../../etc/passwd).

    Strict: filename không được chứa '/' / '\\' / '..'; path resolved phải
    nằm trong reports/retrain-{id}/ tương ứng.
    """
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Tên file không hợp lệ.")
    base = _REPORTS_ROOT / f"retrain-{job_id}"
    candidate = (base / filename).resolve()
    try:
        candidate.relative_to(base.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Đường dẫn ngoài phạm vi báo cáo.") from exc
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail=f"Không tìm thấy {filename}.")
    return candidate


@router.get("/ml/retrain/{job_id}/report")
def get_ml_retrain_report(
    job_id: UUID,
    admin: Annotated[User, Depends(require_admin)],
) -> FileResponse:
    """Xem báo cáo HTML trực tiếp (inline). FE mở qua iframe / new tab."""
    path = _resolve_report_path(job_id, "summary.html")
    return FileResponse(path, media_type="text/html; charset=utf-8")


@router.get("/ml/retrain/{job_id}/report.pdf")
def get_ml_retrain_report_pdf(
    job_id: UUID,
    admin: Annotated[User, Depends(require_admin)],
) -> FileResponse:
    """Tải PDF báo cáo. Filename gợi ý cho browser download dialog."""
    path = _resolve_report_path(job_id, "report.pdf")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=f"bao-cao-ml-{job_id}.pdf",
    )


@router.get("/ml/retrain/{job_id}/assets/{filename}")
def get_ml_retrain_report_asset(
    job_id: UUID,
    filename: str,
    admin: Annotated[User, Depends(require_admin)],
) -> FileResponse:
    """Serve PNG/JSON từ thư mục báo cáo (img inline trong summary.html).

    Template HTML dùng img src relative `<filename>` (cùng folder); browser
    load HTML qua `GET .../report` và fetch img qua URL tương đối, FastAPI
    route phải khớp. Endpoint này là cách rõ ràng (whitelist extension); FE
    cũng có thể gọi để fetch trực tiếp.

    WeasyPrint render PDF với base_url = thư mục báo cáo, tự đọc PNG cùng
    folder mà KHÔNG đi qua route này.
    """
    if not filename.lower().endswith((".png", ".json", ".svg", ".jpg", ".jpeg")):
        raise HTTPException(status_code=400, detail="Định dạng file không được phép.")
    path = _resolve_report_path(job_id, filename)
    media = (
        "image/png"
        if filename.lower().endswith(".png")
        else ("application/json" if filename.lower().endswith(".json") else "image/svg+xml")
    )
    return FileResponse(path, media_type=media)


# ── Notifications: nhắc admin rebuild + retrain khi có data mới ────────
# Đếm row training đã promote sau finished_at của job succeeded gần nhất.
# Không có job nào succeeded → count toàn bộ ts.survey_training (state nguội,
# chưa rebuild lần nào).

_NOTIFY_DATA_FRESHNESS_THRESHOLD = 100

_LAST_SUCCEEDED_REBUILD_AT = text("""
    SELECT finished_at
    FROM audit.coverage_rebuild_jobs
    WHERE status = 'succeeded' AND finished_at IS NOT NULL
    ORDER BY finished_at DESC
    LIMIT 1
""")

_LAST_SUCCEEDED_RETRAIN_AT = text("""
    SELECT finished_at
    FROM audit.ml_retrain_jobs
    WHERE status = 'succeeded' AND finished_at IS NOT NULL
    ORDER BY finished_at DESC
    LIMIT 1
""")

_COUNT_TRAINING_SINCE = text("""
    SELECT COUNT(*)::bigint AS c
    FROM ts.survey_training
    WHERE :since IS NULL OR promoted_at > :since
""")


@router.get(
    "/notifications/data-freshness",
    response_model=DataFreshnessResponse,
)
def get_data_freshness(
    admin: Annotated[User, Depends(require_admin)],
) -> DataFreshnessResponse:
    """Đếm điểm đo training mới kể từ lần rebuild / retrain succeeded gần nhất."""
    with _engine().begin() as conn:
        last_rebuild = conn.execute(_LAST_SUCCEEDED_REBUILD_AT).scalar_one_or_none()
        last_retrain = conn.execute(_LAST_SUCCEEDED_RETRAIN_AT).scalar_one_or_none()
        new_since_rebuild = int(
            conn.execute(_COUNT_TRAINING_SINCE, {"since": last_rebuild}).scalar_one()
        )
        new_since_retrain = int(
            conn.execute(_COUNT_TRAINING_SINCE, {"since": last_retrain}).scalar_one()
        )
    threshold = _NOTIFY_DATA_FRESHNESS_THRESHOLD
    return DataFreshnessResponse(
        threshold=threshold,
        last_rebuild_finished_at=last_rebuild,
        new_points_since_rebuild=new_since_rebuild,
        needs_rebuild=new_since_rebuild > threshold,
        last_retrain_finished_at=last_retrain,
        new_points_since_retrain=new_since_retrain,
        needs_retrain=new_since_retrain > threshold,
    )


# ── Tổng quan dashboard: time-series + top gateway ──────────────────────
# 3 metric:
#   * visits          → SUM(count) FROM audit.daily_visits
#   * signups         → COUNT(*) FROM auth.users   (theo created_at)
#   * training_points → COUNT(*) FROM ts.survey_training (theo promoted_at)
#
# 3 bucket: week (12 buckets), month (12 buckets), year (5 buckets).
# Mỗi query LEFT JOIN với generate_series để bucket trống vẫn trả 0.

_BUCKET_CONFIG: dict[str, dict[str, str]] = {
    "week": {"interval": "1 week", "count": "11"},
    "month": {"interval": "1 month", "count": "11"},
    "year": {"interval": "1 year", "count": "4"},
}

_METRIC_SOURCE: dict[str, dict[str, str]] = {
    "visits": {
        "from": "audit.daily_visits d",
        "ts_col": "d.day::timestamptz",
        "agg": "COALESCE(SUM(d.count), 0)::bigint",
    },
    "signups": {
        "from": "auth.users d",
        "ts_col": "d.created_at",
        "agg": "COUNT(d.id)::bigint",
    },
    "training_points": {
        "from": "ts.survey_training d",
        "ts_col": "d.promoted_at",
        "agg": "COUNT(d.id)::bigint",
    },
}


def _build_timeseries_sql(metric: str, bucket: str) -> str:
    """Build SQL với bucket = date_trunc + generate_series. KHÔNG có user input,
    chỉ chọn từ whitelist → safe khỏi SQL injection."""
    cfg = _BUCKET_CONFIG[bucket]
    src = _METRIC_SOURCE[metric]
    interval = cfg["interval"]
    n = cfg["count"]
    return f"""
        WITH buckets AS (
            SELECT generate_series(
                date_trunc('{bucket}', current_date) - interval '{n} {bucket}s',
                date_trunc('{bucket}', current_date),
                interval '{interval}'
            ) AS bucket_start
        )
        SELECT b.bucket_start, {src["agg"]} AS count
        FROM buckets b
        LEFT JOIN {src["from"]}
          ON {src["ts_col"]} >= b.bucket_start
         AND {src["ts_col"]} <  b.bucket_start + interval '{interval}'
        GROUP BY b.bucket_start
        ORDER BY b.bucket_start
    """


@router.get(
    "/stats/timeseries",
    response_model=TimeseriesResponse,
)
def get_stats_timeseries(
    admin: Annotated[User, Depends(require_admin)],
    metric: str = Query(..., pattern="^(visits|signups|training_points)$"),
    bucket: str = Query(..., pattern="^(week|month|year)$"),
) -> TimeseriesResponse:
    """Time-series cho chart Tổng quan. Buckets đầy đủ kể cả 0."""
    sql = text(_build_timeseries_sql(metric, bucket))
    with _engine().begin() as conn:
        rows = conn.execute(sql).all()
    return TimeseriesResponse(
        metric=metric,
        bucket=bucket,
        items=[
            TimeseriesPoint(bucket_start=r.bucket_start, count=int(r._mapping["count"]))
            for r in rows
        ],
    )


_TOP_GATEWAYS = text("""
    SELECT g.code AS gateway_code, g.name, COUNT(*)::bigint AS training_count
    FROM ts.survey_training t
    JOIN geo.gateways g ON g.id = t.serving_gateway_id
    GROUP BY g.code, g.name
    ORDER BY training_count DESC
    LIMIT 5
""")


@router.get(
    "/stats/top-gateways",
    response_model=TopGatewayResponse,
)
def get_top_gateways(
    admin: Annotated[User, Depends(require_admin)],
) -> TopGatewayResponse:
    """Top 5 gateway theo số điểm đo trong ts.survey_training."""
    with _engine().begin() as conn:
        rows = conn.execute(_TOP_GATEWAYS).all()
    return TopGatewayResponse(
        items=[
            TopGatewayItem(
                gateway_code=r.gateway_code,
                name=r.name,
                training_count=int(r.training_count),
            )
            for r in rows
        ],
    )
