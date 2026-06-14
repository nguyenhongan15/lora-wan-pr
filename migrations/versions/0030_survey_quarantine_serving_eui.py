"""ts.survey_quarantine.serving_gateway_eui — backfill FK sau gateway promote

Revision ID: 0030
Revises: 0029
Create Date: 2026-06-14

Khi sync ingest measurement tham chiếu gateway đang ở geo.gateway_quarantine
(chưa admin duyệt), `serving_gateway_id` (FK xuống geo.gateways.id) bắt buộc
NULL — chưa có row tương ứng. Để backfill được sau khi admin approve gateway,
ta lưu `serving_gateway_eui` (= code) song song. Promote flow query
ts.survey_quarantine WHERE serving_gateway_eui = :new_code AND
serving_gateway_id IS NULL → UPDATE serving_gateway_id = :new_gateway_id.

Không backfill cho measurement gắn gateway đã có trong geo.gateways (vẫn
ghi serving_gateway_id trực tiếp, serving_gateway_eui có thể NULL hoặc bằng
code của gateway — không bắt buộc).
"""

from __future__ import annotations

from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE ts.survey_quarantine "
        "ADD COLUMN serving_gateway_eui text;"
    )
    op.execute(
        "CREATE INDEX ix_survey_quarantine_pending_gw_eui "
        "ON ts.survey_quarantine (serving_gateway_eui) "
        "WHERE serving_gateway_id IS NULL AND serving_gateway_eui IS NOT NULL;"
    )
    op.execute(
        "COMMENT ON COLUMN ts.survey_quarantine.serving_gateway_eui IS "
        "'EUI của serving gateway. Khi gateway còn ở geo.gateway_quarantine, "
        "serving_gateway_id=NULL; admin approve gateway → backfill FK qua cột "
        "này.';"
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS ts.ix_survey_quarantine_pending_gw_eui;"
    )
    op.execute(
        "ALTER TABLE ts.survey_quarantine "
        "DROP COLUMN IF EXISTS serving_gateway_eui;"
    )
