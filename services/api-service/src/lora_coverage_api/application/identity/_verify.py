"""Email-verification token primitives — single-use opaque token.

Mirror `_reset.py`. Module deep: SQL, hash, secure RNG, single-use lifecycle
ẩn sau `issue/consume`.

Token format giống password_reset_tokens: `secrets.token_urlsafe(32)` →
43-char base64url (256-bit entropy). DB store SHA-256 hash; plaintext chỉ
xuất hiện trong email body 1 lần.

Single-use enforced qua UPDATE atomic (WHERE used_at IS NULL).

Khác `_reset.py`: KHÔNG revoke refresh tokens khi consume — verify email
là augment trust, không phải security event đáng kick session.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import Connection, text

from .errors import (
    EmailVerificationTokenExpiredError,
    EmailVerificationTokenInvalidError,
    EmailVerificationTokenUsedError,
)

_TOKEN_BYTES = 32  # 256-bit entropy


def _gen_token() -> str:
    return secrets.token_urlsafe(_TOKEN_BYTES)


def _hash(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


_INSERT = text("""
    INSERT INTO auth.email_verification_tokens
        (user_id, token_hash, expires_at)
    VALUES
        (:user_id, :token_hash, :expires_at)
""")

_SELECT_BY_HASH = text("""
    SELECT id, user_id, expires_at, used_at
    FROM auth.email_verification_tokens
    WHERE token_hash = :token_hash
""")

_MARK_USED = text("""
    UPDATE auth.email_verification_tokens
    SET used_at = now()
    WHERE id = :id AND used_at IS NULL
    RETURNING id
""")

_INVALIDATE_USER_UNUSED = text("""
    UPDATE auth.email_verification_tokens
    SET used_at = now()
    WHERE user_id = :user_id AND used_at IS NULL
""")


@dataclass(frozen=True)
class IssuedVerifyToken:
    token: str  # plaintext — đặt vào email body, KHÔNG log
    expires_at: datetime
    user_id: UUID


def issue(
    conn: Connection,
    user_id: UUID,
    *,
    ttl_minutes: int,
) -> IssuedVerifyToken:
    """Issue token mới sau khi invalidate tất cả token unused của user."""
    conn.execute(_INVALIDATE_USER_UNUSED, {"user_id": user_id})
    token = _gen_token()
    expires_at = datetime.now(UTC) + timedelta(minutes=ttl_minutes)
    conn.execute(
        _INSERT,
        {
            "user_id": user_id,
            "token_hash": _hash(token),
            "expires_at": expires_at,
        },
    )
    return IssuedVerifyToken(token=token, expires_at=expires_at, user_id=user_id)


def consume(conn: Connection, presented_token: str) -> UUID:
    """Validate + mark used atomically. Trả user_id nếu OK.

    Raises:
        EmailVerificationTokenInvalidError: token không tồn tại.
        EmailVerificationTokenUsedError: token đã consume trước đó.
        EmailVerificationTokenExpiredError: quá expires_at.
    """
    row = conn.execute(_SELECT_BY_HASH, {"token_hash": _hash(presented_token)}).one_or_none()
    if row is None:
        raise EmailVerificationTokenInvalidError("Token xác thực email không tồn tại")

    if row.used_at is not None:
        raise EmailVerificationTokenUsedError("Token xác thực email đã được sử dụng")

    if row.expires_at <= datetime.now(UTC):
        raise EmailVerificationTokenExpiredError("Token xác thực email đã hết hạn")

    consumed = conn.execute(_MARK_USED, {"id": row.id}).one_or_none()
    if consumed is None:
        raise EmailVerificationTokenUsedError("Token xác thực email đã được sử dụng")

    user_id: UUID = row.user_id
    return user_id
