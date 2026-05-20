"""Auth routes — register, login, refresh, logout, me.

Plan-auth-v1 §11 step 5 + plan-auth-v2 step 2.

Cookie-based refresh token flow:
  * /login → set HttpOnly cookie (refresh), trả access JWT trong body.
  * /refresh → đọc cookie, rotate, set cookie mới, trả access JWT mới.
  * /logout → revoke refresh trên DB + xoá cookie.

Cookie name `lora_refresh`, path `/api/v1/auth` (browser chỉ gửi cookie cho
endpoints dưới path này → reduce exposure surface).

Rate-limit:
  * /register: 5/hour per IP (anti spam-account).
  * /login: 10/minute per IP (anti brute-force diện rộng; lockout per-email là
    tầng cứng).
  * /refresh: 30/minute per IP (đủ rộng cho client refresh mỗi 15 phút,
    nhưng vẫn chặn abuse).
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request, Response, status
from slowapi.util import get_remote_address

from ...application.identity import (
    IdentityService,
    InvalidCredentialsError,
    User,
)
from ...config import get_settings
from ..deps import _engine, current_user, identity_service
from ..rate_limit import limiter
from ..schemas import (
    LoginRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequestRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_settings = get_settings()

# Cookie config — path scope giới hạn cookie cho /api/v1/auth/* (refresh +
# logout). Endpoint khác KHÔNG nhận được cookie → reduce CSRF/XSS surface.
_REFRESH_COOKIE_NAME = "lora_refresh"
_REFRESH_COOKIE_PATH = "/api/v1/auth"


def _user_to_response(u: User) -> UserResponse:
    return UserResponse(
        id=u.id,
        email=u.email,
        is_admin=u.is_admin,
        created_at=u.created_at,
    )


def _set_refresh_cookie(response: Response, token: str, expires_at: datetime) -> None:
    """Set HttpOnly Secure SameSite refresh cookie với path scope."""
    max_age = max(1, int((expires_at - datetime.now(UTC)).total_seconds()))
    response.set_cookie(
        key=_REFRESH_COOKIE_NAME,
        value=token,
        max_age=max_age,
        path=_REFRESH_COOKIE_PATH,
        httponly=True,
        secure=_settings.refresh_cookie_secure,
        samesite=_settings.refresh_cookie_samesite,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=_REFRESH_COOKIE_NAME,
        path=_REFRESH_COOKIE_PATH,
    )


def _audit_metadata(request: Request) -> tuple[str | None, str | None]:
    """Extract (user_agent, ip) cho refresh-token audit row.

    UA truncate 500 chars chống ghi DB row khổng lồ do header spoof.
    """
    ua = request.headers.get("user-agent")
    ua = ua[:500] if ua else None
    ip = get_remote_address(request)
    return ua, ip


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(_settings.auth_register_rate_limit)
def register(
    request: Request,  # noqa: ARG001 — required by slowapi.Limiter để extract IP
    body: RegisterRequest,
    identity: IdentityService = Depends(identity_service),
) -> UserResponse:
    with _engine().begin() as conn:
        user = identity.register(conn, body.email, body.password)
    return _user_to_response(user)


@router.post(
    "/login",
    response_model=TokenResponse,
)
@limiter.limit(_settings.auth_login_rate_limit)
def login(
    request: Request,
    response: Response,
    body: LoginRequest,
    identity: IdentityService = Depends(identity_service),
) -> TokenResponse:
    ua, ip = _audit_metadata(request)
    with _engine().begin() as conn:
        session = identity.authenticate(conn, body.email, body.password, user_agent=ua, ip=ip)
    _set_refresh_cookie(response, session.refresh_token, session.refresh_expires_at)
    return TokenResponse(
        access_token=session.access_token,
        token_type="bearer",
        expires_at=session.access_expires_at,
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
)
@limiter.limit("30/minute")
def refresh(
    request: Request,
    response: Response,
    identity: IdentityService = Depends(identity_service),
) -> TokenResponse:
    presented = request.cookies.get(_REFRESH_COOKIE_NAME)
    if not presented:
        # Không leak cookie name trong message — generic 401.
        raise InvalidCredentialsError("Thiếu refresh token")
    ua, ip = _audit_metadata(request)
    with _engine().begin() as conn:
        session = identity.refresh_session(conn, presented, user_agent=ua, ip=ip)
    _set_refresh_cookie(response, session.refresh_token, session.refresh_expires_at)
    return TokenResponse(
        access_token=session.access_token,
        token_type="bearer",
        expires_at=session.access_expires_at,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
)
def logout(
    request: Request,
    response: Response,
    identity: IdentityService = Depends(identity_service),
) -> Response:
    # Idempotent: cookie không có hoặc token không hợp lệ → vẫn 204 + clear cookie.
    # Không yêu cầu Authorization header — frontend có thể logout dù access JWT
    # đã hết hạn.
    presented = request.cookies.get(_REFRESH_COOKIE_NAME)
    if presented:
        with _engine().begin() as conn:
            identity.logout(conn, presented)
    _clear_refresh_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get(
    "/me",
    response_model=UserResponse,
)
def me(user: User = Depends(current_user)) -> UserResponse:
    return _user_to_response(user)


# ── Password reset (pre-deploy checklist §2) ──────────────────────────────
# Always-204 trên /request: không leak email registered/disabled. Service
# branch in/out trên user-state, route đồng nhất response shape.


@router.post(
    "/password-reset/request",
    status_code=status.HTTP_204_NO_CONTENT,
)
@limiter.limit(_settings.auth_password_reset_request_rate_limit)
def password_reset_request(
    request: Request,  # noqa: ARG001 — required by slowapi.Limiter để extract IP
    body: PasswordResetRequestRequest,
    identity: IdentityService = Depends(identity_service),
) -> Response:
    with _engine().begin() as conn:
        identity.request_password_reset(conn, body.email)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/password-reset/confirm",
    status_code=status.HTTP_204_NO_CONTENT,
)
@limiter.limit(_settings.auth_password_reset_confirm_rate_limit)
def password_reset_confirm(
    request: Request,  # noqa: ARG001 — required by slowapi.Limiter để extract IP
    body: PasswordResetConfirmRequest,
    identity: IdentityService = Depends(identity_service),
) -> Response:
    with _engine().begin() as conn:
        identity.confirm_password_reset(conn, body.token, body.new_password)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
