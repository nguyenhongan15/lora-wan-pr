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


class UserNotFoundError(IdentityError):
    """Admin truy vấn user_id không tồn tại trong DB."""

    http_status = 404
    code = "user_not_found"


class AdminRequiredError(IdentityError):
    """Endpoint yêu cầu is_admin=true nhưng caller không có quyền."""

    http_status = 403
    code = "admin_required"


class AdminSelfModificationError(IdentityError):
    """Admin tự sửa is_admin/disabled của chính mình.

    Self-protection: tránh trường hợp admin cuối cùng tự revoke quyền hoặc tự
    disable → không còn ai vào /admin được. Không yêu cầu kiểm tra "admin
    cuối cùng" cụ thể (race-prone) — chặn mọi self-modification là đủ.
    """

    http_status = 400
    code = "admin_self_modification"
