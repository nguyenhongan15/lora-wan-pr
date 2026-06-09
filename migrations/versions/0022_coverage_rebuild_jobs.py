"""audit.coverage_rebuild_jobs + geo.gateways.last_rebuild_at

Revision ID: 0022
Revises: 0021
Create Date: 2026-06-09

Bo sung 2 thanh phan cho tinh nang Admin "Rebuild ban do uoc luong":

1. audit.coverage_rebuild_jobs: bang track moi lan admin trigger rebuild map.
   - status: queued / running / succeeded / failed
   - per_gw_log JSONB: chi tiet ket qua tung gateway (rebuilt/skipped/error)
   - celery_task_id: link voi Celery worker

2. geo.gateways.last_rebuild_at: timestamptz, NULL = chua rebuild lan nao.
   Logic incremental: so MAX(uplink_at) tu ts.survey_training voi cot nay;
   neu MAX(uplink_at) > last_rebuild_at → gw co goi tin moi → rebuild;
   nguoc lai → skip.
"""

from __future__ import annotations

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE audit.coverage_rebuild_jobs (
            id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            status           text NOT NULL DEFAULT 'queued',
            triggered_by     uuid REFERENCES auth.users(id) ON DELETE SET NULL,
            triggered_at     timestamptz NOT NULL DEFAULT now(),
            started_at       timestamptz,
            finished_at      timestamptz,
            gateways_total   int,
            gateways_rebuilt int NOT NULL DEFAULT 0,
            gateways_skipped int NOT NULL DEFAULT 0,
            per_gw_log       jsonb NOT NULL DEFAULT '{}'::jsonb,
            error_text       text,
            celery_task_id   text,
            CONSTRAINT chk_rebuild_status
                CHECK (status IN ('queued','running','succeeded','failed'))
        );
        """
    )
    op.execute(
        "CREATE INDEX ix_rebuild_jobs_triggered_at "
        "ON audit.coverage_rebuild_jobs (triggered_at DESC);"
    )
    op.execute(
        "COMMENT ON TABLE audit.coverage_rebuild_jobs IS "
        "'Track moi lan admin trigger rebuild ban do uoc luong (RSSI heatmap). "
        "per_gw_log JSONB: {gw_code: {status, elapsed_s, n_finite, error}}.';"
    )
    op.execute(
        "COMMENT ON COLUMN audit.coverage_rebuild_jobs.celery_task_id IS "
        "'Celery task UUID — link voi Redis result backend de poll progress.';"
    )

    op.execute(
        "ALTER TABLE geo.gateways "
        "ADD COLUMN last_rebuild_at timestamptz NULL;"
    )
    op.execute(
        "COMMENT ON COLUMN geo.gateways.last_rebuild_at IS "
        "'Timestamp lan cuoi per_gw geojson cua gw nay duoc rebuild. NULL = "
        "chua rebuild lan nao. Logic incremental: rebuild khi "
        "MAX(uplink_at) tu ts.survey_training > last_rebuild_at.';"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE geo.gateways DROP COLUMN IF EXISTS last_rebuild_at;"
    )
    op.execute(
        "DROP INDEX IF EXISTS audit.ix_rebuild_jobs_triggered_at;"
    )
    op.execute(
        "DROP TABLE IF EXISTS audit.coverage_rebuild_jobs;"
    )
