"""relax chk_*_rssi upper bound: -30 → 0 dBm

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-08

Constraint cũ `rssi_dbm BETWEEN -150 AND -30` reject valid LoRa data: gateway
ở close-range có thể đo RSSI từ -29 đến -10 dBm (lpwanmapper community data
chứa nhiều record -29 dBm). Hệ quả: sync external provider fail 500 khi
hypertable chunk insert hit constraint.

Quyết định:
  * Nới upper bound 0 dBm (RSSI luôn âm với LoRa receiver; 0 đủ headroom).
  * Vẫn giữ lower -150 và CHECK constraint — chặn rác (`+10`, `9999`).
  * DROP + ADD trong cùng migration; TimescaleDB hypertable tự propagate
    sang chunks qua ALTER TABLE.
"""

from __future__ import annotations

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE ts.survey_training DROP CONSTRAINT chk_t_rssi;")
    op.execute(
        "ALTER TABLE ts.survey_training "
        "ADD CONSTRAINT chk_t_rssi CHECK (rssi_dbm BETWEEN -150 AND 0);"
    )

    op.execute("ALTER TABLE ts.survey_quarantine DROP CONSTRAINT chk_q_rssi;")
    op.execute(
        "ALTER TABLE ts.survey_quarantine "
        "ADD CONSTRAINT chk_q_rssi CHECK (rssi_dbm BETWEEN -150 AND 0);"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE ts.survey_quarantine DROP CONSTRAINT chk_q_rssi;")
    op.execute(
        "ALTER TABLE ts.survey_quarantine "
        "ADD CONSTRAINT chk_q_rssi CHECK (rssi_dbm BETWEEN -150 AND -30);"
    )

    op.execute("ALTER TABLE ts.survey_training DROP CONSTRAINT chk_t_rssi;")
    op.execute(
        "ALTER TABLE ts.survey_training "
        "ADD CONSTRAINT chk_t_rssi CHECK (rssi_dbm BETWEEN -150 AND -30);"
    )
