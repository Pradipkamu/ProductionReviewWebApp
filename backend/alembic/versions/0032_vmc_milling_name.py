"""Rename FTA operation CNC Milling to VMC Milling.

Preserves the operation code and primary key so existing FTA templates and
investigations remain associated with the same operation.
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
            SET name = 'VMC Milling'
            WHERE code = 'CNC_MILL'
              AND name = 'CNC Milling'
        """)
    )


def downgrade():
    bind = op.get_bind()
    bind.execute(
        sa.text("""
            UPDATE fta_operations
            SET name = 'CNC Milling'
            WHERE code = 'CNC_MILL'
              AND name = 'VMC Milling'
        """)
    )
