"""me/sources routes — link/list/unlink/patch external data sources.

Plan-auth-v1 §11 step 6. 4 endpoint mỏng — mỗi endpoint marshall I/O và gọi
đúng 1-2 method LinkingService. ApplicationError handler ở edge/errors.py
xử lý mọi exception (CredentialTestFailedError 400, LinkedSourceNotFoundError
404, InvalidCredentialsError 401 từ current_user dep).

PATCH gộp 2 toggle (contribute + status) vào 1 endpoint thay vì 2 sub-route
POST — REST-idiomatic, hỗ trợ ETag/If-Match concurrency check sau, giảm
surface area.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from ...application.identity import User
from ...application.linking import LinkedSource, LinkingError, LinkingService
from ...application.sync import SyncResult, SyncService
from ..deps import _engine, current_user, linking_service, sync_service
from ..schemas import (
    LinkedSourceListResponse,
    LinkedSourcePatchRequest,
    LinkedSourceResponse,
    LinkSourceRequest,
    SyncResultResponse,
)

router = APIRouter(prefix="/api/v1/me/sources", tags=["me-sources"])


def _to_response(ls: LinkedSource) -> LinkedSourceResponse:
    return LinkedSourceResponse(
        id=ls.id,
        source_type=ls.source_type,
        label=ls.label,
        status=ls.status,
        contribute_to_community=ls.contribute_to_community,
        contributed_at=ls.contributed_at,
        last_sync_at=ls.last_sync_at,
        last_sync_error=ls.last_sync_error,
        created_at=ls.created_at,
    )


@router.get("", response_model=LinkedSourceListResponse)
def list_sources(
    user: Annotated[User, Depends(current_user)],
    linking: Annotated[LinkingService, Depends(linking_service)],
) -> LinkedSourceListResponse:
    with _engine().begin() as conn:
        items = linking.list_for(conn, user)
    return LinkedSourceListResponse(
        items=[_to_response(x) for x in items],
        total=len(items),
    )


@router.post(
    "",
    response_model=LinkedSourceResponse,
    status_code=status.HTTP_201_CREATED,
)
def link_source(
    body: LinkSourceRequest,
    user: Annotated[User, Depends(current_user)],
    linking: Annotated[LinkingService, Depends(linking_service)],
    response: Response,
) -> LinkedSourceResponse:
    with _engine().begin() as conn:
        created = linking.link(
            conn,
            user=user,
            source_type=body.source_type,
            label=body.label,
            credentials=body.credentials,
        )
    response.headers["Location"] = f"/api/v1/me/sources/{created.id}"
    return _to_response(created)


@router.delete("/{linked_source_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_source(
    linked_source_id: UUID,
    user: Annotated[User, Depends(current_user)],
    linking: Annotated[LinkingService, Depends(linking_service)],
) -> Response:
    with _engine().begin() as conn:
        linking.unlink(conn, user, linked_source_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/{linked_source_id}", response_model=LinkedSourceResponse)
def patch_source(
    linked_source_id: UUID,
    body: LinkedSourcePatchRequest,
    user: Annotated[User, Depends(current_user)],
    linking: Annotated[LinkingService, Depends(linking_service)],
) -> LinkedSourceResponse:
    if body.contribute_to_community is None and body.status is None:
        raise LinkingError("PATCH body cần ít nhất 1 trong contribute_to_community hoặc status")

    # Apply mỗi toggle riêng — 1 transaction để 2 update atomic. Method gọi
    # cuối trả LinkedSource sau cả 2 update.
    with _engine().begin() as conn:
        result: LinkedSource | None = None
        if body.status is not None:
            result = linking.set_sync_enabled(
                conn, user, linked_source_id, enabled=body.status == "active"
            )
        if body.contribute_to_community is not None:
            result = linking.set_contribution(
                conn, user, linked_source_id, enabled=body.contribute_to_community
            )
    assert result is not None
    return _to_response(result)


def _sync_to_response(r: SyncResult) -> SyncResultResponse:
    return SyncResultResponse(
        linked_source_id=r.linked_source_id,
        gateways_inserted=r.gateways_inserted,
        gateways_updated=r.gateways_updated,
        measurements_inserted=r.measurements_inserted,
        measurements_updated=r.measurements_updated,
        last_sync_at=r.last_sync_at,
        error=r.error,
    )


# Manual "Sync now" — plan §5 Flow B step 5. Per plan §3.4, sync KHÔNG raise
# trên adapter/decrypt/lock failure: HTTP 200 + result.error != None thay vì
# 502/409. Trade HTTP semantics cho client error handling đơn giản
# (Ousterhout Ch10: define errors out of existence). Riêng linked_source
# không tồn tại / sai owner → 404 (route fail, không phải sync fail).
@router.post("/{linked_source_id}/sync", response_model=SyncResultResponse)
def sync_source(
    linked_source_id: UUID,
    user: Annotated[User, Depends(current_user)],
    sync: Annotated[SyncService, Depends(sync_service)],
) -> SyncResultResponse:
    with _engine().begin() as conn:
        result = sync.sync(conn, user=user, linked_source_id=linked_source_id)
    return _sync_to_response(result)
