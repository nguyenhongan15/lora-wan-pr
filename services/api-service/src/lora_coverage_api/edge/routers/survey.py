"""Survey training points endpoint (read-only cho map visualization)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ...application.repositories import SurveyIngest
from ..deps import survey_repository
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
    repo: SurveyIngest = Depends(survey_repository),
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

    points = repo.list_training(bbox=bbox, limit=limit, device_id=device_id)
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
