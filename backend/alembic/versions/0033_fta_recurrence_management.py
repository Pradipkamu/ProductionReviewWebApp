"""Add traceable recurrence records to machining FTA investigations.

Revision ID: 0033_fta_recurrence_management
Revises: 0032_vmc_milling_name
"""
from alembic import op
import sqlalchemy as sa

revision = "0033_fta_recurrence_management"
down_revision = "0032_vmc_milling_name"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "fta_recurrences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("original_investigation_id", sa.Integer(),
                  sa.ForeignKey("fta_investigations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("rejection_id", sa.Integer(),
                  sa.ForeignKey("quality_rejection_daily.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("classification", sa.String(24), nullable=False, server_default="PENDING_REVIEW"),
        sa.Column("same_root_cause", sa.Boolean(), nullable=True),
        sa.Column("recurrence_reason", sa.Text(), nullable=False),
        sa.Column("containment_action", sa.Text(), nullable=True),
        sa.Column("new_evidence", sa.Text(), nullable=True),
        sa.Column("previous_action_status", sa.String(40), nullable=True),
        sa.Column("previous_verification_result", sa.Text(), nullable=True),
        sa.Column("review_remarks", sa.Text(), nullable=True),
        sa.Column("reviewed_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("rejection_id", name="uq_fta_recurrences_rejection_id"),
        sa.CheckConstraint(
            "classification IN ('PENDING_REVIEW','SAME_ROOT_CAUSE','DIFFERENT_ROOT_CAUSE','UNRELATED')",
            name="ck_fta_recurrences_classification",
        ),
    )
    op.create_index("ix_fta_recurrences_original_investigation_id",
                    "fta_recurrences", ["original_investigation_id"])
    op.create_index("ix_fta_recurrences_created_at", "fta_recurrences", ["created_at"])
    op.add_column("fta_recurrences", sa.Column(
        "related_investigation_id", sa.Integer(),
        sa.ForeignKey("fta_investigations.id", ondelete="SET NULL"), nullable=True,
    ))


def downgrade():
    op.drop_column("fta_recurrences", "related_investigation_id")
    op.drop_index("ix_fta_recurrences_created_at", table_name="fta_recurrences")
    op.drop_index("ix_fta_recurrences_original_investigation_id", table_name="fta_recurrences")
    op.drop_table("fta_recurrences")
