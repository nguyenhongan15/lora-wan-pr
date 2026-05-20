"""auth.password_reset_tokens — single-use reset token chain

Revision ID: 0016
Revises: 0015
Create Date: 2026-05-20

Pre-deploy checklist §2: password reset link phải có TTL ngắn + single-use.

Pattern:
  * Token = 32-byte urlsafe random (256-bit entropy), TTL 30 phút (config).
  * Store SHA-256 hash của token (giống refresh_tokens), KHÔNG plaintext.
  * `used_at IS NULL` = unused; consume = SET used_at = now() trong UPDATE
    atomic (single-use enforced ở SQL layer).
  * Request mới khi vẫn còn token unused → invalidate-all-unused trước khi
    issue (chống tấn công "đầy bảng" + dùng lại link cũ sau khi user đã
    request lại).

KHÔNG có family/rotation như refresh_tokens — reset token là one-shot,
không rotate. Confirm thành công → consume + revoke tất cả refresh tokens
của user (force re-login mọi device, mitigate stolen-cookie scenario).
"""

from __future__ import annotations

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE auth.password_reset_tokens (
            id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id      uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
            token_hash   bytea NOT NULL UNIQUE,
            expires_at   timestamptz NOT NULL,
            used_at      timestamptz NULL,
            created_at   timestamptz NOT NULL DEFAULT now()
        );
        """
    )
    # Partial index: scan unused tokens của 1 user (issue mới → invalidate cũ).
    op.execute(
        "CREATE INDEX ix_password_reset_tokens_user_unused "
        "ON auth.password_reset_tokens (user_id) WHERE used_at IS NULL;"
    )
    op.execute(
        "COMMENT ON TABLE auth.password_reset_tokens IS "
        "'Single-use password reset tokens. TTL ~30min, SHA-256 hashed. Pre-deploy checklist §2.';"
    )
    op.execute(
        "COMMENT ON COLUMN auth.password_reset_tokens.token_hash IS "
        "'SHA-256 hash của opaque token (plaintext chỉ trong email). Lookup by hash.';"
    )
    op.execute(
        "COMMENT ON COLUMN auth.password_reset_tokens.used_at IS "
        "'NULL = chưa dùng. Có giá trị = đã consume single-use; reject mọi attempt sau.';"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS auth.password_reset_tokens;")
