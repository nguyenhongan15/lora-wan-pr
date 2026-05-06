"""ChirpStack network-server webhook endpoint.

Path-based token auth: ChirpStack tự cấu hình URL `/api/v1/webhooks/chirpstack/{token}`.
Token allowlist + uploader mapping nằm ở env `CHIRPSTACK_WEBHOOK_TOKENS`.

Body: ChirpStack uplink JSON nguyên gốc (rxInfo[], txInfo, object{}, ...).
Service xử lý qua ChirpstackWebhookService → SurveyRepo.write_quarantine_idempotent.

Trả 202 Accepted vì insert có thể bị skip do dedup — không phải "0 rỗng = lỗi".
"""

from __future__ import annotations

import secrets
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status

from ...application.chirpstack_webhook_service import ChirpstackWebhookService
from ...config import Settings
from ...domain.survey import UploaderId
from ..deps import settings_dep, survey_repository
from ..schemas import WebhookIngestResponse

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])

logger = structlog.get_logger("lora_coverage_api.webhooks")


def _resolve_token(token: str, settings: Settings) -> UploaderId:
    """Constant-time match token → uploader. 401 nếu không hợp lệ.

    Theo rule-design-security.md §allowlist: chỉ accept token có trong map.
    Dùng `secrets.compare_digest` cho từng key để tránh timing attack.
    """
    token_map = settings.chirpstack_webhook_token_map
    if not token_map:
        # Production phải config; nếu thiếu config thì 503 cho rõ.
        raise HTTPException(
            status_code=503,
            detail="ChirpStack webhook chưa được cấu hình.",
        )
    matched: UploaderId | None = None
    for known_token, uploader_uuid in token_map.items():
        if secrets.compare_digest(known_token, token):
            matched = UploaderId(uploader_uuid)
            # Không break — giữ constant-time tương đối (so với map nhỏ là đủ).
    if matched is None:
        raise HTTPException(status_code=401, detail="invalid webhook token")
    return matched


def webhook_service() -> ChirpstackWebhookService:
    return ChirpstackWebhookService(repository=survey_repository())


@router.post(
    "/chirpstack/{token}",
    response_model=WebhookIngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="ChirpStack uplink ingest (network-server webhook)",
    responses={
        401: {"description": "Invalid webhook token"},
        503: {"description": "Webhook tokens not configured"},
    },
)
async def chirpstack_webhook(
    token: str,
    payload: dict[str, Any],
    request: Request,
    settings: Settings = Depends(settings_dep),
    service: ChirpstackWebhookService = Depends(webhook_service),
) -> WebhookIngestResponse:
    uploader_id = _resolve_token(token, settings)

    receipt = service.ingest_uplink(payload, uploader_id)

    # Log với trace_id để correlate khi debug retry/dedup.
    logger.info(
        "chirpstack_uplink_ingested",
        accepted=receipt.accepted_count,
        inserted=receipt.inserted_count,
        rejected=receipt.rejected_count,
        dedup_id=payload.get("deduplicationId"),
        device=(payload.get("deviceInfo") or {}).get("devEui"),
        trace_id=getattr(request.state, "trace_id", None),
    )

    return WebhookIngestResponse(
        accepted_count=receipt.accepted_count,
        inserted_count=receipt.inserted_count,
        rejected_count=receipt.rejected_count,
        rejected_reasons=receipt.rejected_reasons[:10],  # cap để response gọn
    )
