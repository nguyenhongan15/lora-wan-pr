"""admin manual-review gate — review_status + reviewer audit columns

Revision ID: 0018
Revises: 0017
Create Date: 2026-05-25

Đổi pipeline đóng góp cộng đồng từ auto-promote sang manual gate:

  * Pass auto-validate L1/L2/L3 → KHÔNG còn INSERT thẳng vào survey_training.
    Thay vào đó UPDATE quarantine.review_status='pending_review' chờ admin duyệt.
  * Admin approve → INSERT training + review_status='approved'.
  * Admin reject → review_status='rejected' + review_note.
  * Auto-reject L1/L2/L3 fail (reject_reason ≠ NULL) → KHÔNG enter pending queue,
    review_status giữ NULL (rác hiển nhiên không cần admin review).

Backward compat: rows hiện có trong training KHÔNG bị ảnh hưởng (không backfill,
không xoá). Rows quarantine cũ có review_status=NULL — không xuất hiện trong
admin queue mới (queue chỉ filter review_status='pending_review').
"""

from __future__ import annotations

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE ts.survey_quarantine
            ADD COLUMN review_status        text,
            ADD COLUMN reviewed_by_user_id  uuid REFERENCES auth.users(id) ON DELETE SET NULL,
            ADD COLUMN reviewed_at          timestamptz,
            ADD COLUMN review_note          text;
        """
    )
    op.execute(
        """
        ALTER TABLE ts.survey_quarantine
            ADD CONSTRAINT survey_quarantine_review_status_check
            CHECK (review_status IS NULL OR review_status IN
                ('pending_review', 'approved', 'rejected'));
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN ts.survey_quarantine.review_status IS
            'Admin review state: NULL=legacy/auto-rejected; '
            'pending_review=passed auto-validate, waiting admin; '
            'approved=admin OK, row also in survey_training; '
            'rejected=admin rejected, review_note explains why.';
        """
    )
    op.execute(
        """
        CREATE INDEX ix_survey_quarantine_pending_review
        ON ts.survey_quarantine (timestamp DESC)
        WHERE review_status = 'pending_review';
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ts.ix_survey_quarantine_pending_review;")
    op.execute(
        """
        ALTER TABLE ts.survey_quarantine
            DROP CONSTRAINT IF EXISTS survey_quarantine_review_status_check,
            DROP COLUMN IF EXISTS review_note,
            DROP COLUMN IF EXISTS reviewed_at,
            DROP COLUMN IF EXISTS reviewed_by_user_id,
            DROP COLUMN IF EXISTS review_status;
        """
    )
