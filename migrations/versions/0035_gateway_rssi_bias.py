"""Bo sung cot rssi_bias_db cho per-gateway physics RSSI calibration.

Ly do: Stage 1 (ITU-R P.1812 + DSM) co BIAS he thong rieng tung gateway (do
chieu cao/vi tri anten/moi truong thuc khac nominal). Do tren survey holdout:
bias inter-gateway dao dong tu -8 den +29 dB (std 10.6). Hieu chinh per-gateway
offset (fit tren train window) giam test RMSE 13.88 -> 8.32 dB, bias -4.3 -> ~0.

Co che: rssi_bias_db = dB CONG vao RSSI du doan cua gateway do (Stage1ItuModel
tru khoi pl_db). Calibrate bang scripts/backfill_gateway_rssi_bias.py =
mean(measured_rssi - physics_rssi) per gateway tren train window.

NULL = khong hieu chinh (fallback 0 o application layer). CHECK -60..+60 =
sanity range (bias > 60 dB la bug data/physics).
"""

from __future__ import annotations

from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE geo.gateways ADD COLUMN rssi_bias_db double precision NULL;")
    op.execute(
        "ALTER TABLE geo.gateways "
        "ADD CONSTRAINT chk_rssi_bias_range CHECK ("
        "rssi_bias_db IS NULL OR rssi_bias_db BETWEEN -60 AND 60);"
    )
    op.execute(
        "COMMENT ON COLUMN geo.gateways.rssi_bias_db IS "
        "'Per-gateway physics RSSI bias correction (dB, cong vao RSSI du doan). "
        "NULL = khong hieu chinh. Calibrate tu mean(measured - physics) per "
        "gateway qua scripts/backfill_gateway_rssi_bias.py.';"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE geo.gateways DROP CONSTRAINT IF EXISTS chk_rssi_bias_range;")
    op.execute("ALTER TABLE geo.gateways DROP COLUMN IF EXISTS rssi_bias_db;")
