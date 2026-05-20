"""WebhookAuthService — resolve per-user webhook token cho ingest endpoint.

Plan ChirpStack per-user webhook ingest. Deep module: 1 method công khai
`resolve(token, conn) -> WebhookContext` che hash, query DB, validate user
state. Caller (webhook router) chỉ thấy context hoặc 401 — không biết
HMAC, không biết SQL.

Stateless modulo `cipher` constructor param. Reuse `CredentialCipher.
webhook_token_hash` để cùng security-domain với credential fingerprint
(plan §1).

KHÔNG audit-log token plaintext (không bao giờ thấy). Log token_prefix
6 char + user_id + linked_source_id để debug; full plaintext stays at
client side (ChirpStack HTTP Integration URL).
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import structlog
from sqlalchemy import Connection, text

from .errors import ApplicationError
from .linking._crypto import CredentialCipher

logger = structlog.get_logger("lora_coverage_api.webhook_auth")


class WebhookAuthError(ApplicationError):
    """401 generic: không phân biệt token sai/hết hạn/source paused/user disabled.

    Plan §"Define errors out of existence": leak ít nhất có thể qua wire.
    Server-side log full reason để debug.
    """

    http_status = 401
    code = "webhook_auth_failed"


@dataclass(frozen=True, slots=True)
class WebhookContext:
    """Resolve result — pass thẳng vào ChirpstackWebhookService.ingest_uplink.

    `contribute` đọc 1 lần lúc resolve (snapshot). Toggle giữa lúc resolve và
    insert không re-check — chấp nhận race vì backfill cover trường hợp opt-in
    sau (xem LinkingService._backfill_to_training).
    """

    user_id: UUID
    linked_source_id: UUID
    source_type: str
    contribute: bool


_SELECT_BY_TOKEN_HASH = text("""
    SELECT
        ls.id              AS linked_source_id,
        ls.user_id         AS user_id,
        ls.source_type     AS source_type,
        ls.status          AS status,
        ls.contribute_to_community AS contribute,
        u.disabled         AS user_disabled
    FROM auth.linked_sources ls
    JOIN auth.users u ON u.id = ls.user_id
    WHERE ls.webhook_token_hash = :h
""")


# Length floor cho path token. `secrets.token_urlsafe(32)` ra ~43 char base64;
# bất kỳ chuỗi ngắn hơn ~30 vào path = không thể là token hợp lệ → reject
# trước khi hit DB (giảm log noise + DoS surface). Plan §"Input Validation —
# Reject Before Business Logic".
_MIN_TOKEN_LEN = 32


class WebhookAuthService:
    def __init__(self, *, cipher: CredentialCipher) -> None:
        self._cipher = cipher

    def resolve(self, conn: Connection, token: str) -> WebhookContext:
        """Validate token → trả WebhookContext. Raise WebhookAuthError nếu fail.

        Steps:
          1. Length check — quick reject token quá ngắn.
          2. HMAC-SHA256(token) → bytea hash.
          3. SELECT WHERE webhook_token_hash = :h JOIN users.
          4. Check status='active' (paused source không nhận webhook nữa).
          5. Check user.disabled=false.
        """
        if not token or len(token) < _MIN_TOKEN_LEN:
            logger.info("webhook_token_too_short", token_len=len(token) if token else 0)
            raise WebhookAuthError("invalid webhook token")

        token_hash = self._cipher.webhook_token_hash(token)
        row = conn.execute(_SELECT_BY_TOKEN_HASH, {"h": token_hash}).one_or_none()
        if row is None:
            logger.info("webhook_token_unknown", token_prefix=token[:6])
            raise WebhookAuthError("invalid webhook token")

        if row.status != "active":
            logger.info(
                "webhook_source_not_active",
                linked_source_id=str(row.linked_source_id),
                status=row.status,
            )
            raise WebhookAuthError("invalid webhook token")

        if row.user_disabled:
            logger.info(
                "webhook_user_disabled",
                user_id=str(row.user_id),
                linked_source_id=str(row.linked_source_id),
            )
            raise WebhookAuthError("invalid webhook token")

        return WebhookContext(
            user_id=row.user_id,
            linked_source_id=row.linked_source_id,
            source_type=row.source_type,
            contribute=bool(row.contribute),
        )


__all__ = ["WebhookAuthError", "WebhookAuthService", "WebhookContext"]
