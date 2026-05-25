"""Identity — register/login/me cho web-app users (auth lớp 1).

Plan-auth-v1 §3.1. Module deep: 3 method công khai (register, authenticate,
current_user) ẩn JWT format/secret/TTL, bcrypt work factor, email
canonicalisation, timing-attack mitigation.

KHÔNG quản lý linked external sources — đó là Step 6 (`linking/`).
"""

from ._mailer import Mailer, MailerError
from .errors import (
    AccountLockedError,
    AdminRequiredError,
    AdminSelfModificationError,
    EmailAlreadyExistsError,
    EmailNotVerifiedError,
    EmailVerificationTokenExpiredError,
    EmailVerificationTokenInvalidError,
    EmailVerificationTokenUsedError,
    IdentityError,
    InvalidCredentialsError,
    PasswordResetTokenExpiredError,
    PasswordResetTokenInvalidError,
    PasswordResetTokenUsedError,
    RefreshTokenExpiredError,
    RefreshTokenInvalidError,
    RefreshTokenReusedError,
    TokenExpiredError,
    UserDisabledError,
    UserNotFoundError,
)
from .service import AuthSession, AuthToken, IdentityService, User

__all__ = [
    "AccountLockedError",
    "AdminRequiredError",
    "AdminSelfModificationError",
    "AuthSession",
    "AuthToken",
    "EmailAlreadyExistsError",
    "EmailNotVerifiedError",
    "EmailVerificationTokenExpiredError",
    "EmailVerificationTokenInvalidError",
    "EmailVerificationTokenUsedError",
    "IdentityError",
    "IdentityService",
    "InvalidCredentialsError",
    "Mailer",
    "MailerError",
    "PasswordResetTokenExpiredError",
    "PasswordResetTokenInvalidError",
    "PasswordResetTokenUsedError",
    "RefreshTokenExpiredError",
    "RefreshTokenInvalidError",
    "RefreshTokenReusedError",
    "TokenExpiredError",
    "User",
    "UserDisabledError",
    "UserNotFoundError",
]
