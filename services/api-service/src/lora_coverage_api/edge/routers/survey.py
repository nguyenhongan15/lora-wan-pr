"""Survey training points endpoint (read-only cho map visualization).

Plan-auth-v1 §9.2: filter contributor được parse + authorize ở edge/filters.py
(resolver duy nhất). Repository nhận ContributorSpec đã authorize và build
SQL — KHÔNG kiểm tra quyền lại.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from ...application.identity import User
from ...application.repositories import SurveyIngest
from ..deps import _engine, current_user, current_user_optional, survey_repository
from ..filters import resolve_contributor
from ..schemas import (
    MyDeviceItem,
    MyDeviceListResponse,
    SurveyTrainingListResponse,
    SurveyTrainingPointResponse,
)

# Safety ceiling cho 1 request (cũng dùng làm `limit` default). 50000 đủ
# headroom cho tập điểm đo hiện tại (~9k) + growth, đồng thời vẫn chặn
# full-table dump nếu caller gửi rank_to khổng lồ.
_MAX_RANK_WINDOW = 50000

# SF range cứng theo schema DB constraint (xem migration 0003).
_SF_MIN, _SF_MAX = 7, 12

router = APIRouter(prefix="/api/v1/survey", tags=["survey"])


@router.get(
    "/training",
    response_model=SurveyTrainingListResponse,
    summary="List promoted survey points (read-only, cho map visualization)",
)
async def list_training_points(
    user: Annotated[User | None, Depends(current_user_optional)],
    repo: Annotated[SurveyIngest, Depends(survey_repository)],
    contributor: Annotated[
        str | None,
        Query(
            description=(
                "Symbolic filter: 'community' (default), 'me' (cần auth), "
                "'user/<uuid>' (admin only)."
            ),
            examples=["community", "me", "user/00000000-0000-0000-0000-000000000000"],
        ),
    ] = None,
    linked_source: Annotated[
        UUID | None,
        Query(description="Sub-filter cho 'me': chỉ data của 1 linked source."),
    ] = None,
    source: Annotated[
        str | None,
        Query(description="Filter theo source_type, vd 'lpwanmapper'.", max_length=64),
    ] = None,
    min_lon: float | None = Query(default=None, ge=-180, le=180),
    min_lat: float | None = Query(default=None, ge=-90, le=90),
    max_lon: float | None = Query(default=None, ge=-180, le=180),
    max_lat: float | None = Query(default=None, ge=-90, le=90),
    # Default = safety cap (_MAX_RANK_WINDOW). "Không params" = trả tất cả
    # điểm tới mức trần hệ thống cho phép — UI map default không hard-code
    # số lượng nhỏ hơn.
    limit: int = Query(default=_MAX_RANK_WINDOW, ge=1, le=_MAX_RANK_WINDOW),
    device_id: str | None = Query(default=None, max_length=64),
    sf: str | None = Query(
        default=None,
        description="Multi-select SF, comma-separated, vd '7,8,9'. Mỗi giá trị 7..12.",
        max_length=32,
    ),
    rssi_min: float | None = Query(default=None, ge=-150, le=0),
    rssi_max: float | None = Query(default=None, ge=-150, le=0),
    snr_min: float | None = Query(default=None, ge=-30, le=30),
    snr_max: float | None = Query(default=None, ge=-30, le=30),
    time_from: datetime | None = Query(default=None),
    time_to: datetime | None = Query(default=None),
    sort_by: Literal["timestamp", "rssi", "snr"] = Query(default="timestamp"),
    sort_order: Literal["asc", "desc"] = Query(default="desc"),
    rank_from: int | None = Query(default=None, ge=1, le=_MAX_RANK_WINDOW),
    rank_to: int | None = Query(default=None, ge=1, le=_MAX_RANK_WINDOW),
) -> SurveyTrainingListResponse:
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

    sf_list = _parse_sf_list(sf)
    _validate_range(rssi_min, rssi_max, "rssi")
    _validate_range(snr_min, snr_max, "snr")
    if time_from is not None and time_to is not None and time_from > time_to:
        raise HTTPException(status_code=422, detail="time_from phải <= time_to")
    offset, eff_limit = _resolve_window(rank_from, rank_to, limit)

    # Resolver mở connection ngắn để verify linked_source ownership.
    # Repository tự mở connection riêng cho query chính (read path).
    with _engine().begin() as conn:
        spec = resolve_contributor(
            conn,
            raw_contributor=contributor,
            raw_linked_source=linked_source,
            current_user=user,
        )

    points = repo.list_training(
        contributor=spec,
        bbox=bbox,
        offset=offset,
        limit=eff_limit,
        device_id=device_id,
        source_type=source,
        sf_list=sf_list,
        rssi_min=rssi_min,
        rssi_max=rssi_max,
        snr_min=snr_min,
        snr_max=snr_max,
        time_from=time_from,
        time_to=time_to,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return SurveyTrainingListResponse(
        items=[
            SurveyTrainingPointResponse(
                latitude=p.latitude,
                longitude=p.longitude,
                rssi_dbm=p.rssi_dbm,
                snr_db=p.snr_db,
                spreading_factor=p.spreading_factor,
                serving_gateway_id=p.serving_gateway_id,
                device_id=p.device_id,
                frequency_mhz=p.frequency_mhz,
                timestamp=p.timestamp,
                code_rate=p.code_rate,
            )
            for p in points
        ],
        total=len(points),
    )


@router.get(
    "/me/devices",
    response_model=MyDeviceListResponse,
    summary="List distinct device_ids of current user (cho dropdown filter)",
)
def list_my_devices(
    user: Annotated[User, Depends(current_user)],
    repo: Annotated[SurveyIngest, Depends(survey_repository)],
    linked_source: Annotated[
        UUID | None,
        Query(description="Optional narrow theo 1 linked_source của user."),
    ] = None,
) -> MyDeviceListResponse:
    devices = repo.list_user_devices(user_id=user.id, linked_source_id=linked_source)
    return MyDeviceListResponse(
        items=[MyDeviceItem(device_id=d.device_id, count=d.count) for d in devices]
    )


def _parse_sf_list(raw: str | None) -> list[int] | None:
    if raw is None:
        return None
    try:
        values = [int(x.strip()) for x in raw.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(
            status_code=422, detail="sf phải là CSV số nguyên, vd '7,8,9'"
        ) from None
    if not values:
        return None
    if any(v < _SF_MIN or v > _SF_MAX for v in values):
        raise HTTPException(
            status_code=422,
            detail=f"sf chỉ chấp nhận giá trị {_SF_MIN}..{_SF_MAX}",
        )
    # Khử trùng + giữ thứ tự để query plan stable giữa các request.
    return sorted(set(values))


def _validate_range(lo: float | None, hi: float | None, name: str) -> None:
    if lo is not None and hi is not None and lo > hi:
        raise HTTPException(status_code=422, detail=f"{name}_min phải <= {name}_max")


def _resolve_window(
    rank_from: int | None, rank_to: int | None, legacy_limit: int
) -> tuple[int, int]:
    """Map (rank_from, rank_to) → (offset, limit). Nếu không có rank, dùng
    legacy_limit từ đầu (offset=0).
    """
    if rank_from is None and rank_to is None:
        return 0, legacy_limit
    rf = rank_from if rank_from is not None else 1
    rt = rank_to if rank_to is not None else legacy_limit
    if rt < rf:
        raise HTTPException(status_code=422, detail="rank_to phải >= rank_from")
    window = rt - rf + 1
    if window > _MAX_RANK_WINDOW:
        raise HTTPException(
            status_code=422,
            detail=f"Khoảng rank tối đa {_MAX_RANK_WINDOW} điểm/lần",
        )
    return rf - 1, window
