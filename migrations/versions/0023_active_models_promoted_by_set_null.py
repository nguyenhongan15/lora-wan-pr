"""ml.active_models.promoted_by → ON DELETE SET NULL

Revision ID: 0023
Revises: 0022
Create Date: 2026-06-10

Cho phep super admin xoa user da tung promote model. FK ban dau (mig 0011)
khong khai bao ON DELETE → mac dinh NO ACTION → block DELETE user voi
postgres FK violation.

SET NULL = active_models giu nguyen row + audit trail (promoted_at, version),
chi mat reference toi user (UI hien thi "-" cho promoted_by). Du cho purpose
'ai promote' khi user da xoa.
"""

from __future__ import annotations

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


_FK_NAME = "active_models_promoted_by_fkey"


def upgrade() -> None:
    op.execute(f"ALTER TABLE ml.active_models DROP CONSTRAINT IF EXISTS {_FK_NAME};")
    op.execute(
        f"ALTER TABLE ml.active_models "
        f"ADD CONSTRAINT {_FK_NAME} "
        f"FOREIGN KEY (promoted_by) REFERENCES auth.users(id) ON DELETE SET NULL;"
    )


def downgrade() -> None:
    op.execute(f"ALTER TABLE ml.active_models DROP CONSTRAINT IF EXISTS {_FK_NAME};")
    op.execute(
        f"ALTER TABLE ml.active_models "
        f"ADD CONSTRAINT {_FK_NAME} "
        f"FOREIGN KEY (promoted_by) REFERENCES auth.users(id);"
    )
