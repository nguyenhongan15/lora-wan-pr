"""Refresh-token primitives — opaque token + DB-backed rotation chain.

Plan-auth-v2 step 2. Module deep: SQL, hash, secure RNG, rotation lifecycle
ẩn sau `issue/rotate/revoke`.

Token format: `secrets.token_urlsafe(32)` → 43-char base64url (256-bit entropy).
DB store: SHA-256 hash. Cookie carry plaintext.

Reuse detection: nếu rotate() nhận 1 token đã có `rotated_to IS NOT NULL`,
revoke toàn bộ family (cả attacker và user) — đây là tín hiệu token theft.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, text

from .errors import (
    RefreshTokenExpiredError,
    RefreshTokenInvalidError,
    RefreshTokenReusedError,
)

_TOKEN_BYTES = 32  # 256-bit entropy


def _gen_token() -> str:
    return secrets.token_urlsafe(_TOKEN_BYTES)


def _hash(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


_INSERT = text("""
    INSERT INTO auth.refresh_tokens
        (user_id, token_hash, family_id, expires_at, user_agent, ip)
    VALUES
        (:user_id, :token_hash, :family_id, :expires_at, :user_agent, :ip)
    RETURNING id
""")

_SELECT_BY_HASH = text("""
    SELECT id, user_id, family_id, expires_at, rotated_to, revoked
    FROM auth.refresh_tokens
    WHERE token_hash = :token_hash
""")

_MARK_ROTATED = text("""
    UPDATE auth.refresh_tokens
    SET rotated_to = :new_id
    WHERE id = :old_id
""")

_REVOKE_BY_ID = text("""
    UPDATE auth.refresh_tokens
    SET revoked = true, revoked_at = now()
    WHERE id = :id AND revoked = false
""")

_REVOKE_FAMILY = text("""
    UPDATE auth.refresh_tokens
    SET revoked = true, revoked_at = now()
    WHERE family_id = :family_id AND revoked = false
""")


@dataclass(frozen=True)
class IssuedRefresh:
    token: str  # plaintext — đặt vào cookie, KHÔNG log
    expires_at: datetime
    user_id: UUID
    family_id: UUID


def issue(
    conn: Connection,
    user_id: UUID,
    *,
    ttl_days: int,
    user_agent: str | None = None,
    ip: str | None = None,
) -> IssuedRefresh:
    """First-issue refresh token cho 1 login session mới (tạo family mới)."""
    token = _gen_token()
    family_id = uuid4()
    expires_at = datetime.now(UTC) + timedelta(days=ttl_days)
    conn.execute(
        _INSERT,
        {
            "user_id": user_id,
            "token_hash": _hash(token),
            "family_id": family_id,
            "expires_at": expires_at,
            "user_agent": user_agent,
            "ip": ip,
        },
    )
    return IssuedRefresh(token=token, expires_at=expires_at, user_id=user_id, family_id=family_id)


def rotate(
    conn: Connection,
    presented_token: str,
    *,
    engine: Engine,
    ttl_days: int,
    user_agent: str | None = None,
    ip: str | None = None,
) -> IssuedRefresh:
    """Rotate: validate → issue new in same family → mark parent rotated.

    `engine` cần thiết để revoke_family chạy trong INNER transaction riêng:
    raise RefreshTokenReusedError trên outer conn của route sẽ rollback, mất
    revoke_family. Inner txn commit ngay trước khi raise → family thật sự
    bị revoke kể cả khi route rollback.

    Raises:
        RefreshTokenInvalidError: token không tồn tại hoặc đã revoked.
        RefreshTokenReusedError:  token đã từng rotated (theft signal) →
            revoke family trước khi raise.
        RefreshTokenExpiredError: token còn hợp lệ nhưng quá expires_at.
    """
    row = conn.execute(_SELECT_BY_HASH, {"token_hash": _hash(presented_token)}).one_or_none()
    if row is None:
        raise RefreshTokenInvalidError("Refresh token không tồn tại")

    # Reuse detection PHẢI check trước revoked vì: nếu family đã revoke do
    # theft (revoked=true), ta vẫn muốn báo lý do "reused" để client biết.
    if row.rotated_to is not None:
        # Token này đã được dùng rotate trước đó. Ai cầm nó lần 2 = clone.
        # Inner txn để revoke persist độc lập với route rollback.
        with engine.begin() as wconn:
            wconn.execute(_REVOKE_FAMILY, {"family_id": row.family_id})
        raise RefreshTokenReusedError("Refresh token đã được dùng. Toàn bộ phiên đã bị thu hồi.")

    if row.revoked:
        raise RefreshTokenInvalidError("Refresh token đã bị thu hồi")

    now = datetime.now(UTC)
    if row.expires_at <= now:
        raise RefreshTokenExpiredError("Refresh token đã hết hạn")

    # Issue child in same family.
    new_token = _gen_token()
    new_expires_at = now + timedelta(days=ttl_days)
    new_id_row = conn.execute(
        _INSERT,
        {
            "user_id": row.user_id,
            "token_hash": _hash(new_token),
            "family_id": row.family_id,
            "expires_at": new_expires_at,
            "user_agent": user_agent,
            "ip": ip,
        },
    ).one()
    conn.execute(_MARK_ROTATED, {"old_id": row.id, "new_id": new_id_row.id})

    return IssuedRefresh(
        token=new_token,
        expires_at=new_expires_at,
        user_id=row.user_id,
        family_id=row.family_id,
    )


def revoke(conn: Connection, presented_token: str) -> bool:
    """Revoke 1 token (logout). Idempotent: token không tồn tại = no-op.

    Trả True nếu vừa revoke; False nếu đã revoked / không tồn tại.
    """
    row = conn.execute(_SELECT_BY_HASH, {"token_hash": _hash(presented_token)}).one_or_none()
    if row is None or row.revoked:
        return False
    conn.execute(_REVOKE_BY_ID, {"id": row.id})
    return True
