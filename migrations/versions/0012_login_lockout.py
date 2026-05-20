"""auth.users — login lockout columns

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-19

Plan-auth-v2 step 1 — rate-limit + account lockout.

Thêm 2 cột vào `auth.users` để track failed login attempts:
  * `failed_login_count int NOT NULL DEFAULT 0` — đếm liên tiếp lần sai
    password. Reset về 0 khi login thành công hoặc lockout window expire.
  * `locked_until timestamptz NULL` — null = không lock; > now = đang lock.

Lockout state ngay trên `auth.users` (không tách bảng `login_attempts`) vì
v2 chưa cần history queryable — YAGNI. Nếu sau này cần audit log full
attempts thì add bảng riêng, 2 cột này vẫn dùng cho fast-path.
"""

from __future__ import annotations

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE auth.users
        ADD COLUMN failed_login_count int NOT NULL DEFAULT 0,
        ADD COLUMN locked_until timestamptz NULL;
        """
    )
    op.execute(
        "COMMENT ON COLUMN auth.users.failed_login_count IS "
        "'Số lần liên tiếp login sai password. Reset 0 khi success hoặc lockout expire.';"
    )
    op.execute(
        "COMMENT ON COLUMN auth.users.locked_until IS "
        "'NULL = không lock. > now = đang lock; authenticate raise AccountLockedError.';"
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE auth.users
        DROP COLUMN IF EXISTS locked_until,
        DROP COLUMN IF EXISTS failed_login_count;
        """
    )
