"""daily review MOM and simple actions

Revision ID: 0014_daily_review_mom
Revises: 0013_historical_ppm_production
Create Date: 2026-10-10
"""
from alembic import op
import sqlalchemy as sa

revision = "0014_daily_review_mom"
down_revision = "0013_historical_ppm_production"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("actions", sa.Column("action_type", sa.String(length=40), nullable=False, server_default="WHY_WHY"))
    op.add_column("actions", sa.Column("requires_whywhy", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_index("ix_actions_action_type", "actions", ["action_type"])
    op.create_table(
        "review_points",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("review_session_id", sa.Integer(), sa.ForeignKey("review_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=120), nullable=True),
        sa.Column("discussion_point", sa.Text(), nullable=False),
        sa.Column("action_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("action_id", sa.Integer(), sa.ForeignKey("actions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("review_session_id","sequence_no",name="uq_review_point_sequence"),
    )
    op.create_index("ix_review_points_review_session_id","review_points",["review_session_id"])
    op.create_index("ix_review_points_action_id","review_points",["action_id"])

def downgrade():
    op.drop_index("ix_review_points_action_id",table_name="review_points")
    op.drop_index("ix_review_points_review_session_id",table_name="review_points")
    op.drop_table("review_points")
    op.drop_index("ix_actions_action_type",table_name="actions")
    op.drop_column("actions","requires_whywhy")
    op.drop_column("actions","action_type")
