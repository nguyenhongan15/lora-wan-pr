"""Metadata-locked flag cho gateway

Revision ID: 0034
Revises: 0033
Create Date: 2026-06-17

Admin có thể "khoá" location + altitude_m của 1 gateway để sync
(lpwanmapper/chirpstack) không ghi đè khi metadata external thay đổi.
Dùng cho trường hợp admin đã sửa thủ công (vd swap toạ độ bị nhầm)
và muốn giữ giá trị.

  * `geo.gateways.metadata_locked` boolean NOT NULL DEFAULT false.
  * Sync upsert (_GATEWAY_UPSERT_SQL) kiểm tra cờ này — true → giữ
    location + altitude_m hiện tại bất kể contributor.
  * Không index — query single-row qua PK, không filter theo cột này.
"""

from __future__ import annotations

from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE geo.gateways
            ADD COLUMN metadata_locked boolean NOT NULL DEFAULT false;
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE geo.gateways DROP COLUMN IF EXISTS metadata_locked;"
    )
