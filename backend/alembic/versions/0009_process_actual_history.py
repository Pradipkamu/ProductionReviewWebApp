"""Add auditable process actual corrections."""
from alembic import op
import sqlalchemy as sa

revision = "0009_process_actual_history"
down_revision = "0008_machine_master_costing"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "process_actual_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("process_summary_id", sa.Integer(), nullable=False),
        sa.Column("summary_date", sa.Date(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("route_operation_id", sa.Integer(), nullable=False),
        sa.Column("changed_by_id", sa.Integer(), nullable=True),
        sa.Column("changed_at", sa.DateTime(), nullable=False),
        sa.Column("change_type", sa.String(length=30), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("old_actual_qty", sa.Numeric(16, 3), nullable=True),
        sa.Column("new_actual_qty", sa.Numeric(16, 3), nullable=False),
        sa.Column("old_good_qty", sa.Numeric(16, 3), nullable=True),
        sa.Column("new_good_qty", sa.Numeric(16, 3), nullable=False),
        sa.Column("old_reject_qty", sa.Numeric(16, 3), nullable=True),
        sa.Column("new_reject_qty", sa.Numeric(16, 3), nullable=False),
        sa.Column("old_source", sa.String(length=40), nullable=True),
        sa.Column("new_source", sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(["changed_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["process_summary_id"], ["process_daily_summary.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["route_operation_id"], ["route_operations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_process_actual_history_summary", "process_actual_history", ["process_summary_id"], unique=False)
    op.create_index("ix_process_actual_history_date", "process_actual_history", ["summary_date"], unique=False)
    op.create_index("ix_process_actual_history_product", "process_actual_history", ["product_id"], unique=False)
    op.create_index("ix_process_actual_history_route", "process_actual_history", ["route_operation_id"], unique=False)


def downgrade():
    op.drop_index("ix_process_actual_history_route", table_name="process_actual_history")
    op.drop_index("ix_process_actual_history_product", table_name="process_actual_history")
    op.drop_index("ix_process_actual_history_date", table_name="process_actual_history")
    op.drop_index("ix_process_actual_history_summary", table_name="process_actual_history")
    op.drop_table("process_actual_history")
