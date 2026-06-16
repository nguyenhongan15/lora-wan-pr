"""batch_id trên gateway_quarantine + pending_gateway status

Revision ID: 0032
Revises: 0031
Create Date: 2026-06-17

Đổi flow review: gateway + điểm đo đi cùng 1 batch.

  * `geo.gateway_quarantine.batch_id` (FK→me.upload_batches) — sync nào tạo
    gateway pending thì lưu batch đó. ON DELETE SET NULL: xoá batch chỉ
    detach, không xoá gateway pending (admin có thể vẫn duyệt).
  * `ts.survey_quarantine.review_status` thêm value `'pending_gateway'` —
    dùng khi admin "Duyệt điểm đo (không duyệt gateway)": rows trỏ gateway
    mới giữ ở status này, chờ admin duyệt gateway sau → auto-promote.
"""

from __future__ import annotations

from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE geo.gateway_quarantine
            ADD COLUMN batch_id uuid REFERENCES me.upload_batches(id) ON DELETE SET NULL;
        """
    )
    op.execute(
        "CREATE INDEX ix_gateway_quarantine_batch_id "
        "ON geo.gateway_quarantine (batch_id) WHERE batch_id IS NOT NULL;"
    )
    op.execute(
        """
        ALTER TABLE ts.survey_quarantine
            DROP CONSTRAINT IF EXISTS survey_quarantine_review_status_check;
        """
    )
    op.execute(
        """
        ALTER TABLE ts.survey_quarantine
            ADD CONSTRAINT survey_quarantine_review_status_check
            CHECK (review_status IS NULL OR review_status IN
                ('pending_review', 'pending_gateway', 'approved', 'rejected'));
        """
    )
    op.execute(
        """
        CREATE INDEX ix_survey_quarantine_pending_gateway
        ON ts.survey_quarantine (serving_gateway_eui)
        WHERE review_status = 'pending_gateway';
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ts.ix_survey_quarantine_pending_gateway;")
    op.execute(
        """
        ALTER TABLE ts.survey_quarantine
            DROP CONSTRAINT IF EXISTS survey_quarantine_review_status_check;
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
    op.execute("DROP INDEX IF EXISTS geo.ix_gateway_quarantine_batch_id;")
    op.execute("ALTER TABLE geo.gateway_quarantine DROP COLUMN IF EXISTS batch_id;")
