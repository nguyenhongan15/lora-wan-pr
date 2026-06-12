"""Linking — kết nối user web-app với external data sources.

Plan-auth-v1 §3.3. Module deep: 5 method công khai (link, unlink, list_for,
test, set_sync_enabled) ẩn MultiFernet encryption, JSON serialisation,
source registry dispatch, ownership check, audit log.

KHÔNG quản lý identity (Step 5) hay sync (Step 7).
"""

from ._crypto import CredentialCipher
from .errors import (
    CredentialAlreadyLinkedError,
    CredentialTestFailedError,
    LinkedSourceNotFoundError,
    LinkingError,
)
from .service import LinkedSource, LinkingService, LinkResult

__all__ = [
    "CredentialAlreadyLinkedError",
    "CredentialCipher",
    "CredentialTestFailedError",
    "LinkResult",
    "LinkedSource",
    "LinkedSourceNotFoundError",
    "LinkingError",
    "LinkingService",
]
