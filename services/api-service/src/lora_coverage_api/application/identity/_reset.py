"""Password-reset token primitives — single-use opaque token.

Pre-deploy checklist §2. Module deep: SQL, hash, secure RNG, single-use
lifecycle ẩn sau `issue/consume/invalidate_user_unused`.

Token format giống refresh_tokens: `secrets.token_urlsafe(32)` → 43-char
base64url (256-bit entropy). DB store SHA-256 hash; plaintext chỉ xuất hiện
trong email body 1 lần.

Khác `_refresh.py`:
  * Không có family/rotation — reset token là one-shot.
  * `used_at` cột thay vì `revoked` + `rotated_to` — set 1 lần khi consume,
    UPDATE atomic (WHERE used_at IS NULL) bảo đảm single-use ở SQL layer.
  * Trước khi issue mới, invalidate tất cả unused tokens của user — chống
    tấn công "đầy bảng" và đảm bảo link cũ vô hiệu khi user request lại
    (mitigate email-forwarding scenario).
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import Connection, text

from .errors import (
    PasswordResetTokenExpiredError,
    PasswordResetTokenInvalidError,
    PasswordResetTokenUsedError,
)

_TOKEN_BYTES = 32  # 256-bit entropy


def _gen_token() -> str:
    return secrets.token_urlsafe(_TOKEN_BYTES)


def _hash(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


_INSERT = text("""
    INSERT INTO auth.password_reset_tokens
        (user_id, token_hash, expires_at)
    VALUES
        (:user_id, :token_hash, :expires_at)
""")

_SELECT_BY_HASH = text("""
    SELECT id, user_id, expires_at, used_at
    FROM auth.password_reset_tokens
    WHERE token_hash = :token_hash
""")

# Atomic single-use: chỉ update khi used_at IS NULL. RETURNING id để service
# phân biệt "đã consume" (0 row) vs "vừa consume" (1 row) mà không cần SELECT
# lại — chống race condition 2 request consume cùng token cùng lúc.
_MARK_USED = text("""
    UPDATE auth.password_reset_tokens
    SET used_at = now()
    WHERE id = :id AND used_at IS NULL
    RETURNING id
""")

_INVALIDATE_USER_UNUSED = text("""
    UPDATE auth.password_reset_tokens
    SET used_at = now()
    WHERE user_id = :user_id AND used_at IS NULL
""")


@dataclass(frozen=True)
class IssuedResetToken:
    token: str  # plaintext — đặt vào email body, KHÔNG log
    expires_at: datetime
    user_id: UUID


def issue(
    conn: Connection,
    user_id: UUID,
    *,
    ttl_minutes: int,
) -> IssuedResetToken:
    """Issue token mới sau khi invalidate tất cả token unused của user.

    Invalidate-trước là phần `issue` (encapsulate single-active-token
    invariant): caller chỉ cần gọi `issue`, không cần biết cleanup logic.
    """
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
    return IssuedResetToken(token=token, expires_at=expires_at, user_id=user_id)


def consume(conn: Connection, presented_token: str) -> UUID:
    """Validate + mark used atomically. Trả user_id nếu OK.

    Raises:
        PasswordResetTokenInvalidError: token không tồn tại.
        PasswordResetTokenUsedError: token đã consume trước đó.
        PasswordResetTokenExpiredError: quá expires_at.

    Mark-used dùng UPDATE atomic (WHERE used_at IS NULL) — kể cả 2 request
    đồng thời, chỉ 1 cái nhận RETURNING row, cái kia raise Used.
    """
    row = conn.execute(_SELECT_BY_HASH, {"token_hash": _hash(presented_token)}).one_or_none()
    if row is None:
        raise PasswordResetTokenInvalidError("Reset token không tồn tại")

    if row.used_at is not None:
        raise PasswordResetTokenUsedError("Reset token đã được sử dụng")

    if row.expires_at <= datetime.now(UTC):
        raise PasswordResetTokenExpiredError("Reset token đã hết hạn")

    consumed = conn.execute(_MARK_USED, {"id": row.id}).one_or_none()
    if consumed is None:
        # Race: 1 request khác đã consume giữa SELECT và UPDATE.
        raise PasswordResetTokenUsedError("Reset token đã được sử dụng")

    return row.user_id
