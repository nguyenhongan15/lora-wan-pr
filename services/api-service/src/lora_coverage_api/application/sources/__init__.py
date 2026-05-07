"""Sources — general-purpose external data source interface.

Plan-auth-v1 §3.2.

Caller (Sync orchestrator) thấy: DataSource ABC + 2 record types + registry.
Provider details (HTTP, auth, pagination, retry) ẩn trong implementation
modules dưới sources/<provider>/.
"""

from .base import (
    ConnectionHandle,
    DataSource,
    GatewayRecord,
    MeasurementRecord,
)
from .errors import (
    SourceAuthFailed,
    SourceError,
    SourceFetchFailed,
    SourceUnreachable,
    UnknownSourceType,
)
from .registry import get_adapter, known_source_types, register

# Side effect: built-in adapters self-register vào registry. Caller chỉ cần
# import package này; không phải biết tên adapter module nào tồn tại.
from . import lpwanmapper  # noqa: F401, E402

__all__ = [
    "ConnectionHandle",
    "DataSource",
    "GatewayRecord",
    "MeasurementRecord",
    "SourceError",
    "SourceAuthFailed",
    "SourceFetchFailed",
    "SourceUnreachable",
    "UnknownSourceType",
    "get_adapter",
    "known_source_types",
    "register",
]
