"""Survey training points endpoint (read-only cho map visualization).

Plan-auth-v1 §9.2: filter contributor được parse + authorize ở edge/filters.py
(resolver duy nhất). Repository nhận ContributorSpec đã authorize và build
SQL — KHÔNG kiểm tra quyền lại.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from ...application.identity import User
from ...application.repositories import SurveyIngest
from ..deps import _engine, current_user_optional, survey_repository
from ..filters import resolve_contributor
from ..schemas import (
    SurveyTrainingListResponse,
    SurveyTrainingPointResponse,
)

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
    limit: int = Query(default=1000, ge=1, le=5000),
    device_id: str | None = Query(default=None, max_length=64),
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
        limit=limit,
        device_id=device_id,
        source_type=source,
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
            )
            for p in points
        ],
        total=len(points),
    )
