"""me.upload_batches: thêm kind 'live_session'

Revision ID: 0031
Revises: 0030
Create Date: 2026-06-14

Live session batch: 1 chuyến khảo sát = 1 batch chung cho nhiều lần sync
incremental (frontend timer 20s). Phân biệt với 'sync_lpwanmapper' vì
mỗi sync chu kỳ KHÔNG tạo batch mới — reuse batch_id qua endpoint
POST /me/live-sessions/{batch_id}/sync. UI "Quản lý dữ liệu" sẽ thấy
1 batch / chuyến thay vì hàng chục batch nhỏ lẻ.
"""

from __future__ import annotations

from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE me.upload_batches DROP CONSTRAINT IF EXISTS chk_batch_kind;"
    )
    op.execute(
        "ALTER TABLE me.upload_batches ADD CONSTRAINT chk_batch_kind CHECK ("
        "kind IN ('csv','json','sync_lpwanmapper','sync_chirpstack','live_session')"
        ");"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE me.upload_batches DROP CONSTRAINT IF EXISTS chk_batch_kind;"
    )
    op.execute(
        "ALTER TABLE me.upload_batches ADD CONSTRAINT chk_batch_kind CHECK ("
        "kind IN ('csv','json','sync_lpwanmapper','sync_chirpstack')"
        ");"
    )
