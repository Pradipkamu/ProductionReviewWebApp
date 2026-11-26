"""Track additional causes discovered while implementing FTA actions.

Revision ID: 0030_fta_discovered_causes
Revises: 0029_machining_fta
"""
from alembic import op
import sqlalchemy as sa

revision = "0030_fta_discovered_causes"
down_revision = "0029_machining_fta"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "fta_discovered_causes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("investigation_id", sa.Integer(), sa.ForeignKey("fta_investigations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action_id", sa.Integer(), sa.ForeignKey("actions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cause_description", sa.Text(), nullable=False),
        sa.Column("evidence_reference", sa.Text(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="PROPOSED"),
        sa.Column("reported_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewed_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("review_remarks", sa.Text(), nullable=True),
        sa.Column("verification_method", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_fta_discovered_causes_investigation", "fta_discovered_causes", ["investigation_id"])
    op.create_index("ix_fta_discovered_causes_action", "fta_discovered_causes", ["action_id"])
    op.create_index("ix_fta_discovered_causes_status", "fta_discovered_causes", ["status"])


def downgrade():
    op.drop_index("ix_fta_discovered_causes_status", table_name="fta_discovered_causes")
    op.drop_index("ix_fta_discovered_causes_action", table_name="fta_discovered_causes")
    op.drop_index("ix_fta_discovered_causes_investigation", table_name="fta_discovered_causes")
    op.drop_table("fta_discovered_causes")
