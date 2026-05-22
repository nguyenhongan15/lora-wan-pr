"""contribution trust pipeline — submitted_for_community + user reputation stats

Revision ID: 0017
Revises: 0016
Create Date: 2026-05-22

Plan community-data-contribution: tách "đóng góp cộng đồng" thành quyết định
per-measurement thay vì chỉ dựa cờ `linked_sources.contribute_to_community`
(per-source).

  * `submitted_for_community` trên ts.survey_quarantine + ts.survey_training
    = nguồn sự thật duy nhất cho pipeline TrustValidator quyết định có promote
    record sang training hay không.
  * Backfill từ `linked_sources.contribute_to_community` để các record đang
    có trong DB không đổi behavior (idempotent).
  * Partial index pending: queue rows quarantine đang chờ validate
    (submitted_for_community=true AND reject_reason IS NULL).

  * `auth.users.email_verified` (bool, default false) + `contribution_stats`
    (JSONB) — phục vụ L3 reputation gate của TrustValidator. JSONB thay vì
    cột rời để không phải migration mỗi lần thêm metric (accepted/rejected/
    last_at + future fields).
"""

from __future__ import annotations

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── ts.survey_quarantine ─────────────────────────────────────────────
    op.execute(
        """
        ALTER TABLE ts.survey_quarantine
            ADD COLUMN submitted_for_community boolean NOT NULL DEFAULT false;
        """
    )
    # Backfill: rows hiện có thuộc linked_source đã opt-in → flag true. Bảo
    # đảm webhook ingest trước migration không bị "đứng" ở quarantine sau
    # khi pipeline mới deploy (user đã opt-in từ trước thì mong đợi data
    # vẫn được promote).
    op.execute(
        """
        UPDATE ts.survey_quarantine q
        SET submitted_for_community = true
        FROM auth.linked_sources ls
        WHERE q.linked_source_id = ls.id
          AND ls.contribute_to_community = true;
        """
    )
    op.execute(
        """
        CREATE INDEX ix_survey_quarantine_pending_community
        ON ts.survey_quarantine (timestamp DESC)
        WHERE submitted_for_community = true AND reject_reason IS NULL;
        """
    )

    # ── ts.survey_training ───────────────────────────────────────────────
    # Mọi record đã ở training đều là "đã đóng góp cộng đồng" định nghĩa →
    # backfill true thẳng (không cần JOIN linked_sources).
    op.execute(
        """
        ALTER TABLE ts.survey_training
            ADD COLUMN submitted_for_community boolean NOT NULL DEFAULT true;
        """
    )

    # ── auth.users — email verification + reputation stats ──────────────
    # email_verified default false: user cũ chưa có email verification flow
    # → mặc định coi như chưa verify. Khi flow verify deploy, user click link
    # → set true. L3 reputation: +0.3 score nếu verified.
    op.execute(
        """
        ALTER TABLE auth.users
            ADD COLUMN email_verified boolean NOT NULL DEFAULT false,
            ADD COLUMN contribution_stats jsonb NOT NULL DEFAULT
                '{"accepted": 0, "rejected": 0, "last_at": null}'::jsonb;
        """
    )
    op.execute(
        "COMMENT ON COLUMN auth.users.contribution_stats IS "
        "'TrustValidator reputation stats: {accepted,rejected,last_at}. "
        "Updated atomically sau mỗi validate. JSONB tránh migration mỗi lần thêm metric.';"
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE auth.users
            DROP COLUMN IF EXISTS contribution_stats,
            DROP COLUMN IF EXISTS email_verified;
        """
    )
    op.execute(
        "ALTER TABLE ts.survey_training DROP COLUMN IF EXISTS submitted_for_community;"
    )
    op.execute("DROP INDEX IF EXISTS ts.ix_survey_quarantine_pending_community;")
    op.execute(
        "ALTER TABLE ts.survey_quarantine DROP COLUMN IF EXISTS submitted_for_community;"
    )
