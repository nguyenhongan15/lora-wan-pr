"""Identity-layer exception hierarchy.

Plan-auth-v1 §8.1: subclass `ApplicationError`. Edge handler dùng `http_status`
+ `code` để build RFC 7807 response.

Module identity dùng RAISE cho mọi failure (không return None) — caller cần
phân biệt rõ "credential sai" vs "token hết hạn" vs "email trùng".
"""

from __future__ import annotations

from ..errors import ApplicationError


class IdentityError(ApplicationError):
    http_status = 401
    code = "identity_error"


class InvalidCredentialsError(IdentityError):
    """Email/password sai, token sai signature, hoặc token malformed."""


class TokenExpiredError(IdentityError):
    """JWT exp < now. Phân biệt khỏi InvalidCredentialsError để frontend biết khi nào re-login."""


class EmailAlreadyExistsError(IdentityError):
    """Register với email đã tồn tại."""

    http_status = 409
    code = "email_already_exists"


class UserDisabledError(IdentityError):
    """Login thành công về password nhưng user bị admin disable."""

    http_status = 403
    code = "user_disabled"
