"""Postgres impl của `DeviceQuery` cho `geo.devices`.

Read-only thuần — sync orchestrator (application/sync/_upsert.py) ghi
bằng INSERT...ON CONFLICT, route /me/sources/{id}/devices chỉ SELECT.

Ownership verify thực hiện ở edge (route lookup linked_source theo
user_id trước khi gọi repo); repo không tự JOIN auth.linked_sources lại
vì 1 round-trip ở edge đủ và giữ method này hẹp.
"""

from __future__ import annotations

from typing import cast
from uuid import UUID

from sqlalchemy import Engine, text

from ..application.repositories import LinkedSourceDevice

_LIST_BY_LS_SQL = text("""
    SELECT id, dev_eui, name, source_type, last_seen_at, created_at, updated_at
    FROM geo.devices
    WHERE linked_source_id = :ls_id
    ORDER BY last_seen_at DESC NULLS LAST, dev_eui ASC
    LIMIT :limit OFFSET :offset
""")

_COUNT_BY_LS_SQL = text("""
    SELECT COUNT(*) AS n FROM geo.devices WHERE linked_source_id = :ls_id
""")


class PgDeviceRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def list_by_linked_source(
        self,
        *,
        linked_source_id: UUID,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[LinkedSourceDevice], int]:
        # Connection riêng cho mỗi list call — không reuse từ caller (route
        # đọc-only, không cần tham gia transaction của UPDATE auth.*).
        with self._engine.connect() as conn:
            rows = conn.execute(
                _LIST_BY_LS_SQL,
                {"ls_id": linked_source_id, "limit": limit, "offset": offset},
            ).all()
            total_row = conn.execute(_COUNT_BY_LS_SQL, {"ls_id": linked_source_id}).one()
        items = [
            LinkedSourceDevice(
                id=r.id,
                dev_eui=r.dev_eui,
                name=r.name,
                source_type=r.source_type,
                last_seen_at=r.last_seen_at,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
            for r in rows
        ]
        return items, cast(int, total_row.n)
