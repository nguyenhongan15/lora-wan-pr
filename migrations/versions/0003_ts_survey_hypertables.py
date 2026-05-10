"""ts.survey_quarantine + ts.survey_training (TimescaleDB hypertables)

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-05

Theo system-architecture.md §5.3:

  * 2 bảng RIÊNG BIỆT (không phải 1 bảng + flag) — "define special cases out
    of existence". Query training set không cần WHERE quarantined=false.
  * Cả hai đều là hypertable (partition theo timestamp).
  * GiST index trên location, BRIN trên timestamp (append-only).
  * FK xuống geo.gateways(id) — nhưng nullable (uploader có thể không biết
    serving gateway lúc upload).
"""

from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── ts.survey_quarantine ─────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE ts.survey_quarantine (
            id                  uuid NOT NULL DEFAULT gen_random_uuid(),
            timestamp           timestamptz NOT NULL,
            location            geography(Point, 4326) NOT NULL,
            rssi_dbm            real NOT NULL,
            snr_db              real NOT NULL,
            spreading_factor    smallint NOT NULL,
            frequency_mhz       double precision NOT NULL DEFAULT 923.0,
            device_id           text,
            serving_gateway_id  uuid REFERENCES geo.gateways(id) ON DELETE SET NULL,
            uploader_id         uuid NOT NULL,
            uploaded_at         timestamptz NOT NULL DEFAULT now(),
            reject_reason       text,
            CONSTRAINT chk_q_sf       CHECK (spreading_factor BETWEEN 7 AND 12),
            CONSTRAINT chk_q_rssi     CHECK (rssi_dbm BETWEEN -150 AND -30),
            CONSTRAINT chk_q_snr      CHECK (snr_db BETWEEN -30 AND 30),
            PRIMARY KEY (timestamp, id)
        );
        """
    )
    op.execute(
        "SELECT create_hypertable('ts.survey_quarantine', 'timestamp', if_not_exists => TRUE);"
    )
    op.execute(
        "CREATE INDEX survey_quarantine_loc_gix ON ts.survey_quarantine USING gist (location);"
    )
    op.execute(
        "CREATE INDEX survey_quarantine_ts_brin ON ts.survey_quarantine USING brin (timestamp);"
    )
    op.execute(
        "CREATE INDEX survey_quarantine_uploader_idx ON ts.survey_quarantine (uploader_id, uploaded_at DESC);"
    )

    # ── ts.survey_training ───────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE ts.survey_training (
            id                  uuid NOT NULL,
            timestamp           timestamptz NOT NULL,
            location            geography(Point, 4326) NOT NULL,
            rssi_dbm            real NOT NULL,
            snr_db              real NOT NULL,
            spreading_factor    smallint NOT NULL,
            frequency_mhz       double precision NOT NULL DEFAULT 923.0,
            device_id           text,
            serving_gateway_id  uuid REFERENCES geo.gateways(id) ON DELETE SET NULL,
            uploader_id         uuid NOT NULL,
            weight              real NOT NULL DEFAULT 1.0,
            promoted_at         timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT chk_t_sf     CHECK (spreading_factor BETWEEN 7 AND 12),
            CONSTRAINT chk_t_rssi   CHECK (rssi_dbm BETWEEN -150 AND -30),
            CONSTRAINT chk_t_snr    CHECK (snr_db BETWEEN -30 AND 30),
            CONSTRAINT chk_t_weight CHECK (weight > 0),
            PRIMARY KEY (timestamp, id)
        );
        """
    )
    op.execute(
        "SELECT create_hypertable('ts.survey_training', 'timestamp', if_not_exists => TRUE);"
    )
    op.execute(
        "CREATE INDEX survey_training_loc_gix ON ts.survey_training USING gist (location);"
    )
    op.execute(
        "CREATE INDEX survey_training_ts_brin ON ts.survey_training USING brin (timestamp);"
    )
    op.execute(
        "CREATE INDEX survey_training_gw_idx ON ts.survey_training (serving_gateway_id);"
    )

    op.execute(
        "COMMENT ON TABLE ts.survey_quarantine IS 'Survey uploads chờ validate. Promoted → ts.survey_training hoặc giữ lại nếu reject.';"
    )
    op.execute(
        "COMMENT ON TABLE ts.survey_training IS 'Survey đã validate, dùng cho ML training. KHÔNG có flag quarantined.';"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ts.survey_training;")
    op.execute("DROP TABLE IF EXISTS ts.survey_quarantine;")
