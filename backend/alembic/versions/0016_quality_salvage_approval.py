"""Add controlled approval workflow for daily rejection salvage."""
from alembic import op
import sqlalchemy as sa

revision = "0016_quality_salvage_approval"
down_revision = "0015_mom_product_ctx"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "quality_rejection_daily",
        sa.Column("approved_salvage_qty", sa.Numeric(16, 3), nullable=False, server_default="0"),
    )
    op.create_table(
        "quality_rejection_salvage_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("daily_rejection_id", sa.Integer(), sa.ForeignKey("quality_rejection_daily.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requested_qty", sa.Numeric(16, 3), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("requested_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("approved_before_qty", sa.Numeric(16, 3), nullable=True),
        sa.Column("approved_after_qty", sa.Numeric(16, 3), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_quality_rejection_salvage_requests_daily_rejection_id", "quality_rejection_salvage_requests", ["daily_rejection_id"])
    op.create_index("ix_quality_rejection_salvage_requests_status", "quality_rejection_salvage_requests", ["status"])
    op.create_index("ix_quality_salvage_daily_status", "quality_rejection_salvage_requests", ["daily_rejection_id", "status"])


def downgrade():
    raise RuntimeError("Salvage approvals are audit records; restore a verified backup rather than deleting approval history.")
