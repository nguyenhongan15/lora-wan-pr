"""Gateway directory CRUD endpoints (admin)."""

from __future__ import annotations

import hashlib
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse

from ...application.gateway_state import GatewayState, GatewayStateService
from ...application.identity import User
from ...application.repositories import GatewayDirectory
from ...domain.coverage import Gateway, GatewayId
from ..deps import (
    _engine,
    current_user_optional,
    gateway_directory,
    gateway_state_service,
    require_admin,
)
from ..filters import resolve_contributor
from ..schemas import (
    GatewayCreateRequest,
    GatewayListResponse,
    GatewayPatchRequest,
    GatewayResponse,
)

router = APIRouter(prefix="/api/v1/gateways", tags=["gateways"])


def _to_response(g: Gateway, state_map: dict[str, GatewayState] | None = None) -> GatewayResponse:
    live = state_map.get(g.code.lower()) if state_map else None
    # Manual override (admin "ghim") thắng derived state. last_seen_at vẫn lấy
    # từ ChirpStack/DB (nếu có) để user biết lần cuối thực tế.
    if g.manual_state_override is not None:
        state_value: str = g.manual_state_override
    else:
        state_value = live.state if live else "unknown"
    return GatewayResponse(
        id=g.id,
        code=g.code,
        name=g.name,
        latitude=g.latitude,
        longitude=g.longitude,
        altitude_m=g.altitude_m,
        antenna_height_m=g.antenna_height_m,
        antenna_gain_dbi=g.antenna_gain_dbi,
        tx_power_dbm=g.tx_power_dbm,
        frequency_mhz=g.frequency_mhz,
        rx_antenna_gain_dbi=g.rx_antenna_gain_dbi,
        rx_sensitivity_dbm=g.rx_sensitivity_dbm,
        noise_floor_dbm=g.noise_floor_dbm,
        state=state_value,
        last_seen_at=live.last_seen_at if live else None,
        is_public=g.is_public,
        manual_state_override=g.manual_state_override,
    )


def _etag_for(g: Gateway) -> str:
    """Weak ETag derived from mutable content.

    Đủ cho optimistic concurrency: hai admin sửa cùng lúc → admin sau bị 412.
    Không track delete vì gateway hiện không hỗ trợ DELETE.
    """
    payload = "|".join(
        str(v)
        for v in (
            g.id,
            g.name,
            g.altitude_m,
            g.antenna_height_m,
            g.antenna_gain_dbi,
            g.tx_power_dbm,
            g.frequency_mhz,
            g.rx_antenna_gain_dbi,
            g.rx_sensitivity_dbm,
            g.noise_floor_dbm,
            g.is_public,
            g.manual_state_override,
        )
    )
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
    return f'W/"{digest}"'


@router.get(
    "",
    response_model=GatewayListResponse,
    summary="List gateways (optional bbox + contributor filter)",
)
async def list_gateways(
    user: Annotated[User | None, Depends(current_user_optional)],
    directory: GatewayDirectory = Depends(gateway_directory),
    state_service: GatewayStateService = Depends(gateway_state_service),
    contributor: Annotated[
        str | None,
        Query(
            description=(
                "Symbolic filter: 'community' (default), 'me' (cần auth), "
                "'user/<uuid>' (admin only). Mode 'me'/'user' chỉ trả "
                "gateway từng phục vụ ít nhất 1 survey của user đó."
            ),
            examples=["community", "me", "user/00000000-0000-0000-0000-000000000000"],
        ),
    ] = None,
    linked_source: Annotated[
        UUID | None,
        Query(description="Sub-filter cho 'me': chỉ gateway phục vụ survey của 1 linked source."),
    ] = None,
    min_lon: float | None = Query(default=None, ge=-180, le=180),
    min_lat: float | None = Query(default=None, ge=-90, le=90),
    max_lon: float | None = Query(default=None, ge=-180, le=180),
    max_lat: float | None = Query(default=None, ge=-90, le=90),
    limit: int = Query(default=500, ge=1, le=5000),
    include_hidden: bool = Query(
        default=False,
        description=(
            "Admin only: bypass is_public filter để hiện cả gateway đã ẩn khỏi "
            "bản đồ chung. Non-admin gửi True sẽ bị ignore."
        ),
    ),
) -> GatewayListResponse:
    bbox: tuple[float, float, float, float] | None
    bbox_parts = (min_lon, min_lat, max_lon, max_lat)
    if all(v is not None for v in bbox_parts):
        bbox = tuple(bbox_parts)  # type: ignore[assignment]
    elif any(v is not None for v in bbox_parts):
        raise HTTPException(
            status_code=422,
            detail="bbox cần đủ 4 tham số: min_lon, min_lat, max_lon, max_lat",
        )
    else:
        bbox = None

    # Resolver mở connection ngắn để verify linked_source ownership.
    with _engine().begin() as conn:
        spec = resolve_contributor(
            conn,
            raw_contributor=contributor,
            raw_linked_source=linked_source,
            current_user=user,
        )

    # contributor=community → chỉ gateway is_public=true (đã duyệt + chưa bị ẩn).
    # contributor=self/user → bypass is_public để user vẫn thấy gateway của
    # mình đã bị admin ẩn khỏi bản đồ chung.
    # include_hidden=true: chỉ honor cho admin (admin panel cần thấy cả gw ẩn
    # để restore). Non-admin bị ignore (im lặng, không 403 — tránh leak schema).
    admin_override = include_hidden and user is not None and user.is_admin
    if admin_override:
        is_public_filter = None
    else:
        is_public_filter = True if spec.mode == "community" else None
    items = directory.list_gateways(
        bbox=bbox,
        is_public=is_public_filter,
        limit=limit,
        contributor=spec,
    )
    state_map = state_service.get_state_map()
    return GatewayListResponse(
        items=[_to_response(g, state_map) for g in items],
        total=len(items),
    )


@router.get(
    "/{gateway_id}",
    response_model=GatewayResponse,
    responses={404: {"description": "Not found"}},
)
async def get_gateway(
    gateway_id: UUID,
    request: Request,
    response: Response,
    directory: GatewayDirectory = Depends(gateway_directory),
    state_service: GatewayStateService = Depends(gateway_state_service),
) -> GatewayResponse | JSONResponse:
    g = directory.get_by_id(GatewayId(gateway_id))
    if g is None:
        return JSONResponse(
            status_code=404,
            media_type="application/problem+json",
            content={
                "type": "about:blank",
                "title": "Gateway not found",
                "status": 404,
                "instance": str(request.url.path),
                "code": "GATEWAY_NOT_FOUND",
                "traceId": getattr(request.state, "trace_id", None),
            },
        )
    response.headers["ETag"] = _etag_for(g)
    return _to_response(g, state_service.get_state_map())


@router.post(
    "",
    response_model=GatewayResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_gateway(
    payload: GatewayCreateRequest,
    request: Request,
    directory: GatewayDirectory = Depends(gateway_directory),
    _admin: User = Depends(require_admin),
) -> GatewayResponse | JSONResponse:
    candidate = Gateway(
        id=GatewayId(UUID(int=0)),  # placeholder, DB sẽ gen
        code=payload.code,
        name=payload.name,
        latitude=payload.latitude,
        longitude=payload.longitude,
        altitude_m=payload.altitude_m,
        antenna_height_m=payload.antenna_height_m,
        antenna_gain_dbi=payload.antenna_gain_dbi,
        tx_power_dbm=payload.tx_power_dbm,
        frequency_mhz=payload.frequency_mhz,
        rx_antenna_gain_dbi=payload.rx_antenna_gain_dbi,
        rx_sensitivity_dbm=payload.rx_sensitivity_dbm,
        noise_floor_dbm=payload.noise_floor_dbm,
    )
    try:
        created = directory.create(candidate)
    except Exception as exc:  # IntegrityError, CHECK violation, ...
        return JSONResponse(
            status_code=409,
            media_type="application/problem+json",
            content={
                "type": "about:blank",
                "title": "Gateway create failed",
                "status": 409,
                "detail": str(exc.__cause__ or exc),
                "instance": str(request.url.path),
                "code": "GATEWAY_CREATE_CONFLICT",
                "traceId": getattr(request.state, "trace_id", None),
            },
        )
    return _to_response(created)


@router.patch(
    "/{gateway_id}",
    response_model=GatewayResponse,
    responses={
        404: {"description": "Not found"},
        412: {"description": "ETag mismatch"},
        428: {"description": "If-Match header required"},
    },
)
async def patch_gateway(
    gateway_id: UUID,
    payload: GatewayPatchRequest,
    request: Request,
    response: Response,
    directory: GatewayDirectory = Depends(gateway_directory),
    if_match: str | None = Header(default=None, alias="If-Match"),
    _admin: User = Depends(require_admin),
) -> GatewayResponse | JSONResponse:
    if if_match is None:
        return JSONResponse(
            status_code=428,
            media_type="application/problem+json",
            content={
                "type": "about:blank",
                "title": "Precondition required",
                "status": 428,
                "detail": "If-Match header bắt buộc khi PATCH gateway.",
                "instance": str(request.url.path),
                "code": "IF_MATCH_REQUIRED",
                "traceId": getattr(request.state, "trace_id", None),
            },
        )

    current = directory.get_by_id(GatewayId(gateway_id))
    if current is None:
        return JSONResponse(
            status_code=404,
            media_type="application/problem+json",
            content={
                "type": "about:blank",
                "title": "Gateway not found",
                "status": 404,
                "instance": str(request.url.path),
                "code": "GATEWAY_NOT_FOUND",
                "traceId": getattr(request.state, "trace_id", None),
            },
        )

    current_etag = _etag_for(current)
    # Parse If-Match list (RFC 7232) — accept "*" as wildcard.
    if_match_clean = if_match.strip()
    if if_match_clean != "*":
        candidates = {tok.strip() for tok in if_match_clean.split(",")}
        if current_etag not in candidates:
            return JSONResponse(
                status_code=412,
                media_type="application/problem+json",
                headers={"ETag": current_etag},
                content={
                    "type": "about:blank",
                    "title": "Precondition failed",
                    "status": 412,
                    "detail": "Gateway đã bị sửa bởi user khác. Reload và thử lại.",
                    "instance": str(request.url.path),
                    "code": "ETAG_MISMATCH",
                    "traceId": getattr(request.state, "trace_id", None),
                },
            )

    # `manual_state_override` cho phép explicit-null (clear ghim → về derived
    # state). Các field khác: null = "không gửi", lọc bỏ. exclude_unset đã chỉ
    # giữ field user thực sự gửi nên distinguish được 2 trường hợp.
    raw = payload.model_dump(exclude_unset=True)
    patch_dict: dict[str, object] = {}
    for k, v in raw.items():
        if k == "manual_state_override":
            patch_dict[k] = v  # giữ cả None để UPDATE SET = NULL
        elif v is not None:
            patch_dict[k] = v
    updated = directory.update(GatewayId(gateway_id), patch_dict)
    if updated is None:
        # Race: gateway xóa giữa GET-current và UPDATE.
        return JSONResponse(
            status_code=404,
            media_type="application/problem+json",
            content={
                "type": "about:blank",
                "title": "Gateway not found",
                "status": 404,
                "instance": str(request.url.path),
                "code": "GATEWAY_NOT_FOUND",
                "traceId": getattr(request.state, "trace_id", None),
            },
        )
    response.headers["ETag"] = _etag_for(updated)
    return _to_response(updated)
