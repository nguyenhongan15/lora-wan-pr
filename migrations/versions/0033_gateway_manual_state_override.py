"""Manual state override cho gateway

Revision ID: 0033
Revises: 0032
Create Date: 2026-06-17

Admin có thể "ghim" trạng thái gateway thủ công, bỏ qua derived state từ
ChirpStack ListGateways / MAX(survey_training.timestamp).

  * `geo.gateways.manual_state_override` text NULL — khi set, _to_response
    trả luôn value này thay vì state_map. Khi NULL → fallback về derived
    state như cũ.
  * CHECK: phải IN ('online','offline','never_seen') OR NULL.
  * Không index — query single-row qua PK, không filter theo cột này.
"""

from __future__ import annotations

from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE geo.gateways
            ADD COLUMN manual_state_override text;
        """
    )
    op.execute(
        """
        ALTER TABLE geo.gateways
            ADD CONSTRAINT gateways_manual_state_override_check
            CHECK (manual_state_override IS NULL OR manual_state_override IN
                ('online', 'offline', 'never_seen'));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE geo.gateways
            DROP CONSTRAINT IF EXISTS gateways_manual_state_override_check;
        """
    )
    op.execute(
        "ALTER TABLE geo.gateways DROP COLUMN IF EXISTS manual_state_override;"
    )
