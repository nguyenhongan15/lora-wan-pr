"""audit.ml_retrain_jobs — track admin ML retrain runs.

Revision ID: 0025
Revises: 0024
Create Date: 2026-06-11

Mirror schema cua audit.coverage_rebuild_jobs (mig 0022) — cung pattern:
  - status: queued / running / succeeded / failed
  - error_text + celery_task_id
  - artifact_path: duong dan joblib output (de admin trace artifact nao dang
    duoc ml-service serve)
  - metrics JSONB: RMSE/MAE/feature_count sau khi train xong
  - rows_trained: so row tu ts.survey_training dung de train

Khong co per_gw_log (khong ap dung cho ML — train chay 1 luot tren toan bo
data, khong split per-gateway).
"""

from __future__ import annotations

from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE audit.ml_retrain_jobs (
            id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            status           text NOT NULL DEFAULT 'queued',
            triggered_by     uuid REFERENCES auth.users(id) ON DELETE SET NULL,
            triggered_at     timestamptz NOT NULL DEFAULT now(),
            started_at       timestamptz,
            finished_at      timestamptz,
            rows_trained     int,
            artifact_path    text,
            metrics          jsonb NOT NULL DEFAULT '{}'::jsonb,
            error_text       text,
            celery_task_id   text,
            CONSTRAINT chk_ml_retrain_status
                CHECK (status IN ('queued','running','succeeded','failed'))
        );
        """
    )
    op.execute(
        "CREATE INDEX ix_ml_retrain_jobs_triggered_at "
        "ON audit.ml_retrain_jobs (triggered_at DESC);"
    )
    op.execute(
        "COMMENT ON TABLE audit.ml_retrain_jobs IS "
        "'Track moi lan admin trigger retrain ML model. metrics JSONB chua "
        "RMSE/MAE/feature_count cua run nay; artifact_path = duong dan joblib "
        "ml-service load. Mirror schema audit.coverage_rebuild_jobs.';"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS audit.ix_ml_retrain_jobs_triggered_at;")
    op.execute("DROP TABLE IF EXISTS audit.ml_retrain_jobs;")
