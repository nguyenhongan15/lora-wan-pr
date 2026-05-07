"""Identity service — register, authenticate, current_user.

Plan-auth-v1 §3.1. Deep module: 3 method ngoài, ẩn JWT issuance, password
hashing, email canonicalisation, DB queries vào `auth.users`.

Stateless modulo `(secret, ttl_hours)` constructor params. Caller (`edge/deps`)
khởi tạo 1 instance → process. Connection injection per-call để service không
giữ engine handle (consistency với sync/_upsert.py).

`current_user` luôn refetch user từ DB — tuyệt đối không trust claims trong
JWT cho is_admin/disabled. Lý do: admin disable user phải có hiệu lực ngay
lần request kế tiếp.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import Connection, text

from . import _passwords, _tokens
from .errors import (
    EmailAlreadyExists,
    InvalidCredentials,
    UserDisabled,
)


@dataclass(frozen=True)
class User:
    id: UUID
    email: str
    is_admin: bool
    disabled: bool
    created_at: datetime


@dataclass(frozen=True)
class AuthToken:
    access_token: str
    expires_at: datetime
    token_type: str = "bearer"


_INSERT_USER = text("""
    INSERT INTO auth.users (email, password_hash)
    VALUES (:email, :password_hash)
    RETURNING id, email, is_admin, disabled, created_at
""")

_SELECT_USER_BY_EMAIL = text("""
    SELECT id, email, password_hash, is_admin, disabled, created_at
    FROM auth.users
    WHERE email = :email
""")

_SELECT_USER_BY_ID = text("""
    SELECT id, email, is_admin, disabled, created_at
    FROM auth.users
    WHERE id = :user_id
""")


def _canonical_email(email: str) -> str:
    return email.strip().lower()


class IdentityService:
    def __init__(self, *, jwt_secret: str, jwt_ttl_hours: int) -> None:
        self._secret = jwt_secret
        self._ttl_hours = jwt_ttl_hours

    # ── public interface ──────────────────────────────────────────────────

    def register(self, conn: Connection, email: str, password: str) -> User:
        """Tạo user mới với email + password.

        Raises:
            EmailAlreadyExists: email (case-insensitive) đã có trong DB.
        """
        canonical = _canonical_email(email)
        password_hash = _passwords.hash_password(password)
        try:
            row = conn.execute(
                _INSERT_USER,
                {"email": canonical, "password_hash": password_hash},
            ).one()
        except Exception as exc:
            # psycopg unique violation → IntegrityError. Match qua tên
            # constraint thay vì sniff message để robust với pg version.
            if "users_email_key" in str(exc):
                raise EmailAlreadyExists(f"Email '{canonical}' đã tồn tại") from exc
            raise
        return User(
            id=row.id,
            email=row.email,
            is_admin=row.is_admin,
            disabled=row.disabled,
            created_at=row.created_at,
        )

    def authenticate(self, conn: Connection, email: str, password: str) -> AuthToken:
        """Xác thực credential, trả access token nếu OK.

        Raises:
            InvalidCredentials: email không có hoặc password sai.
            UserDisabled: tìm thấy user nhưng `disabled=true`.

        Lý do tách `UserDisabled`: admin cần biết user disable cố tình login
        (audit), và frontend hiển thị message khác với "sai mật khẩu".
        """
        canonical = _canonical_email(email)
        row = conn.execute(_SELECT_USER_BY_EMAIL, {"email": canonical}).one_or_none()
        if row is None:
            # Hash 1 password giả để chống timing attack (so user-exists vs
            # not-exists). Cost rất nhỏ vs bcrypt verify thật.
            _passwords.verify_password(password, _DUMMY_BCRYPT_HASH)
            raise InvalidCredentials("Email hoặc password sai")

        if not _passwords.verify_password(password, row.password_hash):
            raise InvalidCredentials("Email hoặc password sai")

        if row.disabled:
            raise UserDisabled("Tài khoản đã bị vô hiệu hoá")

        token, expires_at = _tokens.issue(
            row.id, secret=self._secret, ttl_hours=self._ttl_hours
        )
        return AuthToken(access_token=token, expires_at=expires_at)

    def current_user(self, conn: Connection, token: str) -> User:
        """Decode JWT + refetch user từ DB.

        Raises:
            InvalidCredentials: token sai signature, malformed, hoặc user_id
                không tồn tại.
            TokenExpired: JWT exp < now.
            UserDisabled: user tồn tại nhưng đã bị disable.
        """
        claims = _tokens.decode(token, secret=self._secret)
        row = conn.execute(
            _SELECT_USER_BY_ID, {"user_id": claims.user_id}
        ).one_or_none()
        if row is None:
            # User bị xoá sau khi token issued.
            raise InvalidCredentials("User không tồn tại")
        if row.disabled:
            raise UserDisabled("Tài khoản đã bị vô hiệu hoá")
        return User(
            id=row.id,
            email=row.email,
            is_admin=row.is_admin,
            disabled=row.disabled,
            created_at=row.created_at,
        )


# Pre-computed dummy bcrypt hash dùng cho timing-attack mitigation. Hash của
# string ngẫu nhiên cố định, work factor 12 — verify trên hash này tốn cùng
# thời gian như verify hash thật, đảm bảo response time login không tiết
# lộ "user tồn tại không".
_DUMMY_BCRYPT_HASH = "$2b$12$LhPqXjY0ekKvvD8xK5wIvuFJqI3bLaIkQbxX0PWeI8dX8y6IM5tlS"
