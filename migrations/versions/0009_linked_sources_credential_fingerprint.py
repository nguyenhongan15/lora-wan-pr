"""auth.linked_sources.credential_fingerprint + UNIQUE per source_type

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-08

Plan-auth-v1 §3.3 + §6.2 — chặn 2 user khác nhau link cùng external account
(cùng email lpwanmapper / cùng api_token chirpstack). Trước fix: insert
silently OK, sync sau cùng ghi đè contributor → claim được data của user
khác.

Quyết định:
  * Cột `credential_fingerprint` = HMAC-SHA256 hex (64 char) của canonical
    credential (adapter định nghĩa "field nào là identity"). Lưu hex thay
    vì bytea — debug grep, type stable, 64 byte không đáng kể.
  * UNIQUE GLOBAL `(source_type, credential_fingerprint)` (KHÔNG scope
    user_id) — đó là cốt lõi: 2 user khác link cùng account ⇒ conflict.
  * PARTIAL `WHERE credential_fingerprint IS NOT NULL` — row legacy (insert
    trước migration này) có fingerprint NULL không bị constraint, không
    block deploy. Backfill là task riêng (skip v1: DATN-scale, dữ liệu
    test, fix-going-forward đủ).
  * Nullable cột — fix forward only. Sau khi backfill xong (nếu có) đổi
    thành NOT NULL trong migration sau.
"""

from __future__ import annotations

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE auth.linked_sources "
        "ADD COLUMN credential_fingerprint text;"
    )
    op.execute(
        "COMMENT ON COLUMN auth.linked_sources.credential_fingerprint IS "
        "'HMAC-SHA256 hex của canonical credential dict do adapter định "
        "nghĩa. UNIQUE per source_type chặn 2 user link cùng external "
        "account.';"
    )
    op.execute(
        """
        CREATE UNIQUE INDEX ux_linked_sources_fingerprint
        ON auth.linked_sources (source_type, credential_fingerprint)
        WHERE credential_fingerprint IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS auth.ux_linked_sources_fingerprint;")
    op.execute(
        "ALTER TABLE auth.linked_sources "
        "DROP COLUMN IF EXISTS credential_fingerprint;"
    )
