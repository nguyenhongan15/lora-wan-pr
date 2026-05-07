"""Sync — pull data từ external source vào DB.

Plan-auth-v1 §3.4. Step 4 chỉ ship upsert primitives (`_upsert.py`); orchestrator
`sync()` / `sync_all()` thêm ở Step 7 sau khi linking module có (cần encrypt
credential + linked_source row).

Caller hiện tại chỉ là CLI (scripts/sync_one_cli.py).
"""

from ._upsert import UpsertResult, upsert_gateway, upsert_measurement

__all__ = ["UpsertResult", "upsert_gateway", "upsert_measurement"]
