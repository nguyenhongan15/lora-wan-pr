"""me.upload_batches + drop linked_sources.contribute_to_community

Revision ID: 0024
Revises: 0023
Create Date: 2026-06-11

Refactor "Dữ liệu của tôi" (sources page) sang model batch-based:

  * Schema mới `me` — bounded context cho user-facing data tracking. Khác
    `auth` (identity) vì batch không phải identity attribute, khác `ts`
    (hypertable time-series) vì batch là metadata ngắn (per-upload row),
    không phải chuỗi đo dài hạn.

  * `me.upload_batches` = 1 row mỗi lần user "bắn data" vào hệ thống:
    upload CSV/JSON file, hay click "Tải dữ liệu mới nhất" cho 1 linked
    source. Filename + kind + uploaded_at đầy đủ để hiển thị mục "Lịch sử
    upload". points_count = aggregate cache; status thật suy ra từ trạng
    thái các row con (quarantine/training) qua batch_id FK.

  * batch_id trên ts.survey_quarantine + ts.survey_training: ON DELETE SET
    NULL để xoá batch giữ lại data đã admin duyệt vào training (parity với
    linked_source_id mig 0007). UI mục "Quản lý dữ liệu" hide row có
    batch_id NULL → legacy data (option (c) — không backfill).

  * Drop `auth.linked_sources.contribute_to_community` + partial index
    `ix_linked_sources_eligible`: cờ per-source bị thay bằng quyết định
    per-batch (user bấm "Đóng góp" trên 1 batch cụ thể). Community-mode
    query `list_training` chuyển sang LEFT JOIN (admin duyệt vào training
    = đã đủ gate, không cần thêm cờ source-level).
"""

from __future__ import annotations

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Schema me ───────────────────────────────────────────────────────────
    op.execute("CREATE SCHEMA IF NOT EXISTS me;")
    op.execute(
        "COMMENT ON SCHEMA me IS "
        "'User-facing data tracking — batch metadata cho mục Dữ liệu của tôi.';"
    )

    # ── me.upload_batches ───────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE me.upload_batches (
            id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id           uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
            kind              text NOT NULL,
            filename          text NOT NULL,
            linked_source_id  uuid REFERENCES auth.linked_sources(id) ON DELETE SET NULL,
            uploaded_at       timestamptz NOT NULL DEFAULT now(),
            points_count      integer NOT NULL DEFAULT 0,
            deleted_at        timestamptz,
            created_at        timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT chk_batch_kind CHECK (
                kind IN ('csv','json','sync_lpwanmapper','sync_chirpstack')
            ),
            CONSTRAINT chk_batch_points CHECK (points_count >= 0)
        );
        """
    )
    op.execute(
        "CREATE INDEX ix_upload_batches_user_uploaded "
        "ON me.upload_batches (user_id, uploaded_at DESC);"
    )
    op.execute(
        "CREATE INDEX ix_upload_batches_linked_source "
        "ON me.upload_batches (linked_source_id) "
        "WHERE linked_source_id IS NOT NULL;"
    )
    op.execute(
        "COMMENT ON TABLE me.upload_batches IS "
        "'Mỗi lần user upload CSV/JSON hoặc click Sync = 1 batch row. "
        "Filename + kind hiển thị trong mục Lịch sử upload; deleted_at = "
        "soft-delete (UI mục Quản lý dữ liệu hide, mục Lịch sử vẫn show với "
        "trạng thái Đã xoá).';"
    )
    op.execute(
        "COMMENT ON COLUMN me.upload_batches.kind IS "
        "'csv | json | sync_lpwanmapper | sync_chirpstack — quyết định nhãn "
        "Loại file trên UI.';"
    )
    op.execute(
        "COMMENT ON COLUMN me.upload_batches.points_count IS "
        "'Aggregate cache. Trạng thái thật (private/pending/public) suy từ "
        "join quarantine+training qua batch_id, không cache.';"
    )

    # ── batch_id FK trên hypertable ─────────────────────────────────────────
    # Hypertable ALTER ADD COLUMN hoạt động bình thường (precedent: mig 0017).
    # ON DELETE SET NULL: xoá batch không cascade xoá data đã admin duyệt.
    op.execute(
        "ALTER TABLE ts.survey_quarantine "
        "ADD COLUMN batch_id uuid REFERENCES me.upload_batches(id) ON DELETE SET NULL;"
    )
    op.execute(
        "CREATE INDEX ix_survey_quarantine_batch "
        "ON ts.survey_quarantine (batch_id) "
        "WHERE batch_id IS NOT NULL;"
    )
    op.execute(
        "ALTER TABLE ts.survey_training "
        "ADD COLUMN batch_id uuid REFERENCES me.upload_batches(id) ON DELETE SET NULL;"
    )
    op.execute(
        "CREATE INDEX ix_survey_training_batch "
        "ON ts.survey_training (batch_id) "
        "WHERE batch_id IS NOT NULL;"
    )

    # ── Drop linked_sources.contribute_to_community ─────────────────────────
    # Partial index phải drop TRƯỚC vì reference column.
    op.execute("DROP INDEX IF EXISTS auth.ix_linked_sources_eligible;")
    op.execute(
        "ALTER TABLE auth.linked_sources "
        "DROP COLUMN IF EXISTS contribute_to_community, "
        "DROP COLUMN IF EXISTS contributed_at;"
    )


def downgrade() -> None:
    # Restore contribute_to_community (default false → preserve privacy
    # opt-in semantics; rows mất state cũ vì column đã drop).
    op.execute(
        "ALTER TABLE auth.linked_sources "
        "ADD COLUMN contribute_to_community boolean NOT NULL DEFAULT false, "
        "ADD COLUMN contributed_at timestamptz;"
    )
    op.execute(
        """
        CREATE INDEX ix_linked_sources_eligible
        ON auth.linked_sources (source_type)
        WHERE status = 'active' AND contribute_to_community = true;
        """
    )

    op.execute("DROP INDEX IF EXISTS ts.ix_survey_training_batch;")
    op.execute("ALTER TABLE ts.survey_training DROP COLUMN IF EXISTS batch_id;")
    op.execute("DROP INDEX IF EXISTS ts.ix_survey_quarantine_batch;")
    op.execute("ALTER TABLE ts.survey_quarantine DROP COLUMN IF EXISTS batch_id;")

    op.execute("DROP TABLE IF EXISTS me.upload_batches;")
    op.execute("DROP SCHEMA IF EXISTS me;")
