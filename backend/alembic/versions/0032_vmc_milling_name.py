"""Rename the production FTA milling operation to VMC Milling.

Preserves the operation primary key so existing FTA templates and
investigations remain associated with the same operation. This migration is
intended for the production database only; do not apply it to the test database.
"""
from alembic import op
import sqlalchemy as sa

revision = "0032_vmc_milling_name"
down_revision = "0031_shared_fta_phenomena"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    bind.execute(
        sa.text("""
            UPDATE fta_operations
            SET code = 'VMC_MILL',
                name = 'VMC Milling'
            WHERE code = 'CNC_MILL'
              AND name = 'CNC Milling'
        """)
    )


def downgrade():
    bind = op.get_bind()
    bind.execute(
        sa.text("""
            UPDATE fta_operations
            SET code = 'CNC_MILL',
                name = 'CNC Milling'
            WHERE code = 'VMC_MILL'
              AND name = 'VMC Milling'
        """)
    )
