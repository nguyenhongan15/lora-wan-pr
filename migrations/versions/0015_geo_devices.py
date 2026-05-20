"""geo.devices — danh sách devices đồng bộ từ external source

Revision ID: 0015
Revises: 0014
Create Date: 2026-05-19

Mỗi linked_source có thể chứa nhiều device (devEui). Sync REST kéo metadata
device về để FE hiển thị "user X có Y devices, last seen ...". Table KHÔNG
phải dependency của ingest path — survey_quarantine vẫn lưu device_id text
thô. Devices table thuần là projection của provider data.

Quyết định:
  * Schema `geo` (cùng schema với gateways) — về mặt domain, device cũng là
    physical asset có toạ độ tiềm năng (GNSS). Khác với gateways: device
    không phải always-on, không có RX path → tách bảng nhưng cùng schema.
  * `external_id`/`source_type` provenance theo pattern migration 0007 cho
    geo.gateways. UNIQUE PARTIAL `(source_type, external_id)` chặn 2 user
    link cùng device qua cùng provider (collision rất hiếm vì devEui là
    EUI-64 toàn cầu).
  * `linked_source_id` ON DELETE SET NULL — user unlink source thì devices
    giữ lại cho audit (giống survey_*).
  * `last_seen_at` populate từ ChirpStack `lastSeenAt`. NULL = chưa thấy.
  * KHÔNG có CHECK `dev_eui ~ '^[0-9a-fA-F]{16}$'` — provider có thể trả
    format khác (Helium, TTN…); validate ở mapping layer thay vì DB.
"""

from __future__ import annotations

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE geo.devices (
            id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            dev_eui             text NOT NULL,
            name                text,
            source_type         text NOT NULL,
            external_id         text NOT NULL,
            linked_source_id    uuid REFERENCES auth.linked_sources(id) ON DELETE SET NULL,
            contributor_user_id uuid REFERENCES auth.users(id) ON DELETE SET NULL,
            last_seen_at        timestamptz,
            created_at          timestamptz NOT NULL DEFAULT now(),
            updated_at          timestamptz NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX ux_devices_external
        ON geo.devices (source_type, external_id);
        """
    )
    op.execute(
        "CREATE INDEX ix_devices_linked_source "
        "ON geo.devices (linked_source_id) "
        "WHERE linked_source_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_devices_contributor "
        "ON geo.devices (contributor_user_id) "
        "WHERE contributor_user_id IS NOT NULL;"
    )
    op.execute(
        "COMMENT ON TABLE geo.devices IS "
        "'External-source device registry. Synced khi user bấm sync hoặc "
        "admin global sync. Không phải dependency của ingest path.';"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS geo.ix_devices_contributor;")
    op.execute("DROP INDEX IF EXISTS geo.ix_devices_linked_source;")
    op.execute("DROP INDEX IF EXISTS geo.ux_devices_external;")
    op.execute("DROP TABLE IF EXISTS geo.devices;")
