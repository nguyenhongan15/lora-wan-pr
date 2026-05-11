"""geo.gateways bidirectional link budget fields

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-11

Bổ sung 2 cột cho bidirectional link budget (xem
docs/data-architecture.md §6.1 sau refactor):

  * rx_antenna_gain_dbi : RX antenna gain khi gateway thu uplink.
    NULL = duplex symmetric (= antenna_gain_dbi); resolution diễn ra ở
    application layer (path_loss._resolve_rx_gain). Đa số IoT gateway dùng
    anten đơn duplex nên NULL phổ biến — không backfill ép buộc.

  * rx_sensitivity_dbm : RX sensitivity per chain. NULL = derive từ SF
    table (Semtech SX1302 datasheet) ở application layer.

Cột cũ `antenna_gain_dbi` đổi semantic thành "TX antenna gain" (giữ tên
để khỏi phá schema). Comment cập nhật.

Both columns NULLABLE — không backfill, application layer xử lý None.
CHECK constraints sanity range; chấp nhận NULL.
"""

from __future__ import annotations

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE geo.gateways "
        "ADD COLUMN rx_antenna_gain_dbi double precision NULL;"
    )
    op.execute(
        "ALTER TABLE geo.gateways "
        "ADD COLUMN rx_sensitivity_dbm double precision NULL;"
    )
    op.execute(
        "ALTER TABLE geo.gateways "
        "ADD CONSTRAINT chk_rx_gain_range CHECK ("
        "rx_antenna_gain_dbi IS NULL "
        "OR rx_antenna_gain_dbi BETWEEN -10 AND 30);"
    )
    op.execute(
        "ALTER TABLE geo.gateways "
        "ADD CONSTRAINT chk_rx_sens_range CHECK ("
        "rx_sensitivity_dbm IS NULL "
        "OR rx_sensitivity_dbm BETWEEN -150 AND -50);"
    )
    op.execute(
        "COMMENT ON COLUMN geo.gateways.antenna_gain_dbi IS "
        "'TX antenna gain (Gt) khi gateway phat downlink. dBi.';"
    )
    op.execute(
        "COMMENT ON COLUMN geo.gateways.rx_antenna_gain_dbi IS "
        "'RX antenna gain (Gr) khi gateway thu uplink. NULL = duplex "
        "symmetric, app layer fallback ve antenna_gain_dbi.';"
    )
    op.execute(
        "COMMENT ON COLUMN geo.gateways.rx_sensitivity_dbm IS "
        "'Gateway RX sensitivity per chain. NULL = derive tu SF table o "
        "application layer (Semtech SX1302 datasheet).';"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE geo.gateways DROP CONSTRAINT IF EXISTS chk_rx_sens_range;"
    )
    op.execute(
        "ALTER TABLE geo.gateways DROP CONSTRAINT IF EXISTS chk_rx_gain_range;"
    )
    op.execute(
        "ALTER TABLE geo.gateways DROP COLUMN IF EXISTS rx_sensitivity_dbm;"
    )
    op.execute(
        "ALTER TABLE geo.gateways DROP COLUMN IF EXISTS rx_antenna_gain_dbi;"
    )
