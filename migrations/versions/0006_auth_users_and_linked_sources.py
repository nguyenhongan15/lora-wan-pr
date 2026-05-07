"""auth.users + auth.linked_sources

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-07

CB-3 plan-auth-v1 §6.1 + §6.2 — identity layer 1 (web-app users) và linked
external data sources (1 user → N sources).

Quyết định:
  * Schema mới `auth` — bounded-context naming nhất quán với geo/ts/address/
    audit (system-architecture.md §6). Plan §6.1 viết DDL không có schema
    prefix; chọn `auth` để tránh đẩy table identity xuống public.
  * id UUID với gen_random_uuid() — deviate khỏi BIGSERIAL trong plan §6.1
    để giữ consistency với schema hiện hữu (geo.gateways.id, ts.survey_*.id
    đều UUID; uploader_id uuid trong survey hypertables là tiền đề tự nhiên
    của contributor_user_id).
  * `status` (kỹ thuật: active/paused/failed) tách RIÊNG khỏi
    `contribute_to_community` (chính sách: data có lên bản đồ cộng đồng
    không) — plan §3.3, §6.2. Hai cờ độc lập, không gộp thành 1 enum.
  * Partial index `ix_linked_sources_eligible` chỉ index những source
    eligible cho sync_all() — plan §3.4 sync orchestrator filter.
"""

from __future__ import annotations

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS auth;")
    op.execute("COMMENT ON SCHEMA auth IS 'Identity (users) + linked external data sources';")

    # ── auth.users ──────────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE auth.users (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            email           text NOT NULL UNIQUE,
            password_hash   text NOT NULL,
            is_admin        boolean NOT NULL DEFAULT false,
            disabled        boolean NOT NULL DEFAULT false,
            created_at      timestamptz NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "COMMENT ON TABLE auth.users IS "
        "'Web-app users (identity layer 1). Email/password do app quản lý, KHÔNG liên quan lpwanmapper.';"
    )
    op.execute(
        "COMMENT ON COLUMN auth.users.disabled IS "
        "'Admin disable = flag, không xoá. Query map JOIN users + WHERE NOT disabled.';"
    )

    # ── auth.linked_sources ─────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE auth.linked_sources (
            id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id                  uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
            source_type              text NOT NULL,
            label                    text NOT NULL,
            credentials_encrypted    bytea NOT NULL,
            status                   text NOT NULL DEFAULT 'active',
            contribute_to_community  boolean NOT NULL DEFAULT false,
            contributed_at           timestamptz,
            last_sync_at             timestamptz,
            last_sync_error          text,
            created_at               timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT chk_ls_status CHECK (status IN ('active','paused','failed'))
        );
        """
    )
    op.execute(
        "CREATE INDEX ix_linked_sources_user ON auth.linked_sources (user_id);"
    )
    op.execute(
        """
        CREATE INDEX ix_linked_sources_eligible
        ON auth.linked_sources (source_type)
        WHERE status = 'active' AND contribute_to_community = true;
        """
    )
    op.execute(
        "COMMENT ON TABLE auth.linked_sources IS "
        "'1 user → N nguồn data ngoài (lpwanmapper, chirpstack, csv...). "
        "credentials_encrypted = Fernet/AES-GCM blob, key trong env.';"
    )
    op.execute(
        "COMMENT ON COLUMN auth.linked_sources.status IS "
        "'Kỹ thuật: active/paused/failed — có pull data từ source không.';"
    )
    op.execute(
        "COMMENT ON COLUMN auth.linked_sources.contribute_to_community IS "
        "'Chính sách: data có lên bản đồ cộng đồng không. Default false (privacy opt-in).';"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS auth.linked_sources;")
    op.execute("DROP TABLE IF EXISTS auth.users;")
    op.execute("DROP SCHEMA IF EXISTS auth;")
