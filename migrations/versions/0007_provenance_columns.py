"""provenance columns trên geo.gateways + ts.survey_*

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-07

CB-3 plan-auth-v1 §6.3 — gắn (contributor_user_id, linked_source_id,
external_id, source_type) vào các bảng cộng đồng để truy xuất nguồn gốc data
và filter theo contributor.

Quyết định:
  * Tất cả NULLABLE — data legacy (pre-CB-3) hoặc service account chung tag
    NULL. Không backfill; sync layer tag dần khi pull mới.
  * source_type DENORMALIZED (cũng có trong auth.linked_sources) — cho phép
    filter "show only lpwanmapper data" không cần JOIN. Trade-off: sync layer
    phải đảm bảo consistency lúc upsert (plan §6.4).
  * geo.gateways: UNIQUE PARTIAL (source_type, external_id) — dedup cross-
    contributor (plan §3.4 risk #3). Hai user link cùng physical gateway →
    UPSERT ON CONFLICT.
  * ts.survey_* hypertable: UNIQUE phải include partition column (timestamp);
    PARTIAL UNIQUE (timestamp, source_type, external_id) cho phép ON CONFLICT
    upsert. external_id của 1 measurement là unique per provider record →
    không bao giờ collision giữa các measurement khác nhau.
"""

from __future__ import annotations

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── geo.gateways ────────────────────────────────────────────────────────
    op.execute(
        """
        ALTER TABLE geo.gateways
            ADD COLUMN contributor_user_id uuid REFERENCES auth.users(id) ON DELETE SET NULL,
            ADD COLUMN linked_source_id    uuid REFERENCES auth.linked_sources(id) ON DELETE SET NULL,
            ADD COLUMN external_id         text,
            ADD COLUMN source_type         text;
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX ux_gateways_external
        ON geo.gateways (source_type, external_id)
        WHERE external_id IS NOT NULL;
        """
    )
    op.execute(
        "CREATE INDEX ix_gateways_contributor ON geo.gateways (contributor_user_id) "
        "WHERE contributor_user_id IS NOT NULL;"
    )

    # ── ts.survey_quarantine ────────────────────────────────────────────────
    op.execute(
        """
        ALTER TABLE ts.survey_quarantine
            ADD COLUMN contributor_user_id uuid REFERENCES auth.users(id) ON DELETE SET NULL,
            ADD COLUMN linked_source_id    uuid REFERENCES auth.linked_sources(id) ON DELETE SET NULL,
            ADD COLUMN external_id         text,
            ADD COLUMN source_type         text;
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX ux_survey_quarantine_external
        ON ts.survey_quarantine (timestamp, source_type, external_id)
        WHERE external_id IS NOT NULL;
        """
    )
    op.execute(
        "CREATE INDEX ix_survey_quarantine_contributor "
        "ON ts.survey_quarantine (contributor_user_id, uploaded_at DESC) "
        "WHERE contributor_user_id IS NOT NULL;"
    )

    # ── ts.survey_training ──────────────────────────────────────────────────
    op.execute(
        """
        ALTER TABLE ts.survey_training
            ADD COLUMN contributor_user_id uuid REFERENCES auth.users(id) ON DELETE SET NULL,
            ADD COLUMN linked_source_id    uuid REFERENCES auth.linked_sources(id) ON DELETE SET NULL,
            ADD COLUMN external_id         text,
            ADD COLUMN source_type         text;
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX ux_survey_training_external
        ON ts.survey_training (timestamp, source_type, external_id)
        WHERE external_id IS NOT NULL;
        """
    )
    op.execute(
        "CREATE INDEX ix_survey_training_contributor "
        "ON ts.survey_training (contributor_user_id, promoted_at DESC) "
        "WHERE contributor_user_id IS NOT NULL;"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ts.ix_survey_training_contributor;")
    op.execute("DROP INDEX IF EXISTS ts.ux_survey_training_external;")
    op.execute(
        """
        ALTER TABLE ts.survey_training
            DROP COLUMN IF EXISTS source_type,
            DROP COLUMN IF EXISTS external_id,
            DROP COLUMN IF EXISTS linked_source_id,
            DROP COLUMN IF EXISTS contributor_user_id;
        """
    )

    op.execute("DROP INDEX IF EXISTS ts.ix_survey_quarantine_contributor;")
    op.execute("DROP INDEX IF EXISTS ts.ux_survey_quarantine_external;")
    op.execute(
        """
        ALTER TABLE ts.survey_quarantine
            DROP COLUMN IF EXISTS source_type,
            DROP COLUMN IF EXISTS external_id,
            DROP COLUMN IF EXISTS linked_source_id,
            DROP COLUMN IF EXISTS contributor_user_id;
        """
    )

    op.execute("DROP INDEX IF EXISTS geo.ix_gateways_contributor;")
    op.execute("DROP INDEX IF EXISTS geo.ux_gateways_external;")
    op.execute(
        """
        ALTER TABLE geo.gateways
            DROP COLUMN IF EXISTS source_type,
            DROP COLUMN IF EXISTS external_id,
            DROP COLUMN IF EXISTS linked_source_id,
            DROP COLUMN IF EXISTS contributor_user_id;
        """
    )
