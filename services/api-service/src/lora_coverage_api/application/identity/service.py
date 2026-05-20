"""Identity service — register, authenticate, current_user, refresh_session.

Plan-auth-v1 §3.1 + plan-auth-v2 step 2. Deep module: 5 method ngoài, ẩn JWT
issuance, password hashing, email canonicalisation, refresh token rotation,
DB queries vào `auth.users` + `auth.refresh_tokens`.

`current_user` luôn refetch user từ DB — tuyệt đối không trust claims trong
JWT cho is_admin/disabled. Lý do: admin disable user phải có hiệu lực ngay
lần request kế tiếp.

`refresh_session` cũng refetch user — đảm bảo user bị disable sau khi login
sẽ không refresh được phiên.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import Connection, Engine, text

from . import _passwords, _refresh, _reset, _tokens
from ._mailer import Mailer
from .errors import (
    AccountLockedError,
    EmailAlreadyExistsError,
    InvalidCredentialsError,
    UserDisabledError,
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


@dataclass(frozen=True)
class AuthSession:
    """Cặp access + refresh token issued cho 1 login/refresh.

    Plan-auth-v2: access token đi qua Authorization header (frontend hold trong
    memory hoặc localStorage), refresh token đi qua HttpOnly cookie (frontend
    KHÔNG đọc được — chống XSS exfiltration).
    """

    access_token: str
    access_expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime
    token_type: str = "bearer"


_INSERT_USER = text("""
    INSERT INTO auth.users (email, password_hash)
    VALUES (:email, :password_hash)
    RETURNING id, email, is_admin, disabled, created_at
""")

_SELECT_USER_BY_EMAIL = text("""
    SELECT id, email, password_hash, is_admin, disabled, created_at,
           failed_login_count, locked_until
    FROM auth.users
    WHERE email = :email
""")

_SELECT_USER_BY_ID = text("""
    SELECT id, email, is_admin, disabled, created_at
    FROM auth.users
    WHERE id = :user_id
""")

# Login-failure counter UPDATE statements (plan-auth-v2 step 1). Mỗi lần ghi
# chạy trong inner transaction riêng (xem `authenticate`) để counter persist
# kể cả khi outer transaction của route rollback do raise.
_UPDATE_LOGIN_FAILURE = text("""
    UPDATE auth.users
    SET failed_login_count = failed_login_count + 1
    WHERE id = :user_id
    RETURNING failed_login_count
""")

_UPDATE_LOGIN_LOCK = text("""
    UPDATE auth.users
    SET locked_until = :locked_until,
        failed_login_count = 0
    WHERE id = :user_id
""")

_UPDATE_LOGIN_SUCCESS = text("""
    UPDATE auth.users
    SET failed_login_count = 0,
        locked_until = NULL
    WHERE id = :user_id
""")

_UPDATE_PASSWORD = text("""
    UPDATE auth.users
    SET password_hash = :password_hash,
        failed_login_count = 0,
        locked_until = NULL
    WHERE id = :user_id
""")

# Revoke toàn bộ refresh token chưa revoked của user — kick mọi device sau
# khi reset password. Mitigate scenario attacker đã cầm refresh cookie cũ.
_REVOKE_ALL_USER_REFRESH = text("""
    UPDATE auth.refresh_tokens
    SET revoked = true, revoked_at = now()
    WHERE user_id = :user_id AND revoked = false
""")


def _canonical_email(email: str) -> str:
    return email.strip().lower()


class IdentityService:
    def __init__(
        self,
        *,
        engine: Engine,
        jwt_secret: str,
        access_ttl_minutes: int,
        refresh_ttl_days: int,
        lockout_max_attempts: int,
        lockout_window_minutes: int,
        mailer: Mailer,
        password_reset_ttl_minutes: int,
        password_reset_url_template: str,
    ) -> None:
        # `engine` cần thiết cho inner write transactions của login-failure
        # counter (plan-auth-v2). Route mở outer `engine.begin()` rồi raise
        # InvalidCredentialsError → rollback; nếu counter ghi trên outer conn
        # thì mất. Service phải tự quản inner transaction để persist.
        self._engine = engine
        self._secret = jwt_secret
        self._access_ttl = timedelta(minutes=access_ttl_minutes)
        self._refresh_ttl_days = refresh_ttl_days
        self._lockout_max_attempts = lockout_max_attempts
        self._lockout_window_minutes = lockout_window_minutes
        self._mailer = mailer
        self._password_reset_ttl_minutes = password_reset_ttl_minutes
        # Template format: "{frontend_base_url}/?reset={token}". Format string
        # đơn giản — caller chỉ chèn token. Validate khi construct settings.
        self._password_reset_url_template = password_reset_url_template

    # ── public interface ──────────────────────────────────────────────────

    def register(self, conn: Connection, email: str, password: str) -> User:
        """Tạo user mới với email + password.

        Raises:
            EmailAlreadyExistsError: email (case-insensitive) đã có trong DB.
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
                raise EmailAlreadyExistsError(f"Email '{canonical}' đã tồn tại") from exc
            raise
        return User(
            id=row.id,
            email=row.email,
            is_admin=row.is_admin,
            disabled=row.disabled,
            created_at=row.created_at,
        )

    def authenticate(
        self,
        conn: Connection,
        email: str,
        password: str,
        *,
        user_agent: str | None = None,
        ip: str | None = None,
    ) -> AuthSession:
        """Xác thực credential, trả AuthSession (access + refresh) nếu OK.

        Raises:
            InvalidCredentialsError: email không có hoặc password sai.
            UserDisabledError: tìm thấy user nhưng `disabled=true`.
            AccountLockedError: account đang trong lockout window (plan-auth-v2).

        Lý do tách `UserDisabledError`: admin cần biết user disable cố tình
        login (audit), và frontend hiển thị message khác với "sai mật khẩu".

        `user_agent` + `ip` là audit metadata cho refresh-token row — KHÔNG
        phải security gate (có thể spoof). Truncate trong route trước khi pass.
        """
        canonical = _canonical_email(email)
        row = conn.execute(_SELECT_USER_BY_EMAIL, {"email": canonical}).one_or_none()
        if row is None:
            # Hash 1 password giả để chống timing attack (so user-exists vs
            # not-exists). Cost rất nhỏ vs bcrypt verify thật.
            _passwords.verify_password(password, _DUMMY_BCRYPT_HASH)
            raise InvalidCredentialsError("Email hoặc password sai")

        now = datetime.now(UTC)

        # Lockout check trước verify để không tốn bcrypt khi đang locked.
        if row.locked_until is not None and row.locked_until > now:
            retry_after = max(1, math.ceil((row.locked_until - now).total_seconds()))
            raise AccountLockedError(
                f"Tài khoản đã bị khoá tạm thời. Thử lại sau {retry_after} giây.",
                retry_after_seconds=retry_after,
            )

        if not _passwords.verify_password(password, row.password_hash):
            # Ghi counter trên inner transaction để persist độc lập với
            # outer rollback (route raise InvalidCredentialsError → outer
            # txn rollback). Sau khi commit thoát `with`, raise lỗi.
            should_lock = False
            with self._engine.begin() as wconn:
                new_count = wconn.execute(_UPDATE_LOGIN_FAILURE, {"user_id": row.id}).scalar_one()
                if new_count >= self._lockout_max_attempts:
                    locked_until = now + timedelta(minutes=self._lockout_window_minutes)
                    wconn.execute(
                        _UPDATE_LOGIN_LOCK,
                        {"user_id": row.id, "locked_until": locked_until},
                    )
                    should_lock = True
            if should_lock:
                retry_after = self._lockout_window_minutes * 60
                raise AccountLockedError(
                    f"Sai mật khẩu quá {self._lockout_max_attempts} lần. "
                    f"Tài khoản đã bị khoá {self._lockout_window_minutes} phút.",
                    retry_after_seconds=retry_after,
                )
            raise InvalidCredentialsError("Email hoặc password sai")

        if row.disabled:
            # Không reset counter — disabled user không nên dùng được account
            # dù password đúng, counter trạng thái không relevant.
            raise UserDisabledError("Tài khoản đã bị vô hiệu hoá")

        # Success: reset counters (commit ngay trên inner txn, an toàn dù outer rollback).
        with self._engine.begin() as wconn:
            wconn.execute(_UPDATE_LOGIN_SUCCESS, {"user_id": row.id})

        return self._issue_session(conn, row.id, user_agent=user_agent, ip=ip)

    def refresh_session(
        self,
        conn: Connection,
        presented_refresh_token: str,
        *,
        user_agent: str | None = None,
        ip: str | None = None,
    ) -> AuthSession:
        """Rotate refresh token + issue access token mới.

        Raises:
            RefreshTokenInvalidError / RefreshTokenExpiredError / RefreshTokenReusedError
            UserDisabledError: user còn nhưng admin disable từ login.
            InvalidCredentialsError: user đã bị xoá khỏi DB.
        """
        rotated = _refresh.rotate(
            conn,
            presented_refresh_token,
            engine=self._engine,
            ttl_days=self._refresh_ttl_days,
            user_agent=user_agent,
            ip=ip,
        )
        # Verify user vẫn hợp lệ — refresh không bypass disable check.
        user_row = conn.execute(_SELECT_USER_BY_ID, {"user_id": rotated.user_id}).one_or_none()
        if user_row is None:
            raise InvalidCredentialsError("User không tồn tại")
        if user_row.disabled:
            raise UserDisabledError("Tài khoản đã bị vô hiệu hoá")

        access_token, access_exp = _tokens.issue(
            rotated.user_id, secret=self._secret, ttl=self._access_ttl
        )
        return AuthSession(
            access_token=access_token,
            access_expires_at=access_exp,
            refresh_token=rotated.token,
            refresh_expires_at=rotated.expires_at,
        )

    def logout(self, conn: Connection, presented_refresh_token: str) -> None:
        """Revoke 1 refresh token (logout 1 device). Idempotent.

        Plan-auth-v2: KHÔNG revoke toàn family — user logout 1 device không
        nên kick các device khác.
        """
        _refresh.revoke(conn, presented_refresh_token)

    def request_password_reset(self, conn: Connection, email: str) -> None:
        """Request reset link cho email. Always-200 từ phía route (no enum).

        Behavior:
          * Email tồn tại + active → issue token + send mail.
          * Email tồn tại + disabled → NO-OP (không gửi mail; tránh leak
            disabled status + tránh user disable nghĩ là reset được).
          * Email không tồn tại → NO-OP.

        Route handler luôn trả 204 bất kể nhánh nào → caller không enumerate
        được email registered. Pre-deploy checklist §2 + §5 (no info leak).

        Mailer raise MailerError → propagate; route trả 503. Token đã được
        ghi DB trước khi gửi (commit ở outer txn), retry user sẽ invalidate
        và issue token mới — không có "ghost token" do mail fail.
        """
        canonical = _canonical_email(email)
        row = conn.execute(_SELECT_USER_BY_EMAIL, {"email": canonical}).one_or_none()
        if row is None or row.disabled:
            return

        issued = _reset.issue(
            conn,
            row.id,
            ttl_minutes=self._password_reset_ttl_minutes,
        )
        reset_url = self._password_reset_url_template.format(token=issued.token)
        # Gửi mail sau khi token đã ghi (cùng outer txn). Nếu mail raise,
        # route bắt → outer rollback → token cũng bị xoá. Consistent state.
        self._mailer.send_password_reset(
            canonical,
            reset_url=reset_url,
            expires_in_minutes=self._password_reset_ttl_minutes,
        )

    def confirm_password_reset(
        self,
        conn: Connection,
        presented_token: str,
        new_password: str,
    ) -> None:
        """Validate token + đổi password + revoke mọi refresh token của user.

        Raises:
            PasswordResetTokenInvalidError / ExpiredError / UsedError
            UserDisabledError: user đã bị disable sau khi request token.

        Side effect: tất cả phiên đăng nhập hiện hữu của user bị revoke —
        force re-login mọi device sau reset. Mitigate stolen-cookie scenario.
        """
        user_id = _reset.consume(conn, presented_token)
        # Refetch user để check disabled (admin có thể disable giữa lúc user
        # request reset và lúc confirm). Cũng đảm bảo user còn tồn tại.
        user_row = conn.execute(_SELECT_USER_BY_ID, {"user_id": user_id}).one_or_none()
        if user_row is None:
            raise InvalidCredentialsError("User không tồn tại")
        if user_row.disabled:
            raise UserDisabledError("Tài khoản đã bị vô hiệu hoá")

        password_hash = _passwords.hash_password(new_password)
        conn.execute(
            _UPDATE_PASSWORD,
            {"user_id": user_id, "password_hash": password_hash},
        )
        conn.execute(_REVOKE_ALL_USER_REFRESH, {"user_id": user_id})

    def _issue_session(
        self,
        conn: Connection,
        user_id: UUID,
        *,
        user_agent: str | None,
        ip: str | None,
    ) -> AuthSession:
        """Issue cặp access + refresh token (family mới) cho login."""
        issued = _refresh.issue(
            conn,
            user_id,
            ttl_days=self._refresh_ttl_days,
            user_agent=user_agent,
            ip=ip,
        )
        access_token, access_exp = _tokens.issue(user_id, secret=self._secret, ttl=self._access_ttl)
        return AuthSession(
            access_token=access_token,
            access_expires_at=access_exp,
            refresh_token=issued.token,
            refresh_expires_at=issued.expires_at,
        )

    def current_user(self, conn: Connection, token: str) -> User:
        """Decode JWT + refetch user từ DB.

        Raises:
            InvalidCredentialsError: token sai signature, malformed, hoặc
                user_id không tồn tại.
            TokenExpiredError: JWT exp < now.
            UserDisabledError: user tồn tại nhưng đã bị disable.
        """
        claims = _tokens.decode(token, secret=self._secret)
        row = conn.execute(_SELECT_USER_BY_ID, {"user_id": claims.user_id}).one_or_none()
        if row is None:
            # User bị xoá sau khi token issued.
            raise InvalidCredentialsError("User không tồn tại")
        if row.disabled:
            raise UserDisabledError("Tài khoản đã bị vô hiệu hoá")
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
