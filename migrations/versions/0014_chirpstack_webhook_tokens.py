"""auth.linked_sources.webhook_token_hash + webhook_rotated_at

Revision ID: 0014
Revises: 0013
Create Date: 2026-05-19

Plan ChirpStack per-user webhook ingest. Mỗi linked_source được cấp 1 webhook
token plaintext (opaque 256-bit, sinh ở app) → ChirpStack HTTP Integration POST
uplink về URL chứa token đó. DB chỉ giữ HMAC-SHA256 hash; không bao giờ lưu
plaintext (giống pattern auth.refresh_tokens).

Quyết định:
  * `webhook_token_hash bytea` NULLABLE — chỉ source_type='chirpstack' sinh
    token. lpwanmapper / csv không có webhook → column null. Không thêm CHECK
    ràng buộc theo source_type để giữ table mở rộng cho provider mới.
  * UNIQUE PARTIAL `WHERE webhook_token_hash IS NOT NULL` — lookup webhook
    request bằng 1 query `WHERE webhook_token_hash = :h`. PG O(log n).
  * `webhook_rotated_at timestamptz` audit: thời điểm rotate gần nhất. Khác
    `last_sync_at` (sync gần nhất) và `created_at` (link). UI hiển thị "Token
    cấp ngày dd/mm".
  * Migration KHÔNG backfill — system trước migration này dùng env-map
    `CHIRPSTACK_WEBHOOK_TOKENS`, không có DB state cũ để migrate. Admin re-link
    sau khi deploy (đã thông báo trong plan).
"""

from __future__ import annotations

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE auth.linked_sources
            ADD COLUMN webhook_token_hash bytea,
            ADD COLUMN webhook_rotated_at timestamptz;
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX ux_linked_sources_webhook_token_hash
        ON auth.linked_sources (webhook_token_hash)
        WHERE webhook_token_hash IS NOT NULL;
        """
    )
    op.execute(
        "COMMENT ON COLUMN auth.linked_sources.webhook_token_hash IS "
        "'HMAC-SHA256(token) cho ChirpStack HTTP integration. Plaintext chỉ "
        "hiển thị 1 lần khi link/rotate, KHÔNG lưu DB. NULL = source không "
        "dùng webhook.';"
    )
    op.execute(
        "COMMENT ON COLUMN auth.linked_sources.webhook_rotated_at IS "
        "'Thời điểm rotate token gần nhất. NULL khi chưa rotate (token vẫn "
        "là token gốc cấp lúc link).';"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS auth.ux_linked_sources_webhook_token_hash;")
    op.execute(
        """
        ALTER TABLE auth.linked_sources
            DROP COLUMN IF EXISTS webhook_rotated_at,
            DROP COLUMN IF EXISTS webhook_token_hash;
        """
    )
