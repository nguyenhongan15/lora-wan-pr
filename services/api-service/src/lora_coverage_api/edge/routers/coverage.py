"""Coverage prediction endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse

from ...application.repositories import CoverageQuery
from ...domain.coverage import Target
from ...domain.errors import PredictionErrorCode
from ...domain.result import Err
from ..deps import coverage_query
from ..schemas import ConfidenceResponse, PredictionResponse, PredictRequest

router = APIRouter(prefix="/api/v1/coverage", tags=["coverage"])


@router.post(
    "/predict",
    response_model=PredictionResponse,
    status_code=status.HTTP_200_OK,
    summary="Predict LoRa coverage tại 1 điểm",
    responses={
        404: {"description": "Không có gateway phục vụ"},
        422: {"description": "Validation error"},
    },
)
async def predict(
    payload: PredictRequest,
    request: Request,
    service: CoverageQuery = Depends(coverage_query),
) -> PredictionResponse | JSONResponse:
    target = Target(
        latitude=payload.latitude,
        longitude=payload.longitude,
        spreading_factor=payload.spreading_factor,
        frequency_mhz=payload.frequency_mhz,
    )
    result = service.predict(target)

    if isinstance(result, Err):
        # Map domain error → HTTP status (RFC 7807).
        status_code = (
            404
            if result.error.code == PredictionErrorCode.NO_GATEWAY_NEARBY
            else 422
        )
        return JSONResponse(
            status_code=status_code,
            media_type="application/problem+json",
            content={
                "type": "about:blank",
                "title": "Prediction unavailable",
                "status": status_code,
                "detail": result.error.message,
                "instance": str(request.url.path),
                "code": result.error.code.value,
                "traceId": getattr(request.state, "trace_id", None),
            },
        )

    p = result.value
    return PredictionResponse(
        rssi_dbm=p.rssi_dbm,
        snr_db=p.snr_db,
        coverage_status=p.coverage_status.value,  # type: ignore[arg-type]
        serving_gateway_id=p.serving_gateway_id,
        confidence=ConfidenceResponse(
            score=p.confidence.score,
            method=p.confidence.method.value,  # type: ignore[arg-type]
        ),
        model_version=p.model_version,
    )
