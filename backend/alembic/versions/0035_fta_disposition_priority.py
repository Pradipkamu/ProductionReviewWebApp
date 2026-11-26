"""Add not-applicable disposition and finding priority to FTA findings.

Revision ID: 0035_fta_disp_priority
Revises: 0034_fta_templates_v2
"""
from alembic import op
import sqlalchemy as sa

revision = "0035_fta_disp_priority"
down_revision = "0034_fta_templates_v2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "fta_findings",
        sa.Column("priority", sa.String(12), nullable=False, server_default="MEDIUM"),
    )
    op.create_check_constraint(
        "ck_fta_findings_priority",
        "fta_findings",
        "priority IN ('HIGH', 'MEDIUM', 'LOW')",
    )


def downgrade():
    op.drop_constraint("ck_fta_findings_priority", "fta_findings", type_="check")
    op.drop_column("fta_findings", "priority")
