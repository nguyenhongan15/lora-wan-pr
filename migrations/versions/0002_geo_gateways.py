"""geo.gateways table + GiST index

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-05

geo.gateways là entity nền cho coverage prediction. Theo
system-architecture.md §6.1.1.

Hard rule: geometry dùng SRID 4326 (WGS84). Index GiST.
"""

from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE geo.gateways (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            code            text UNIQUE NOT NULL,
            name            text NOT NULL,
            location        geography(Point, 4326) NOT NULL,
            altitude_m      double precision NOT NULL DEFAULT 0,
            antenna_height_m double precision NOT NULL DEFAULT 10,
            antenna_gain_dbi double precision NOT NULL DEFAULT 2.0,
            tx_power_dbm    double precision NOT NULL DEFAULT 14.0,
            frequency_mhz   double precision NOT NULL DEFAULT 923.0,
            owner_org       text,
            is_public       boolean NOT NULL DEFAULT true,
            created_at      timestamptz NOT NULL DEFAULT now(),
            updated_at      timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT chk_freq_lora_band CHECK (
                frequency_mhz IN (433.0, 868.0, 915.0, 923.0)
            ),
            CONSTRAINT chk_height_nonneg CHECK (antenna_height_m >= 0),
            CONSTRAINT chk_tx_power_range CHECK (tx_power_dbm BETWEEN -10 AND 30)
        );
        """
    )
    op.execute(
        "CREATE INDEX gateways_location_gix ON geo.gateways USING gist (location);"
    )
    op.execute(
        "CREATE INDEX gateways_code_idx ON geo.gateways (code);"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION geo.touch_updated_at() RETURNS trigger AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER gateways_set_updated_at
        BEFORE UPDATE ON geo.gateways
        FOR EACH ROW EXECUTE FUNCTION geo.touch_updated_at();
        """
    )

    op.execute("COMMENT ON TABLE geo.gateways IS 'LoRa gateways (public + private)';")
    op.execute("COMMENT ON COLUMN geo.gateways.location IS 'WGS84 (SRID 4326)';")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS gateways_set_updated_at ON geo.gateways;")
    op.execute("DROP FUNCTION IF EXISTS geo.touch_updated_at();")
    op.execute("DROP TABLE IF EXISTS geo.gateways;")
