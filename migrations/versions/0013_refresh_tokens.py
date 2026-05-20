"""auth.refresh_tokens — revocable refresh token chain

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-19

Plan-auth-v2 step 2 — "Short-Lived JWTs with Revocable Refresh Tokens".

Pattern:
  * Access JWT vẫn 15 phút (short-lived) ở Authorization header.
  * Refresh token = opaque 256-bit random, HttpOnly Secure SameSite=Lax cookie,
    TTL 30 ngày, store SHA-256 hash trong bảng này (KHÔNG lưu plaintext).
  * Rotation-on-use: mỗi lần /refresh issue cặp mới (access + refresh) và
    mark token cũ `rotated_to = new.id`. Token cũ KHÔNG xoá ngay để detect
    reuse.
  * Theft detection: nếu ai đó present 1 token đã `rotated_to IS NOT NULL`,
    nghĩa là token này đã được dùng để rotate trước đó → có người clone →
    revoke toàn bộ `family_id` (cả attacker lẫn user phải re-login).

Schema:
  * `token_hash bytea UNIQUE` — SHA-256(token). Lookup by hash, không index
    plaintext (rủi ro DB leak).
  * `family_id uuid` — group rotation chain. Login đầu tạo family mới; rotate
    inherit family của parent.
  * `rotated_to uuid` nullable self-FK — null = chưa rotated, có giá trị =
    đã dùng để rotate sang token này (reuse-detection signal).
  * `revoked bool` + `revoked_at` — logout explicit hoặc family revoked do
    theft detection.
  * `user_agent` + `ip` — audit, không phải security gate (UA/IP có thể spoof).
"""

from __future__ import annotations

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE auth.refresh_tokens (
            id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id      uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
            token_hash   bytea NOT NULL UNIQUE,
            family_id    uuid NOT NULL,
            issued_at    timestamptz NOT NULL DEFAULT now(),
            expires_at   timestamptz NOT NULL,
            rotated_to   uuid NULL REFERENCES auth.refresh_tokens(id) ON DELETE SET NULL,
            revoked      boolean NOT NULL DEFAULT false,
            revoked_at   timestamptz NULL,
            user_agent   text NULL,
            ip           inet NULL
        );
        """
    )
    # Partial index: chỉ query active (chưa revoked) khi rotate/revoke.
    op.execute(
        "CREATE INDEX ix_refresh_tokens_user_active "
        "ON auth.refresh_tokens (user_id) WHERE revoked = false;"
    )
    # Family lookup cho theft-detection revoke-all.
    op.execute(
        "CREATE INDEX ix_refresh_tokens_family "
        "ON auth.refresh_tokens (family_id);"
    )
    op.execute(
        "COMMENT ON TABLE auth.refresh_tokens IS "
        "'Refresh token chain (plan-auth-v2). Rotation-on-use + theft detection qua family_id.';"
    )
    op.execute(
        "COMMENT ON COLUMN auth.refresh_tokens.token_hash IS "
        "'SHA-256 hash của opaque token (plaintext ở cookie). Lookup by hash, KHÔNG store plaintext.';"
    )
    op.execute(
        "COMMENT ON COLUMN auth.refresh_tokens.rotated_to IS "
        "'NULL = chưa dùng. Có giá trị = đã rotate sang token kế. Dùng lại token có rotated_to != NULL = theft → revoke family.';"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS auth.refresh_tokens;")
