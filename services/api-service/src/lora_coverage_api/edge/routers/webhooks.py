"""ChirpStack per-user webhook ingest endpoint.

Path token mapping per-user (plan ChirpStack per-user webhook ingest):
URL = `/api/v1/webhooks/chirpstack/source/{token}`. Token plaintext do
backend cấp lúc user link source; ChirpStack HTTP Integration cấu hình
URL chứa token; mỗi uplink push về đây mang đúng provenance của user đó.

Resolve flow:
  1. slowapi rate limit per-token → chặn 1 misconfigured ChirpStack flood.
  2. WebhookAuthService.resolve(token) → WebhookContext{user_id, ls_id,
     source_type, contribute} hoặc raise 401.
  3. ChirpstackWebhookService.ingest_uplink(payload, context) → idempotent
     write vào ts.survey_quarantine với provenance đầy đủ.

Endpoint legacy `/chirpstack/{token}` + env CHIRPSTACK_WEBHOOK_TOKENS đã
remove (plan §2 quyết định "migrate hẳn"). Admin re-link sau deploy để
được cấp URL mới.

Body: ChirpStack uplink JSON nguyên gốc — Pydantic không validate shape
(`dict[str, Any]`) vì adapter là pure function đã validate từng field
(rejected_reasons list[str]).

Trả 202 Accepted: insert có thể bị skip do dedup — không phải "0 rỗng = lỗi".
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, Request, status

from ...application.chirpstack_webhook_service import ChirpstackWebhookService
from ...application.webhook_auth import WebhookAuthService
from ...config import get_settings
from ..deps import _engine, survey_repository, webhook_auth_service
from ..rate_limit import limiter
from ..schemas import WebhookIngestResponse

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])

logger = structlog.get_logger("lora_coverage_api.webhooks")

# Settings resolve 1 lần — decorator @limiter.limit cần string lúc import.
# Test override env trước khi import router (consistent với auth.py).
_settings = get_settings()


def _webhook_token_key(request: Request) -> str:
    """slowapi key_func: rate-limit bucket = path token.

    Misconfigured ChirpStack flooding 1 token KHÔNG ảnh hưởng tới user khác.
    Token được hash bởi slowapi storage trước khi dùng làm key — plaintext
    không leak trong storage backend.

    Fallback: nếu path không có token (route mismatch), key = client IP để
    tránh None → key_func crash.
    """
    token = request.path_params.get("token")
    if isinstance(token, str) and token:
        return f"webhook:{token}"
    return f"webhook:ip:{request.client.host if request.client else 'unknown'}"


def _webhook_service() -> ChirpstackWebhookService:
    return ChirpstackWebhookService(repository=survey_repository())


@router.post(
    "/chirpstack/source/{token}",
    response_model=WebhookIngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="ChirpStack uplink ingest (per-user webhook URL)",
    responses={
        401: {"description": "Invalid or revoked webhook token"},
        429: {"description": "Rate limit exceeded for this token"},
    },
)
@limiter.limit(_settings.chirpstack_webhook_rate_limit, key_func=_webhook_token_key)
async def chirpstack_webhook(
    request: Request,
    token: str,
    payload: dict[str, Any],
    auth: WebhookAuthService = Depends(webhook_auth_service),
    service: ChirpstackWebhookService = Depends(_webhook_service),
) -> WebhookIngestResponse:
    with _engine().begin() as conn:
        context = auth.resolve(conn, token)

    receipt = service.ingest_uplink(payload, context)

    # Log với trace_id để correlate khi debug retry/dedup. Token KHÔNG bao
    # giờ log — context.linked_source_id là handle public an toàn.
    logger.info(
        "chirpstack_uplink_ingested",
        linked_source_id=str(context.linked_source_id),
        user_id=str(context.user_id),
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
