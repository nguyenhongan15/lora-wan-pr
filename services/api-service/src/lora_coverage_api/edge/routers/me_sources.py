"""me/sources routes — link/list/unlink/patch/rotate external data sources.

Plan-auth-v1 §11 step 6 + plan ChirpStack per-user webhook ingest §2-3.
Mỗi endpoint marshall I/O và gọi 1-2 method LinkingService / SyncService /
DeviceQuery. ApplicationError handler ở edge/errors.py xử lý mọi exception.

PATCH gộp 2 toggle (contribute + status) vào 1 endpoint thay vì 2 sub-route
POST — REST-idiomatic, hỗ trợ ETag/If-Match concurrency check sau, giảm
surface area.

Webhook show-once: response của `POST /me/sources` và `POST /{id}/rotate-
webhook` là CHỖ DUY NHẤT trả plaintext token. List/get endpoint chỉ phơi
`has_webhook_token: bool` (presence-only).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from ...application.identity import EmailNotVerifiedError, User
from ...application.linking import LinkedSource, LinkingError, LinkingService, LinkResult
from ...application.repositories import DeviceQuery
from ...application.sync import SyncResult, SyncService
from ...config import Settings
from ..deps import (
    _engine,
    current_user,
    device_query,
    linking_service,
    settings_dep,
    sync_service,
)
from ..schemas import (
    DeviceListResponse,
    DeviceResponse,
    LinkedSourceListResponse,
    LinkedSourcePatchRequest,
    LinkedSourceResponse,
    LinkSourceCreatedResponse,
    LinkSourceRequest,
    SyncResultResponse,
    WebhookSecretResponse,
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
        has_webhook_token=ls.has_webhook_token,
        webhook_rotated_at=ls.webhook_rotated_at,
    )


def _build_webhook_url(settings: Settings, token: str) -> str:
    """Concat `webhook_base_url` (no trailing slash) với path token.

    Production: settings validator chặn empty base_url. Dev: empty → URL
    sẽ chỉ là path-only ("/api/v1/...") — FE có thể tự ghép với current
    origin. Vẫn không hardcode host trong code.
    """
    base = settings.webhook_base_url.rstrip("/")
    return f"{base}/api/v1/webhooks/chirpstack/source/{token}"


def _to_created_response(result: LinkResult, settings: Settings) -> LinkSourceCreatedResponse:
    """Marshall LinkResult → response. Webhook fields chỉ set khi có token
    (source thuộc whitelist). Source khác → cả 2 = None.
    """
    if result.webhook_token is None:
        return LinkSourceCreatedResponse(
            source=_to_response(result.linked_source),
            webhook_url=None,
            webhook_token=None,
        )
    return LinkSourceCreatedResponse(
        source=_to_response(result.linked_source),
        webhook_url=_build_webhook_url(settings, result.webhook_token),
        webhook_token=result.webhook_token,
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
    response_model=LinkSourceCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
def link_source(
    body: LinkSourceRequest,
    user: Annotated[User, Depends(current_user)],
    linking: Annotated[LinkingService, Depends(linking_service)],
    settings: Annotated[Settings, Depends(settings_dep)],
    response: Response,
) -> LinkSourceCreatedResponse:
    with _engine().begin() as conn:
        result = linking.link(
            conn,
            user=user,
            source_type=body.source_type,
            label=body.label,
            credentials=body.credentials,
        )
    response.headers["Location"] = f"/api/v1/me/sources/{result.linked_source.id}"
    return _to_created_response(result, settings)


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

    if body.contribute_to_community is True and not user.email_verified:
        raise EmailNotVerifiedError("Cần xác thực email trước khi đóng góp dữ liệu cho cộng đồng")

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


@router.post(
    "/{linked_source_id}/rotate-webhook",
    response_model=WebhookSecretResponse,
)
def rotate_webhook(
    linked_source_id: UUID,
    user: Annotated[User, Depends(current_user)],
    linking: Annotated[LinkingService, Depends(linking_service)],
    settings: Annotated[Settings, Depends(settings_dep)],
) -> WebhookSecretResponse:
    """Sinh token webhook mới, vô hiệu token cũ. Trả plaintext 1 lần.

    Source type không hỗ trợ webhook (lpwanmapper) → 400 qua LinkingError.
    """
    with _engine().begin() as conn:
        result = linking.rotate_webhook(conn, user, linked_source_id)
    # rotate luôn issue token mới — webhook_token không bao giờ None ở đây,
    # nhưng assert vẫn an toàn tránh mypy narrow miss.
    assert result.webhook_token is not None
    return WebhookSecretResponse(
        source=_to_response(result.linked_source),
        webhook_url=_build_webhook_url(settings, result.webhook_token),
        webhook_token=result.webhook_token,
    )


@router.get(
    "/{linked_source_id}/devices",
    response_model=DeviceListResponse,
)
def list_devices(
    linked_source_id: UUID,
    user: Annotated[User, Depends(current_user)],
    linking: Annotated[LinkingService, Depends(linking_service)],
    devices: Annotated[DeviceQuery, Depends(device_query)],
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> DeviceListResponse:
    """List devices của 1 linked_source. Verify ownership trước khi đọc
    `geo.devices` — repo không tự JOIN.
    """
    with _engine().begin() as conn:
        # Ownership check — raise LinkedSourceNotFoundError → 404 nếu sai
        # owner hoặc không tồn tại (define errors out of existence).
        linking.get(conn, user, linked_source_id)

    items, total = devices.list_by_linked_source(
        linked_source_id=linked_source_id,
        offset=offset,
        limit=limit,
    )
    return DeviceListResponse(
        items=[
            DeviceResponse(
                id=d.id,
                dev_eui=d.dev_eui,
                name=d.name,
                source_type=d.source_type,
                last_seen_at=d.last_seen_at,
                created_at=d.created_at,
                updated_at=d.updated_at,
            )
            for d in items
        ],
        total=total,
    )


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
