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


class InvalidCredentials(IdentityError):
    """Email/password sai, token sai signature, hoặc token malformed."""

    code = "invalid_credentials"


class TokenExpired(IdentityError):
    """JWT exp < now. Phân biệt khỏi InvalidCredentials để frontend biết khi nào re-login."""

    code = "token_expired"


class EmailAlreadyExists(IdentityError):
    """Register với email đã tồn tại."""

    http_status = 409
    code = "email_already_exists"


class UserDisabled(IdentityError):
    """Login thành công về password nhưng user bị admin disable."""

    http_status = 403
    code = "user_disabled"
