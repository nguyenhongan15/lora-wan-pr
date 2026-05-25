"""auth.email_verification_tokens — single-use email verification token chain

Revision ID: 0019
Revises: 0018
Create Date: 2026-05-25

Email verification gate cho community contribution. User chưa verify email
KHÔNG được submit data cho community (gated ở POST /me/uploads/csv/promote
và PATCH /me/sources/{id} khi contribute_to_community=true).

Pattern mirror migration 0016 (password_reset_tokens):
  * Token = 32-byte urlsafe random (256-bit entropy), TTL 60 phút (config).
  * Store SHA-256 hash của token (giống password_reset_tokens), KHÔNG plaintext.
  * `used_at IS NULL` = unused; consume = SET used_at = now() trong UPDATE
    atomic (single-use enforced ở SQL layer).
  * Request mới khi vẫn còn token unused → invalidate-all-unused trước khi
    issue (mitigate email-forwarding scenario: user request 2 lần, link cũ
    phải vô hiệu).

Khác password reset: KHÔNG revoke refresh tokens khi consume — verify email
là augment trust, không phải security event đáng kick session.
"""

from __future__ import annotations

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE auth.email_verification_tokens (
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
        "CREATE INDEX ix_email_verification_tokens_user_unused "
        "ON auth.email_verification_tokens (user_id) WHERE used_at IS NULL;"
    )
    op.execute(
        "COMMENT ON TABLE auth.email_verification_tokens IS "
        "'Single-use email verification tokens. TTL ~60min, SHA-256 hashed. "
        "Gate cho community contribution submit.';"
    )
    op.execute(
        "COMMENT ON COLUMN auth.email_verification_tokens.token_hash IS "
        "'SHA-256 hash của opaque token (plaintext chỉ trong email). Lookup by hash.';"
    )
    op.execute(
        "COMMENT ON COLUMN auth.email_verification_tokens.used_at IS "
        "'NULL = chưa dùng. Có giá trị = đã consume single-use; reject mọi attempt sau.';"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS auth.email_verification_tokens;")
