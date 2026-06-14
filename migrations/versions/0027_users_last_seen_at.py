"""auth.users — them cot last_seen_at cho admin Tong quan "User online".

Revision ID: 0027
Revises: 0026
Create Date: 2026-06-13

Middleware cap nhat last_seen_at trong current_user() dep tren moi authenticated
request (throttled 30s). Admin stats query dem distinct users co last_seen_at
trong 5 phut gan nhat = so "User online".
"""

from __future__ import annotations

from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE auth.users ADD COLUMN last_seen_at timestamptz;"
    )
    # Index cho query `WHERE last_seen_at > now() - interval '5 min'` — admin
    # stats poll 30s/lan, can index BRIN/btree de tranh seq scan khi user table
    # lon. Partial index chi cho row co last_seen_at IS NOT NULL.
    op.execute(
        "CREATE INDEX idx_users_last_seen_at ON auth.users (last_seen_at) "
        "WHERE last_seen_at IS NOT NULL;"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS auth.idx_users_last_seen_at;")
    op.execute("ALTER TABLE auth.users DROP COLUMN IF EXISTS last_seen_at;")
