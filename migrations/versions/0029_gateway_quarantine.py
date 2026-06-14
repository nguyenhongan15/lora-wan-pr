"""geo.gateway_quarantine — admin-review gate cho gateway đóng góp

Revision ID: 0029
Revises: 0028
Create Date: 2026-06-14

Mirror logic ts.survey_quarantine → ts.survey_training cho gateways:

  * Sync layer (lpwanmapper/chirpstack) gateway MỚI → INSERT vào quarantine
    (review_status='pending_review'), KHÔNG đẩy thẳng geo.gateways.
  * Re-sync cùng (source_type, external_id) → UPDATE quarantine row (location,
    name, altitude_m có thể đổi nếu user move gateway / rename).
  * Admin approve → INSERT geo.gateways từ quarantine row + update
    review_status='approved'.
  * Admin reject → review_status='rejected' + review_note (giữ row làm audit).
  * Admin direct-create (tạo thẳng trong UI Admin) → bypass quarantine, INSERT
    thẳng geo.gateways.

Grandfather: 15 gateway hiện có trong geo.gateways KHÔNG migrate ngược về
quarantine. Sync re-run trên chính các EUI đó tiếp tục dùng path UPSERT cũ
(owner-scoped, sửa ở Bước 2 trong _upsert.py).

Unique key (source_type, external_id) — đảm bảo idempotent: sync nhiều lần
cùng gateway = update cùng row quarantine, không tạo duplicate.
"""

from __future__ import annotations

from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE geo.gateway_quarantine (
            id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            code                 text NOT NULL,
            name                 text NOT NULL,
            location             geography(Point, 4326) NOT NULL,
            altitude_m           double precision NOT NULL DEFAULT 0,
            frequency_mhz        double precision NOT NULL DEFAULT 923.0,
            contributor_user_id  uuid REFERENCES auth.users(id) ON DELETE SET NULL,
            linked_source_id     uuid REFERENCES auth.linked_sources(id) ON DELETE SET NULL,
            external_id          text NOT NULL,
            source_type          text NOT NULL,
            review_status        text NOT NULL DEFAULT 'pending_review',
            reviewed_by_user_id  uuid REFERENCES auth.users(id) ON DELETE SET NULL,
            reviewed_at          timestamptz,
            review_note          text,
            promoted_gateway_id  uuid REFERENCES geo.gateways(id) ON DELETE SET NULL,
            created_at           timestamptz NOT NULL DEFAULT now(),
            updated_at           timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT chk_gwq_freq_lora_band CHECK (
                frequency_mhz IN (433.0, 868.0, 915.0, 923.0)
            ),
            CONSTRAINT chk_gwq_review_status CHECK (
                review_status IN ('pending_review', 'approved', 'rejected')
            )
        );
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX ux_gateway_quarantine_external "
        "ON geo.gateway_quarantine (source_type, external_id);"
    )
    op.execute(
        "CREATE INDEX gateway_quarantine_location_gix "
        "ON geo.gateway_quarantine USING gist (location);"
    )
    op.execute(
        "CREATE INDEX ix_gateway_quarantine_pending "
        "ON geo.gateway_quarantine (created_at DESC) "
        "WHERE review_status = 'pending_review';"
    )
    op.execute(
        "CREATE INDEX ix_gateway_quarantine_contributor "
        "ON geo.gateway_quarantine (contributor_user_id) "
        "WHERE contributor_user_id IS NOT NULL;"
    )
    op.execute(
        """
        CREATE TRIGGER gateway_quarantine_set_updated_at
        BEFORE UPDATE ON geo.gateway_quarantine
        FOR EACH ROW EXECUTE FUNCTION geo.touch_updated_at();
        """
    )
    op.execute(
        "COMMENT ON TABLE geo.gateway_quarantine IS "
        "'Gateway pending admin review. Sync layer ghi vào đây; admin approve "
        "→ insert geo.gateways + flip review_status=approved.';"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS gateway_quarantine_set_updated_at "
        "ON geo.gateway_quarantine;"
    )
    op.execute("DROP TABLE IF EXISTS geo.gateway_quarantine;")
