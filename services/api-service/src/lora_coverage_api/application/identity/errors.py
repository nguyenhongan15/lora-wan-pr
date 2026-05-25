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


class AccountLockedError(IdentityError):
    """Account đang trong lockout window do quá nhiều lần login sai.

    Plan-auth-v2. Edge handler đọc `retry_after_seconds` → set HTTP header
    Retry-After + include trong body. Không leak email tồn tại: response
    giống `InvalidCredentialsError` về structure, khác ở status 429 + code.
    Frontend phân biệt qua `code` field.
    """

    http_status = 429
    code = "account_locked"

    def __init__(self, message: str, retry_after_seconds: int) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


# ── Refresh token errors (plan-auth-v2 step 2) ─────────────────────────────
# 401 cho cả 3 — frontend treat đồng nhất "phiên hết hạn, re-login". Phân
# biệt qua `code` để log audit / hiển thị message phù hợp.


class RefreshTokenInvalidError(IdentityError):
    """Refresh token không tồn tại, đã revoked, hoặc malformed."""

    http_status = 401
    code = "refresh_invalid"


class RefreshTokenExpiredError(IdentityError):
    """Refresh token quá expires_at (30 ngày từ issue)."""

    http_status = 401
    code = "refresh_expired"


class RefreshTokenReusedError(IdentityError):
    """Refresh token đã rotated nhưng bị present lại — theft signal.

    Service đã revoke family trước khi raise. Client thấy lỗi này = phiên đã
    bị compromise, phải re-login.
    """

    http_status = 401
    code = "refresh_reused"


# ── Password reset errors (pre-deploy checklist §2) ────────────────────────
# 400 cho cả 3 — frontend treat đồng nhất "link hỏng, request lại". Phân
# biệt qua `code` để hiển thị message cụ thể (hết hạn vs đã dùng vs sai).


class PasswordResetTokenInvalidError(IdentityError):
    """Reset token không tồn tại hoặc malformed."""

    http_status = 400
    code = "password_reset_invalid"


class PasswordResetTokenExpiredError(IdentityError):
    """Reset token quá expires_at (TTL ~30 phút)."""

    http_status = 400
    code = "password_reset_expired"


class PasswordResetTokenUsedError(IdentityError):
    """Reset token đã được consume — single-use enforced."""

    http_status = 400
    code = "password_reset_used"


# ── Email verification errors ──────────────────────────────────────────────
# 400 cho cả 3 — frontend treat đồng nhất "link hỏng, request lại". Phân
# biệt qua `code` để hiển thị message cụ thể (hết hạn vs đã dùng vs sai).


class EmailVerificationTokenInvalidError(IdentityError):
    """Verification token không tồn tại hoặc malformed."""

    http_status = 400
    code = "email_verification_invalid"


class EmailVerificationTokenExpiredError(IdentityError):
    """Verification token quá expires_at (TTL ~60 phút)."""

    http_status = 400
    code = "email_verification_expired"


class EmailVerificationTokenUsedError(IdentityError):
    """Verification token đã được consume — single-use enforced."""

    http_status = 400
    code = "email_verification_used"


class EmailNotVerifiedError(IdentityError):
    """User chưa xác thực email — endpoint yêu cầu verified để submit community data."""

    http_status = 403
    code = "email_not_verified"
