"""Identity — register/login/me cho web-app users (auth lớp 1).

Plan-auth-v1 §3.1. Module deep: 3 method công khai (register, authenticate,
current_user) ẩn JWT format/secret/TTL, bcrypt work factor, email
canonicalisation, timing-attack mitigation.

KHÔNG quản lý linked external sources — đó là Step 6 (`linking/`).
"""

from .errors import (
    EmailAlreadyExistsError,
    IdentityError,
    InvalidCredentialsError,
    TokenExpiredError,
    UserDisabledError,
)
from .service import AuthToken, IdentityService, User

__all__ = [
    "AuthToken",
    "EmailAlreadyExistsError",
    "IdentityError",
    "IdentityService",
    "InvalidCredentialsError",
    "TokenExpiredError",
    "User",
    "UserDisabledError",
]
