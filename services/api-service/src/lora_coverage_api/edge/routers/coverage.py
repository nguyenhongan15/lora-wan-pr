"""Coverage prediction endpoints."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse

from ...application.repositories import AddressResolution, CoverageQuery
from ...config import get_settings
from ...domain.address import Address
from ...domain.coverage import Target
from ...domain.errors import AddressLookupErrorCode, PredictionErrorCode
from ...domain.result import Err
from ..deps import address_resolution, coverage_query
from ..metrics import LOOKUP_LATENCY_SECONDS, LOOKUP_SLO_VIOLATIONS_TOTAL
from ..schemas import (
    AddressLookupRequest,
    ConfidenceResponse,
    CoverageBatchItem,
    CoverageBatchItemResult,
    CoverageBatchRequest,
    CoverageBatchResponse,
    CoverageLookupResponse,
    PredictionResponse,
    PredictRequest,
    ResolvedAddressResponse,
)

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
        status_code = 404 if result.error.code == PredictionErrorCode.NO_GATEWAY_NEARBY else 422
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

    return _to_prediction_response(result.value)


def _to_prediction_response(p: object) -> PredictionResponse:
    """Map domain Prediction → wire schema."""
    # Lazy attr access — tránh import cycle với domain ở module top.
    return PredictionResponse(
        rssi_dbm=p.rssi_dbm,  # type: ignore[attr-defined]
        snr_db=p.snr_db,  # type: ignore[attr-defined]
        coverage_status=p.coverage_status.value,  # type: ignore[attr-defined]
        serving_gateway_id=p.serving_gateway_id,  # type: ignore[attr-defined]
        confidence=ConfidenceResponse(
            score=p.confidence.score,  # type: ignore[attr-defined]
            method=p.confidence.method.value,  # type: ignore[attr-defined]
        ),
        model_version=p.model_version,  # type: ignore[attr-defined]
        recommended_sf=p.recommended_sf,  # type: ignore[attr-defined]
    )


_ADDRESS_ERR_TO_STATUS = {
    AddressLookupErrorCode.NOT_FOUND: 404,
    AddressLookupErrorCode.OUT_OF_REGION: 422,
    AddressLookupErrorCode.PROVIDER_UNAVAILABLE: 503,
    AddressLookupErrorCode.RATE_LIMITED: 429,
}


@router.post(
    "/lookup",
    response_model=CoverageLookupResponse,
    status_code=status.HTTP_200_OK,
    summary="Lookup coverage theo địa chỉ (F2 funnel)",
    responses={
        404: {"description": "Không tìm thấy địa chỉ hoặc không có gateway"},
        422: {"description": "Địa chỉ ngoài VN hoặc validation"},
        429: {"description": "Geocoding rate-limited"},
        503: {"description": "Geocoding provider không khả dụng"},
    },
)
async def lookup(
    payload: AddressLookupRequest,
    request: Request,
    geocoder: AddressResolution = Depends(address_resolution),
    service: CoverageQuery = Depends(coverage_query),
) -> CoverageLookupResponse | JSONResponse:
    # F2 SLA §8.2: P95 < 3s end-to-end. Đo từ entry endpoint, ghi vào
    # LOOKUP_LATENCY_SECONDS với label provider+outcome để alert được tách.
    started = time.perf_counter()
    provider_label = "unknown"

    def _record(outcome: str) -> None:
        elapsed = time.perf_counter() - started
        LOOKUP_LATENCY_SECONDS.labels(provider_label, outcome).observe(elapsed)
        if elapsed > get_settings().lookup_slo_seconds:
            LOOKUP_SLO_VIOLATIONS_TOTAL.labels(provider_label, outcome).inc()

    addr_result = geocoder.lookup(Address(raw=payload.address))
    if isinstance(addr_result, Err):
        status_code = _ADDRESS_ERR_TO_STATUS.get(addr_result.error.code, 422)
        # Provider không xác định được khi geocode fail → giữ "unknown".
        _record("error_geocode")
        return JSONResponse(
            status_code=status_code,
            media_type="application/problem+json",
            content={
                "type": "about:blank",
                "title": "Address lookup failed",
                "status": status_code,
                "detail": addr_result.error.message,
                "instance": str(request.url.path),
                "code": addr_result.error.code.value,
                "traceId": getattr(request.state, "trace_id", None),
            },
        )

    resolved = addr_result.value
    provider_label = resolved.provider.value
    target = Target(
        latitude=resolved.latitude,
        longitude=resolved.longitude,
        spreading_factor=payload.spreading_factor,
        frequency_mhz=payload.frequency_mhz,
    )
    pred_result = service.predict(target)
    if isinstance(pred_result, Err):
        status_code = (
            404 if pred_result.error.code == PredictionErrorCode.NO_GATEWAY_NEARBY else 422
        )
        _record("error_predict")
        return JSONResponse(
            status_code=status_code,
            media_type="application/problem+json",
            content={
                "type": "about:blank",
                "title": "Prediction unavailable",
                "status": status_code,
                "detail": pred_result.error.message,
                "instance": str(request.url.path),
                "code": pred_result.error.code.value,
                "traceId": getattr(request.state, "trace_id", None),
                # Dù prediction fail, vẫn echo địa chỉ đã resolve để client
                # có thể vẽ marker / hiển thị "không có sóng tại đây".
                "resolvedAddress": {
                    "latitude": resolved.latitude,
                    "longitude": resolved.longitude,
                    "displayName": resolved.display_name,
                    "provider": resolved.provider.value,
                },
            },
        )

    _record("ok")
    return CoverageLookupResponse(
        address=ResolvedAddressResponse(
            latitude=resolved.latitude,
            longitude=resolved.longitude,
            display_name=resolved.display_name,
            provider=resolved.provider.value,
            confidence=resolved.confidence,
        ),
        prediction=_to_prediction_response(pred_result.value),
    )


@router.post(
    "/batch",
    response_model=CoverageBatchResponse,
    status_code=status.HTTP_200_OK,
    summary="Bulk coverage lookup (≤500 items) — IoT/SI use case",
    responses={
        422: {"description": "Validation error (malformed batch)"},
    },
)
async def lookup_batch(
    payload: CoverageBatchRequest,
    geocoder: AddressResolution = Depends(address_resolution),
    service: CoverageQuery = Depends(coverage_query),
) -> CoverageBatchResponse:
    """Mỗi item được xử lý độc lập: 1 item lỗi không làm fail cả batch.

    Per item rule:
      * có lat/lng           → predict trực tiếp
      * có address (text)    → geocode → predict
      * cả hai/không có gì   → error item, không nhận lat/lng = None khi address rỗng
    """
    results: list[CoverageBatchItemResult] = []
    ok = 0
    err = 0

    for item in payload.items:
        result = _process_batch_item(
            item, payload.spreading_factor, payload.frequency_mhz, geocoder, service
        )
        results.append(result)
        if result.status == "ok":
            ok += 1
        else:
            err += 1

    return CoverageBatchResponse(items=results, ok_count=ok, error_count=err)


def _process_batch_item(
    item: CoverageBatchItem,
    sf: int,
    freq_mhz: float,
    geocoder: AddressResolution,
    service: CoverageQuery,
) -> CoverageBatchItemResult:
    has_coords = item.latitude is not None and item.longitude is not None
    has_addr = bool(item.address and item.address.strip())

    if not has_coords and not has_addr:
        return CoverageBatchItemResult(
            label=item.label,
            status="error",
            error_code="INPUT_MISSING",
            error_message="Item phải có address HOẶC latitude+longitude.",
        )

    resolved_dto: ResolvedAddressResponse | None = None
    if has_coords:
        # User-supplied coords — không geocode reverse, dùng label hoặc tọa độ.
        lat = item.latitude
        lng = item.longitude
        assert lat is not None and lng is not None
        resolved_dto = ResolvedAddressResponse(
            latitude=lat,
            longitude=lng,
            display_name=item.label or f"{lat:.5f}, {lng:.5f}",
            provider="postgres",
            confidence=1.0,
        )
    else:
        addr_result = geocoder.lookup(Address(raw=item.address or ""))
        if isinstance(addr_result, Err):
            return CoverageBatchItemResult(
                label=item.label,
                status="error",
                error_code=addr_result.error.code.value,
                error_message=addr_result.error.message,
            )
        resolved = addr_result.value
        resolved_dto = ResolvedAddressResponse(
            latitude=resolved.latitude,
            longitude=resolved.longitude,
            display_name=resolved.display_name,
            provider=resolved.provider.value,
            confidence=resolved.confidence,
        )

    target = Target(
        latitude=resolved_dto.latitude,
        longitude=resolved_dto.longitude,
        spreading_factor=sf,
        frequency_mhz=freq_mhz,
    )
    pred_result = service.predict(target)
    if isinstance(pred_result, Err):
        return CoverageBatchItemResult(
            label=item.label,
            status="error",
            address=resolved_dto,
            error_code=pred_result.error.code.value,
            error_message=pred_result.error.message,
        )

    return CoverageBatchItemResult(
        label=item.label,
        status="ok",
        address=resolved_dto,
        prediction=_to_prediction_response(pred_result.value),
    )
