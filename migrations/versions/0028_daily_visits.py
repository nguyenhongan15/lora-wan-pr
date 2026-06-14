"""audit.daily_visits — counter pageview cho admin dashboard Tong quan.

Revision ID: 0028
Revises: 0027
Create Date: 2026-06-13

Endpoint public POST /telemetry/visit lam UPSERT (day, count+1). Khong dedupe
theo user — frontend goi tren moi mount cua App. Admin stats chart bucket
theo tuan/thang/nam.
"""

from __future__ import annotations

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS audit;")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS audit.daily_visits (
            day   date NOT NULL PRIMARY KEY,
            count bigint NOT NULL DEFAULT 0
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit.daily_visits;")
