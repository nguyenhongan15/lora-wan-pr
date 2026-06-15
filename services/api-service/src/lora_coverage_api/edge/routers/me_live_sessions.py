"""me/live-sessions — chuyến khảo sát trực tiếp (mig 0031).

1 chuyến khảo sát = 1 row `me.upload_batches` kind='live_session'. Endpoint:

  * POST /api/v1/me/live-sessions
        body {linked_source_id} → verify owner → tạo batch trống → trả batch_id.
        FE giữ batch_id trong state; mọi sync chu kỳ trong cùng chuyến append
        rows vào batch này (không tạo batch mới mỗi lần).

  * POST /api/v1/me/live-sessions/{batch_id}/sync
        Incremental pull. Lookup linked_source_id từ batch row (verify owner
        + kind='live_session' + chưa xoá) → delegate SyncService.sync với
        reuse_batch_id=batch_id. Mỗi gọi cộng dồn measurements_inserted vào
        batch points_count (không set, để không đè counter của lần trước).

End chuyến = FE gọi sync 1 lần cuối + (optional) DELETE batch nếu 0 row qua
endpoint cũ `DELETE /me/uploads/batches/{id}`. Không cần endpoint "end" riêng.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text

from ...application.identity import User
from ...application.linking import LinkingService
from ...application.sync import SyncResult, SyncService
from ...application.uploads import add_batch_points_count, create_upload_batch
from ..deps import _engine, current_user, linking_service, sync_service
from ..schemas import (
    LiveSessionStartRequest,
    LiveSessionStartResponse,
    SyncResultResponse,
)

router = APIRouter(prefix="/api/v1/me/live-sessions", tags=["me-live-sessions"])


_SELECT_LIVE_BATCH = text(
    """
    SELECT linked_source_id, uploaded_at
    FROM me.upload_batches
    WHERE id = :batch_id
      AND user_id = :user_id
      AND kind = 'live_session'
      AND deleted_at IS NULL
    """
)


# Webhook ingest (ChirpStack push) ghi vào ts.survey_quarantine với batch_id
# NULL — không có context để biết user đang chạy live session nào. Mỗi lần
# sync_live_session chạy (interval HOẶC final), gom toàn bộ record orphan
# (batch_id IS NULL) của user + linked_source trong cửa sổ session [uploaded_at
# .. now] về batch này. LPWANMapper KHÔNG bị: nó đi qua sync REST với
# reuse_batch_id, batch_id được set ngay lúc insert.
_BACKFILL_ORPHAN_WEBHOOK = text(
    """
    WITH updated AS (
        UPDATE ts.survey_quarantine
        SET batch_id = :batch_id
        WHERE batch_id IS NULL
          AND contributor_user_id = :user_id
          AND linked_source_id = :linked_source_id
          AND timestamp >= :session_started_at
        RETURNING 1
    )
    SELECT COUNT(*) FROM updated
    """
)


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


@router.post(
    "",
    response_model=LiveSessionStartResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Bắt đầu chuyến khảo sát trực tiếp — tạo 1 batch live_session",
)
def start_live_session(
    body: LiveSessionStartRequest,
    user: Annotated[User, Depends(current_user)],
    linking: Annotated[LinkingService, Depends(linking_service)],
) -> LiveSessionStartResponse:
    """Verify ownership của linked_source rồi tạo batch trống.

    Filename = ISO timestamp lúc click — UI mục "Lịch sử upload" dùng combo
    `kindLabel` ("Chuyến khảo sát") + filename để show. Points count khởi tạo
    0; sync incremental sẽ cộng dồn delta sau mỗi gọi.
    """
    started_at = datetime.now(UTC)
    with _engine().begin() as conn:
        # Raise LinkedSourceNotFoundError → 404 nếu không tồn tại hoặc sai owner.
        linking.get(conn, user, body.linked_source_id)
        batch_id, uploaded_at = create_upload_batch(
            conn,
            user_id=user.id,
            kind="live_session",
            filename=started_at.isoformat(),
            linked_source_id=body.linked_source_id,
            uploaded_at=started_at,
            points_count=0,
        )
    return LiveSessionStartResponse(
        batch_id=batch_id,
        linked_source_id=body.linked_source_id,
        started_at=uploaded_at,
    )


@router.post(
    "/{batch_id}/sync",
    response_model=SyncResultResponse,
    summary="Pull incremental cho 1 chuyến khảo sát đang chạy",
)
def sync_live_session(
    batch_id: UUID,
    user: Annotated[User, Depends(current_user)],
    sync: Annotated[SyncService, Depends(sync_service)],
) -> SyncResultResponse:
    """Lookup linked_source từ batch → call sync với reuse_batch_id.

    404 nếu batch không tồn tại / sai owner / sai kind / đã xoá. Sync error
    (locked / decrypt fail / adapter unreachable) vẫn HTTP 200 với
    `result.error != None` — đồng nhất với /me/sources/{id}/sync.
    """
    with _engine().begin() as conn:
        row = conn.execute(
            _SELECT_LIVE_BATCH, {"batch_id": batch_id, "user_id": user.id}
        ).one_or_none()
        if row is None:
            raise HTTPException(
                status_code=404,
                detail="Chuyến khảo sát không tồn tại hoặc đã kết thúc",
            )
        backfilled = (
            conn.execute(
                _BACKFILL_ORPHAN_WEBHOOK,
                {
                    "batch_id": batch_id,
                    "user_id": user.id,
                    "linked_source_id": row.linked_source_id,
                    "session_started_at": row.uploaded_at,
                },
            ).scalar()
            or 0
        )
        if backfilled > 0:
            add_batch_points_count(conn, batch_id=batch_id, delta=backfilled)
        result = sync.sync(
            conn,
            user=user,
            linked_source_id=row.linked_source_id,
            reuse_batch_id=batch_id,
        )
        if backfilled > 0:
            result = replace(
                result,
                measurements_inserted=result.measurements_inserted + backfilled,
            )
    return _sync_to_response(result)
