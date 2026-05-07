"""Auth routes — register, login, me.

Plan-auth-v1 §11 step 5. 3 endpoint mỏng — mỗi endpoint chỉ marshall I/O và
gọi đúng 1 method của `IdentityService`. Không try/except: ApplicationError
handler ở edge/errors.py xử lý tất cả.

Auth lớp 1 (web-app users) — KHÔNG liên quan lpwanmapper. Step 6 sẽ thêm
me/sources cho linked external sources.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from ...application.identity import IdentityService, User
from ..deps import _engine, current_user, identity_service
from ..schemas import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _user_to_response(u: User) -> UserResponse:
    return UserResponse(
        id=u.id,
        email=u.email,
        is_admin=u.is_admin,
        created_at=u.created_at,
    )


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(
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
def login(
    body: LoginRequest,
    identity: IdentityService = Depends(identity_service),
) -> TokenResponse:
    with _engine().begin() as conn:
        token = identity.authenticate(conn, body.email, body.password)
    return TokenResponse(
        access_token=token.access_token,
        token_type="bearer",
        expires_at=token.expires_at,
    )


@router.get(
    "/me",
    response_model=UserResponse,
)
def me(user: User = Depends(current_user)) -> UserResponse:
    return _user_to_response(user)
