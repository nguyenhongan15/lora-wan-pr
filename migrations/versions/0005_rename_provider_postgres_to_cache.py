"""rename provider 'postgres' to 'cache' in address.canonical

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-06

Storage-tier identifier 'postgres' đã leak vào domain enum
(GeocodingProvider.POSTGRES) — vi phạm 5-layer separation (CI grep enforce
ở application/ + domain/). Đổi sang 'cache' để domain không biết về
implementation detail.

DB hiện không có row nào với provider='postgres' nên không cần UPDATE data
— chỉ thay CHECK constraint là đủ.
"""

from __future__ import annotations

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE address.canonical DROP CONSTRAINT chk_provider;")
    op.execute(
        """
        ALTER TABLE address.canonical
        ADD CONSTRAINT chk_provider CHECK (
            provider IN ('cache','nominatim','vietmap','goong','google')
        );
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE address.canonical DROP CONSTRAINT chk_provider;")
    op.execute(
        """
        ALTER TABLE address.canonical
        ADD CONSTRAINT chk_provider CHECK (
            provider IN ('postgres','nominatim','vietmap','goong','google')
        );
        """
    )