"""JWT issuance + verification — HS256 qua python-jose.

Plan-auth-v1 §3.1 hidden: JWT format/secret/TTL/algorithm không lộ ra
interface. Caller (`service.authenticate`) thấy `issue(user, ttl) -> token_str`
và `decode(token) -> Claims`.

Claims minimal:
    sub: str       — user_id (UUID string)
    exp: int       — unix epoch
    iat: int       — unix epoch (issued at; useful nếu sau này blacklist)

KHÔNG cho thêm role/admin/email vào claims — không phải DB-of-truth.
Edge dependency luôn refetch user từ DB khi cần is_admin/disabled (xem
`service.current_user`). Lý do: admin disable user phải có hiệu lực ngay
lần request kế tiếp, không đợi token hết hạn.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from jose import JWTError, jwt
from jose.exceptions import ExpiredSignatureError

from .errors import InvalidCredentials, TokenExpired

_ALGORITHM = "HS256"


@dataclass(frozen=True)
class Claims:
    user_id: UUID
    issued_at: datetime
    expires_at: datetime


def issue(user_id: UUID, *, secret: str, ttl_hours: int) -> tuple[str, datetime]:
    """Encode JWT cho `user_id`. Trả (token, expires_at).

    `expires_at` cần ở interface để caller (route /login) report `expires_in`
    cho client mà không phải decode lại.
    """
    now = datetime.now(UTC)
    exp = now + timedelta(hours=ttl_hours)
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    token = jwt.encode(payload, secret, algorithm=_ALGORITHM)
    return token, exp


def decode(token: str, *, secret: str) -> Claims:
    """Verify signature + exp. Trả Claims hoặc raise.

    Raises:
        TokenExpired       — exp < now
        InvalidCredentials — signature sai, malformed, sub không phải UUID
    """
    try:
        payload = jwt.decode(token, secret, algorithms=[_ALGORITHM])
    except ExpiredSignatureError as e:
        raise TokenExpired("Token expired") from e
    except JWTError as e:
        raise InvalidCredentials("Invalid token") from e

    sub = payload.get("sub")
    iat = payload.get("iat")
    exp = payload.get("exp")
    if not isinstance(sub, str) or not isinstance(iat, int) or not isinstance(exp, int):
        raise InvalidCredentials("Token claims malformed")
    try:
        user_id = UUID(sub)
    except ValueError as e:
        raise InvalidCredentials("Token sub is not UUID") from e

    return Claims(
        user_id=user_id,
        issued_at=datetime.fromtimestamp(iat, tz=UTC),
        expires_at=datetime.fromtimestamp(exp, tz=UTC),
    )
