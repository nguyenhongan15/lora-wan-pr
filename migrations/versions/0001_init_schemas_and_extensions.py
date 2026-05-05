"""init schemas (geo/ts/address/audit) and required extensions

Revision ID: 0001
Revises:
Create Date: 2026-05-05

Mục tiêu:
  - Tạo 4 schema cố định: geo, ts, address, audit (theo system-architecture.md §6).
  - Bật extension: postgis, timescaledb, unaccent, pg_trgm, pgcrypto.

KHÔNG tạo bảng ở đây — bảng được thêm trong migration sau (tách concern).
"""

from __future__ import annotations

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Extensions
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;")
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent;")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")  # gen_random_uuid()

    # Schemas (theo bounded context)
    op.execute("CREATE SCHEMA IF NOT EXISTS geo;")
    op.execute("CREATE SCHEMA IF NOT EXISTS ts;")
    op.execute("CREATE SCHEMA IF NOT EXISTS address;")
    op.execute("CREATE SCHEMA IF NOT EXISTS audit;")

    op.execute("COMMENT ON SCHEMA geo IS 'Gateways, antennas, static spatial entities';")
    op.execute("COMMENT ON SCHEMA ts IS 'Time-series: survey hypertables (quarantine + training, riêng biệt)';")
    op.execute("COMMENT ON SCHEMA address IS 'Vietnamese canonical address (unaccent generated column)';")
    op.execute("COMMENT ON SCHEMA audit IS 'Compliance log (plain table, append-only)';")


def downgrade() -> None:
    # Cẩn thận: drop schema = mất tất cả bảng bên trong.
    # Chỉ chạy ở dev/test. Production migrations phải reversible từng bước.
    op.execute("DROP SCHEMA IF EXISTS audit CASCADE;")
    op.execute("DROP SCHEMA IF EXISTS address CASCADE;")
    op.execute("DROP SCHEMA IF EXISTS ts CASCADE;")
    op.execute("DROP SCHEMA IF EXISTS geo CASCADE;")
    # Extensions giữ nguyên (có thể bị shared với DB khác).
