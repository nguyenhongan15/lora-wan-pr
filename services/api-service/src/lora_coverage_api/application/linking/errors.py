"""Linking-layer exception hierarchy.

Plan-auth-v1 §8.1: subclass ApplicationError. 1 handler ở edge map sang
RFC 7807 Problem Details.
"""

from __future__ import annotations

from ..errors import ApplicationError


class LinkingError(ApplicationError):
    http_status = 400
    code = "linking_error"


class CredentialTestFailedError(LinkingError):
    """`link()` hoặc `test()` gọi `adapter.connect()` và adapter raise SourceAuthError.

    User-facing 400: "Credential <provider> sai" — KHÔNG persist row, không
    leak chi tiết HTTP error của provider ra response.
    """

    code = "credential_test_failed"


class LinkedSourceNotFoundError(LinkingError):
    """ID không tồn tại HOẶC tồn tại nhưng thuộc user khác.

    Không phân biệt 2 case ở response để tránh leak ID enumeration —
    user khác xem được "id 7 tồn tại nhưng không phải của bạn" là
    thông tin không cần.
    """

    http_status = 404
    code = "linked_source_not_found"


class CredentialAlreadyLinkedError(LinkingError):
    """Cùng external account (theo fingerprint) đã được user khác link.

    UNIQUE `(source_type, credential_fingerprint)` ở DB layer (migration
    0009) chặn — `LinkingService.link()` catch IntegrityError và raise
    error này. 409 Conflict (REST: trạng thái resource hiện tại không
    cho phép request).

    Privacy trade-off: response tiết lộ "account này đã có người link" —
    chấp nhận vì caller phải có credential hợp lệ để đến bước này
    (test() đã pass), nên không cộng thêm khả năng enumeration nào so
    với việc login trực tiếp vào provider.
    """

    http_status = 409
    code = "credential_already_linked"
