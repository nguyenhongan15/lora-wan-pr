"""Source-type registry.

Plan-auth-v1 §3.2 + §7. Sync orchestrator dispatch theo `source_type`
(lpwanmapper / chirpstack / csv) qua registry này — không if/elif chuỗi dài.

Adapter modules tự register lúc import. Step 3 sẽ đăng ký LpwanmapperSource.
"""

from __future__ import annotations

from .base import DataSource
from .errors import UnknownSourceTypeError

_REGISTRY: dict[str, type[DataSource]] = {}


def register(source_type: str, adapter_cls: type[DataSource]) -> None:
    """Đăng ký 1 adapter class cho source_type. Idempotent (overwrite OK)."""
    _REGISTRY[source_type] = adapter_cls


def get_adapter(source_type: str) -> DataSource:
    """Trả instance adapter mới cho source_type.

    Raises:
        UnknownSourceTypeError: source_type không có trong registry.
    """
    cls = _REGISTRY.get(source_type)
    if cls is None:
        raise UnknownSourceTypeError(f"unknown source_type: {source_type!r}")
    return cls()


def known_source_types() -> tuple[str, ...]:
    """List source types đã đăng ký (cho admin UI / validation)."""
    return tuple(_REGISTRY)
