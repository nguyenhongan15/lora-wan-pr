"""Sync — pull data từ external source vào DB.

Plan-auth-v1 §3.4. Step 4 ship `_upsert.py` primitives; Step 7 thêm
orchestrator (`SyncService`) + 2 result types.
"""

from ._upsert import UpsertResult, upsert_gateway, upsert_measurement
from .service import SyncReport, SyncResult, SyncService

__all__ = [
    "SyncReport",
    "SyncResult",
    "SyncService",
    "UpsertResult",
    "upsert_gateway",
    "upsert_measurement",
]
