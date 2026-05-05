"""Survey upload endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse

from ...application.repositories import SurveyIngest
from ...application.survey_service import SurveyIngestService
from ...domain.coverage import GatewayId
from ...domain.survey import SurveyBatch, SurveyRecord, UploaderId
from ..deps import survey_repository, survey_service
from ..schemas import (
    SurveyTrainingListResponse,
    SurveyTrainingPointResponse,
    SurveyUploadRequest,
    SurveyUploadResponse,
)

router = APIRouter(prefix="/api/v1/survey", tags=["survey"])


@router.post(
    "/upload",
    response_model=SurveyUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload batch survey records (quarantined → manual promote)",
    responses={
        422: {"description": "Validation error (whole batch rejected)"},
    },
)
async def upload_survey(
    payload: SurveyUploadRequest,
    request: Request,
    service: SurveyIngestService = Depends(survey_service),
) -> SurveyUploadResponse | JSONResponse:
    try:
        records = [
            SurveyRecord(
                timestamp=r.timestamp,
                latitude=r.latitude,
                longitude=r.longitude,
                rssi_dbm=r.rssi_dbm,
                snr_db=r.snr_db,
                spreading_factor=r.spreading_factor,
                frequency_mhz=r.frequency_mhz,
                device_id=r.device_id,
                serving_gateway_id=GatewayId(r.serving_gateway_id) if r.serving_gateway_id else None,
            )
            for r in payload.records
        ]
    except ValueError as exc:
        return JSONResponse(
            status_code=422,
            media_type="application/problem+json",
            content={
                "type": "about:blank",
                "title": "Survey record validation failed",
                "status": 422,
                "detail": str(exc),
                "instance": str(request.url.path),
                "code": "SURVEY_RECORD_INVALID",
                "traceId": getattr(request.state, "trace_id", None),
            },
        )

    batch = SurveyBatch(
        uploader_id=UploaderId(payload.uploader_id),
        records=records,
    )
    receipt = service.ingest_batch(batch)

    return SurveyUploadResponse(
        batch_id=receipt.batch_id,
        status=receipt.status.value,  # type: ignore[arg-type]
        accepted_count=receipt.accepted_count,
        rejected_count=receipt.rejected_count,
        estimated_review_hours=receipt.estimated_review_hours,
    )


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

    points = repo.list_training(bbox=bbox, limit=limit)
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
