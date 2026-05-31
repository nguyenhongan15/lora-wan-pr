"""geo.gateways noise_floor_dbm column

Revision ID: 0020
Revises: 0019
Create Date: 2026-05-31

Bo sung cot noise_floor_dbm cho per-gateway noise floor (uplink link budget).

Ly do: Constant -117 dBm (thermal -174 + 10log(125kHz) + NF 6dB) la lower bound
ly thuyet. Do measure tu Nov-Dec 2025 Da Nang survey thay actual NF
inter-gateway dao dong tu -110 den -99 dBm (interference-dominated environment).
Dung constant lam Stage 1 SNR over-optimistic +21 dB, recommend_sf saI SF7 ~88%
truong hop.

NULL = fallback ve DEFAULT_NOISE_FLOOR_DBM (-104) o application layer (rule
phu hop empirically tu 8 gateway hien co).

CHECK constraint: -130 (thermal floor + NF 0) den -80 (interference cao bat
thuong) — sanity range, accept NULL.
"""

from __future__ import annotations

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE geo.gateways "
        "ADD COLUMN noise_floor_dbm double precision NULL;"
    )
    op.execute(
        "ALTER TABLE geo.gateways "
        "ADD CONSTRAINT chk_noise_floor_range CHECK ("
        "noise_floor_dbm IS NULL "
        "OR noise_floor_dbm BETWEEN -130 AND -80);"
    )
    op.execute(
        "COMMENT ON COLUMN geo.gateways.noise_floor_dbm IS "
        "'Per-gateway measured noise floor (dBm) at 125 kHz BW. NULL = "
        "fallback ve DEFAULT_NOISE_FLOOR_DBM o application layer. Calibrate "
        "tu survey rssi - snr theo gateway.';"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE geo.gateways DROP CONSTRAINT IF EXISTS chk_noise_floor_range;"
    )
    op.execute(
        "ALTER TABLE geo.gateways DROP COLUMN IF EXISTS noise_floor_dbm;"
    )
