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
from typing import Annotated
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import text

from ...application.identity import (
    AdminSelfModificationError,
    User,
    UserNotFoundError,
)
from ...application.sync import SyncResult, SyncService
from ..deps import _engine, require_admin, sync_service
from ..schemas import (
    AdminStatsResponse,
    SyncReportResponse,
    SyncResultResponse,
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

# Stats — 1 query/aggregate. Acceptable cho v1 (gateway/measurement bảng
# chưa quá lớn). Future: materialised view nếu cần.
_STATS_QUERIES = {
    "user_count": "SELECT COUNT(*) FROM auth.users",
    "active_user_count": "SELECT COUNT(*) FROM auth.users WHERE disabled = false",
    "linked_source_count": "SELECT COUNT(*) FROM auth.linked_sources",
    "active_source_count": (
        "SELECT COUNT(*) FROM auth.linked_sources "
        "WHERE status = 'active' AND contribute_to_community = true"
    ),
    "gateway_count": "SELECT COUNT(*) FROM geo.gateways",
    # ts.survey_training là hypertable training (đã accept) — quarantine
    # KHÔNG count vì không phải đóng góp confirm.
    "measurement_count": "SELECT COUNT(*) FROM ts.survey_training",
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
    with _engine().begin() as conn:
        rows = conn.execute(_LIST_USERS).all()
    items = [
        UserAdminResponse(
            id=r.id,
            email=r.email,
            is_admin=r.is_admin,
            disabled=r.disabled,
            created_at=r.created_at,
            contribution_count=int(r.contribution_count),
        )
        for r in rows
    ]
    return UserListResponse(items=items, total=len(items))


@router.patch("/users/{user_id}", response_model=UserAdminResponse)
def patch_user(
    user_id: UUID,
    body: UserPatchRequest,
    admin: Annotated[User, Depends(require_admin)],
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

    return UserAdminResponse(
        id=row.id,
        email=row.email,
        is_admin=row.is_admin,
        disabled=row.disabled,
        created_at=row.created_at,
        contribution_count=contribution_count,
    )


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
