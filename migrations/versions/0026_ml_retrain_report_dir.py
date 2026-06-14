"""audit.ml_retrain_jobs — them cot report_dir.

Revision ID: 0026
Revises: 0025
Create Date: 2026-06-13

Sau khi Celery retrain_ml_model train xong, render bao cao danh gia (plots +
HTML + PDF) vao thu muc `reports/retrain-{job_id}/`. Cot nay luu duong dan
folder de endpoint /admin/ml/retrain/{id}/report tra HTML va serve assets.
"""

from __future__ import annotations

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE audit.ml_retrain_jobs ADD COLUMN report_dir text;"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE audit.ml_retrain_jobs DROP COLUMN IF EXISTS report_dir;")
