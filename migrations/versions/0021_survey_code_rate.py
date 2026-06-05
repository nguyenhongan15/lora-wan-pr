"""ts.survey_quarantine + ts.survey_training code_rate column

Revision ID: 0021
Revises: 0020
Create Date: 2026-06-05

Bo sung cot code_rate (LoRa coding rate, vd "4/5"/"4/6"/"4/7"/"4/8") cho 2
hypertable survey. Source thuc te:
  * lpwanmapper / ChirpStack uplink: txInfo.modulation.lora.codeRate
    (enum string "CR_4_5" / "CR_4_6" / ...). Adapter convert sang "X/Y".
  * CSV upload: hien tai khong co cot → NULL.
  * Historic rows: NULL (popup hien "—").

Nullable text — khong CHECK constraint vi muon accept dang adapter-specific
trong tuong lai (vd "4/5SF"). Validate o application layer khi can.
"""

from __future__ import annotations

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE ts.survey_quarantine ADD COLUMN code_rate text;")
    op.execute("ALTER TABLE ts.survey_training ADD COLUMN code_rate text;")
    op.execute(
        "COMMENT ON COLUMN ts.survey_quarantine.code_rate IS "
        "'LoRa coding rate \"X/Y\" (vd 4/5). NULL khi source khong cung cap.';"
    )
    op.execute(
        "COMMENT ON COLUMN ts.survey_training.code_rate IS "
        "'LoRa coding rate \"X/Y\" (vd 4/5). NULL khi source khong cung cap.';"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE ts.survey_training DROP COLUMN IF EXISTS code_rate;")
    op.execute("ALTER TABLE ts.survey_quarantine DROP COLUMN IF EXISTS code_rate;")
