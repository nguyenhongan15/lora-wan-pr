"""Source-layer exception hierarchy.

Plan-auth-v1 §8.1.

Adapters convert raw HTTP/network/JSON error → các class này. Caller (Sync)
chỉ catch SourceError; không bao giờ thấy httpx.HTTPError leak ra.
"""

from __future__ import annotations

from ..errors import ApplicationError


class SourceError(ApplicationError):
    http_status = 502
    code = "source_error"


class SourceAuthError(SourceError):
    code = "source_auth_failed"


class SourceUnreachableError(SourceError):
    code = "source_unreachable"


class SourceFetchError(SourceError):
    code = "source_fetch_failed"


class UnknownSourceTypeError(SourceError):
    """Registry không có adapter cho source_type. User-facing → 400."""

    http_status = 400
    code = "unknown_source_type"
