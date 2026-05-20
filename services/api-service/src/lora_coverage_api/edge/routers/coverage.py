"""Coverage prediction endpoints."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse

from ...application.prediction_service import PredictionOrchestrator
from ...application.repositories import AddressResolution
from ...config import get_settings
from ...domain.address import Address
from ...domain.coverage import Target, TerminalEnvironment
from ...domain.errors import AddressLookupErrorCode, PredictionErrorCode
from ...domain.result import Err
from ..deps import address_resolution, prediction_orchestrator
from ..metrics import LOOKUP_LATENCY_SECONDS, LOOKUP_SLO_VIOLATIONS_TOTAL
from ..rate_limit import limiter
from ..schemas import (
    AddressLookupRequest,
    ConfidenceResponse,
    CoverageBatchItem,
    CoverageBatchItemResult,
    CoverageBatchRequest,
    CoverageBatchResponse,
    CoverageLookupResponse,
    LinkBudgetResponse,
    PredictionResponse,
    PredictRequest,
    ResolvedAddressResponse,
)

router = APIRouter(prefix="/api/v1/coverage", tags=["coverage"])

_settings = get_settings()


@router.post(
    "/predict",
    response_model=PredictionResponse,
    status_code=status.HTTP_200_OK,
    summary="Predict LoRa coverage tại 1 điểm",
    responses={
        404: {"description": "Không có gateway phục vụ"},
        422: {"description": "Validation error"},
        429: {"description": "Rate limit exceeded"},
    },
)
@limiter.limit(_settings.coverage_predict_rate_limit)
async def predict(
    request: Request,
    payload: PredictRequest,
    service: PredictionOrchestrator = Depends(prediction_orchestrator),
) -> PredictionResponse | JSONResponse:
    target = _build_target(
        latitude=payload.latitude,
        longitude=payload.longitude,
        sf=payload.spreading_factor,
        freq_mhz=payload.frequency_mhz,
        tx_power_dbm=payload.tx_power_dbm,
        tx_antenna_gain_dbi=payload.tx_antenna_gain_dbi,
        rx_antenna_gain_dbi=payload.rx_antenna_gain_dbi,
        rx_sensitivity_dbm=payload.rx_sensitivity_dbm,
        environment=payload.environment,
    )
    result = await service.predict(target)

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


def _build_target(
    *,
    latitude: float,
    longitude: float,
    sf: int,
    freq_mhz: float,
    tx_power_dbm: float | None = None,
    tx_antenna_gain_dbi: float | None = None,
    rx_antenna_gain_dbi: float | None = None,
    rx_sensitivity_dbm: float | None = None,
    environment: TerminalEnvironment = "outdoor",
) -> Target:
    """Construct Target. None field → fallback Settings env defaults.

    rx_sensitivity_dbm None đi thẳng vào Target → application layer derive từ
    SF table (không expose qua env vì đã hardcode SX1276 datasheet).
    """
    settings = get_settings()
    return Target(
        latitude=latitude,
        longitude=longitude,
        spreading_factor=sf,
        frequency_mhz=freq_mhz,
        tx_power_dbm=tx_power_dbm
        if tx_power_dbm is not None
        else settings.default_device_tx_power_dbm,
        tx_antenna_gain_dbi=tx_antenna_gain_dbi
        if tx_antenna_gain_dbi is not None
        else settings.default_device_tx_antenna_gain_dbi,
        rx_antenna_gain_dbi=rx_antenna_gain_dbi
        if rx_antenna_gain_dbi is not None
        else settings.default_device_rx_antenna_gain_dbi,
        rx_sensitivity_dbm=rx_sensitivity_dbm,
        environment=environment,
    )


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
            epistemic_variance_db2=p.confidence.epistemic_variance_db2,  # type: ignore[attr-defined]
            aleatoric_variance_db2=p.confidence.aleatoric_variance_db2,  # type: ignore[attr-defined]
        ),
        model_version=p.model_version,  # type: ignore[attr-defined]
        recommended_sf=p.recommended_sf,  # type: ignore[attr-defined]
        uplink=LinkBudgetResponse(
            rssi_dbm=p.uplink_rssi_dbm,  # type: ignore[attr-defined]
            snr_db=p.uplink_snr_db,  # type: ignore[attr-defined]
            margin_db=p.uplink_margin_db,  # type: ignore[attr-defined]
            status=p.uplink_status.value,  # type: ignore[attr-defined]
        ),
        downlink=LinkBudgetResponse(
            rssi_dbm=p.downlink_rssi_dbm,  # type: ignore[attr-defined]
            snr_db=p.downlink_snr_db,  # type: ignore[attr-defined]
            margin_db=p.downlink_margin_db,  # type: ignore[attr-defined]
            status=p.downlink_status.value,  # type: ignore[attr-defined]
        ),
        bottleneck=p.bottleneck,  # type: ignore[attr-defined]
        path_loss_db=p.path_loss_db,  # type: ignore[attr-defined]
        distance_to_serving_gateway_km=p.distance_to_serving_gateway_km,  # type: ignore[attr-defined]
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
        429: {"description": "Rate limit exceeded hoặc geocoding rate-limited"},
        503: {"description": "Geocoding provider không khả dụng"},
    },
)
@limiter.limit(_settings.coverage_lookup_rate_limit)
async def lookup(
    request: Request,
    payload: AddressLookupRequest,
    geocoder: AddressResolution = Depends(address_resolution),
    service: PredictionOrchestrator = Depends(prediction_orchestrator),
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
    # AddressLookupRequest chưa expose device-side overrides — dùng Target defaults.
    target = _build_target(
        latitude=resolved.latitude,
        longitude=resolved.longitude,
        sf=payload.spreading_factor,
        freq_mhz=payload.frequency_mhz,
    )
    pred_result = await service.predict(target)
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
        429: {"description": "Rate limit exceeded"},
    },
)
@limiter.limit(_settings.coverage_batch_rate_limit)
async def lookup_batch(
    request: Request,
    payload: CoverageBatchRequest,
    geocoder: AddressResolution = Depends(address_resolution),
    service: PredictionOrchestrator = Depends(prediction_orchestrator),
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
        result = await _process_batch_item(
            item, payload.spreading_factor, payload.frequency_mhz, geocoder, service
        )
        results.append(result)
        if result.status == "ok":
            ok += 1
        else:
            err += 1

    return CoverageBatchResponse(items=results, ok_count=ok, error_count=err)


async def _process_batch_item(
    item: CoverageBatchItem,
    sf: int,
    freq_mhz: float,
    geocoder: AddressResolution,
    service: PredictionOrchestrator,
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
            provider="cache",
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

    target = _build_target(
        latitude=resolved_dto.latitude,
        longitude=resolved_dto.longitude,
        sf=sf,
        freq_mhz=freq_mhz,
    )
    pred_result = await service.predict(target)
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
