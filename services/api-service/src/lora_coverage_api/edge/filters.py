"""ContributorFilter resolver — symbolic URL params → SQL filter spec.

Plan-auth-v1 §9.2 + §13 risk #4: resolver DUY NHẤT ở edge layer; mọi route
đọc data có filter contributor đi qua hàm này. Ngăn logic disabled-flag /
ownership / admin-gate bị duplicate inconsistent giữa các endpoint.

Symbolic URL syntax (plan §9.2):
    contributor=community             → mặc định (anon hoặc authenticated)
    contributor=me                    → chỉ data của current_user
    contributor=me&linked_source=<id> → sub-filter trong "Của tôi"
    contributor=user/<uuid>           → admin only, xem data 1 user khác

User KHÔNG nhìn raw user_id của người khác trong URL — buộc qua symbolic.

Errors raise ApplicationError → handler ở edge/errors.py convert RFC 7807.
Filter errors co-located ở đây thay vì application/errors.py vì chỉ phát
sinh trong context parsing/auth của edge.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Connection, text

from ..application.errors import ApplicationError
from ..application.identity import AdminRequiredError, User
from ..application.repositories import ContributorSpec

# ── Errors ────────────────────────────────────────────────────────────────


class FilterError(ApplicationError):
    """Base cho mọi lỗi parse/authorize ContributorFilter."""

    http_status = 400
    code = "filter_error"


class InvalidContributorError(FilterError):
    """Giá trị `contributor` không match grammar community|me|user/<uuid>."""

    http_status = 400
    code = "invalid_contributor"


class FilterAuthRequiredError(FilterError):
    """Mode `me` hoặc `user/<id>` cần auth nhưng request không kèm token."""

    http_status = 401
    code = "auth_required"


class LinkedSourceForbiddenError(FilterError):
    """linked_source param trỏ vào source không thuộc current_user.

    Trả 403 (không phải 404) — không tiết lộ tồn tại của linked_source thuộc
    user khác. Plan §13 risk #4.
    """

    http_status = 403
    code = "linked_source_forbidden"


# ── Resolver ──────────────────────────────────────────────────────────────
# `ContributorSpec` định nghĩa ở application/repositories.py vì là data
# (no logic) — Protocol cần import. Resolver ở đây làm parse + auth + DB
# lookup, ép buộc duy nhất ở edge layer.

_USER_PREFIX = "user/"

_SELECT_LINKED_SOURCE_OWNER = text("SELECT user_id FROM auth.linked_sources WHERE id = :ls_id")


def resolve_contributor(
    conn: Connection,
    *,
    raw_contributor: str | None,
    raw_linked_source: UUID | None,
    current_user: User | None,
) -> ContributorSpec:
    """Parse + authorize. Default `community` khi raw_contributor=None.

    Raises:
        InvalidContributorError    400 — contributor format sai / kết hợp param sai.
        FilterAuthRequiredError    401 — `me`/`user/...` thiếu auth token.
        AdminRequiredError         403 — `user/...` mà current_user không admin.
        LinkedSourceForbiddenError 403 — linked_source không thuộc current_user
                                         (hoặc không tồn tại — không phân biệt).
    """
    contributor = (raw_contributor or "community").strip()

    # ── community ─────────────────────────────────────────────────────────
    if contributor == "community":
        if raw_linked_source is not None:
            raise InvalidContributorError("linked_source chỉ kết hợp được với contributor=me")
        return ContributorSpec(mode="community")

    # ── me ────────────────────────────────────────────────────────────────
    if contributor == "me":
        if current_user is None:
            raise FilterAuthRequiredError("contributor=me cần auth token")
        spec_linked: UUID | None = None
        if raw_linked_source is not None:
            _assert_linked_source_owner(conn, raw_linked_source, current_user.id)
            spec_linked = raw_linked_source
        return ContributorSpec(
            mode="self",
            target_user_id=current_user.id,
            linked_source_id=spec_linked,
        )

    # ── user/<uuid> ───────────────────────────────────────────────────────
    if contributor.startswith(_USER_PREFIX):
        if current_user is None:
            raise FilterAuthRequiredError("contributor=user/<id> cần auth token")
        if not current_user.is_admin:
            raise AdminRequiredError("contributor=user/<id> chỉ admin gọi được")
        if raw_linked_source is not None:
            raise InvalidContributorError("linked_source không kết hợp với contributor=user/<id>")
        try:
            target_id = UUID(contributor.removeprefix(_USER_PREFIX))
        except ValueError:
            raise InvalidContributorError("user/<id> phải là UUID hợp lệ") from None
        return ContributorSpec(mode="user", target_user_id=target_id)

    raise InvalidContributorError(
        f"contributor không hợp lệ: {contributor!r}. Giá trị chấp nhận: community, me, user/<uuid>"
    )


def _assert_linked_source_owner(conn: Connection, linked_source_id: UUID, user_id: UUID) -> None:
    row = conn.execute(_SELECT_LINKED_SOURCE_OWNER, {"ls_id": linked_source_id}).first()
    # row=None (không tồn tại) cũng raise forbidden — không leak existence.
    if row is None or row.user_id != user_id:
        raise LinkedSourceForbiddenError(
            "linked_source không thuộc user hiện tại hoặc không tồn tại"
        )
