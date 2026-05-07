"""Linking — kết nối user web-app với external data sources.

Plan-auth-v1 §3.3. Module deep: 6 method công khai (link, unlink, list_for,
test, set_sync_enabled, set_contribution) ẩn MultiFernet encryption,
JSON serialisation, source registry dispatch, ownership check, audit log.

KHÔNG quản lý identity (Step 5) hay sync (Step 7).
"""

from ._crypto import CredentialCipher
from .errors import (
    CredentialTestFailedError,
    LinkedSourceNotFoundError,
    LinkingError,
)
from .service import LinkedSource, LinkingService

__all__ = [
    "CredentialCipher",
    "CredentialTestFailedError",
    "LinkedSource",
    "LinkedSourceNotFoundError",
    "LinkingError",
    "LinkingService",
]
