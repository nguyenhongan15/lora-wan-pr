"""Sources — general-purpose external data source interface.

Plan-auth-v1 §3.2.

Caller (Sync orchestrator) thấy: DataSource ABC + 2 record types + registry.
Provider details (HTTP, auth, pagination, retry) ẩn trong implementation
modules dưới sources/<provider>/.
"""

# Side effect: built-in adapters self-register vào registry. Caller chỉ cần
# import package này; không phải biết tên adapter module nào tồn tại.
from . import chirpstack, lpwanmapper  # noqa: F401
from .base import (
    ConnectionHandle,
    DataSource,
    DeviceRecord,
    GatewayRecord,
    MeasurementRecord,
)
from .errors import (
    SourceAuthError,
    SourceError,
    SourceFetchError,
    SourceUnreachableError,
    UnknownSourceTypeError,
)
from .registry import get_adapter, known_source_types, register

__all__ = [
    "ConnectionHandle",
    "DataSource",
    "DeviceRecord",
    "GatewayRecord",
    "MeasurementRecord",
    "SourceAuthError",
    "SourceError",
    "SourceFetchError",
    "SourceUnreachableError",
    "UnknownSourceTypeError",
    "get_adapter",
    "known_source_types",
    "register",
]
