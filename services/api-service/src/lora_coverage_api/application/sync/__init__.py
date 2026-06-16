"""Sync — pull data từ external source vào DB.

Plan-auth-v1 §3.4. Step 4 ship `_upsert.py` primitives; Step 7 thêm
orchestrator (`SyncService`) + 2 result types.
"""

from ._upsert import (
    UpsertResult,
    lookup_existing_gateway,
    upsert_device,
    upsert_gateway,
    upsert_gateway_quarantine,
    upsert_measurement,
)
from .live_pull import LivePullPoint, LivePullService
from .service import SyncReport, SyncResult, SyncService

__all__ = [
    "LivePullPoint",
    "LivePullService",
    "SyncReport",
    "SyncResult",
    "SyncService",
    "UpsertResult",
    "lookup_existing_gateway",
    "upsert_device",
    "upsert_gateway",
    "upsert_gateway_quarantine",
    "upsert_measurement",
]
