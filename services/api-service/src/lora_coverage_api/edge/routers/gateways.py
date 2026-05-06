"""Gateway directory CRUD endpoints (admin)."""

from __future__ import annotations

import hashlib
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse

from ...application.repositories import GatewayDirectory
from ...domain.coverage import Gateway, GatewayId
from ..deps import gateway_directory
from ..schemas import (
    GatewayCreateRequest,
    GatewayListResponse,
    GatewayPatchRequest,
    GatewayResponse,
)

router = APIRouter(prefix="/api/v1/gateways", tags=["gateways"])


def _to_response(g: Gateway) -> GatewayResponse:
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
        )
    )
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
    return f'W/"{digest}"'


@router.get(
    "",
    response_model=GatewayListResponse,
    summary="List gateways (optional bbox filter)",
)
async def list_gateways(
    directory: GatewayDirectory = Depends(gateway_directory),
    min_lon: float | None = Query(default=None, ge=-180, le=180),
    min_lat: float | None = Query(default=None, ge=-90, le=90),
    max_lon: float | None = Query(default=None, ge=-180, le=180),
    max_lat: float | None = Query(default=None, ge=-90, le=90),
    limit: int = Query(default=500, ge=1, le=5000),
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

    items = directory.list_gateways(bbox=bbox, is_public=True, limit=limit)
    return GatewayListResponse(
        items=[_to_response(g) for g in items],
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
    return _to_response(g)


@router.post(
    "",
    response_model=GatewayResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_gateway(
    payload: GatewayCreateRequest,
    request: Request,
    directory: GatewayDirectory = Depends(gateway_directory),
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

    patch_dict: dict[str, object] = {
        k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None
    }
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
