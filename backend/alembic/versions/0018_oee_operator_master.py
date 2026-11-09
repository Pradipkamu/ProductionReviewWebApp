"""Add shared operator master and optional OEE operator reference."""

from alembic import op
import sqlalchemy as sa

revision = "0018_oee_operator_master"
down_revision = "0017_sales_price_two_decimals"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "oee_operators",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("full_name", sa.String(length=160), nullable=False),
        sa.Column("normalized_name", sa.String(length=160), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("normalized_name", name="uq_oee_operators_normalized_name"),
    )
    op.create_index("ix_oee_operators_normalized_name", "oee_operators", ["normalized_name"], unique=False)
    with op.batch_alter_table("machine_shift_production") as batch:
        batch.add_column(sa.Column("operator_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_machine_shift_production_operator_id_oee_operators",
            "oee_operators", ["operator_id"], ["id"], ondelete="SET NULL",
        )
        batch.create_index("ix_machine_shift_production_operator_id", ["operator_id"])


def downgrade():
    with op.batch_alter_table("machine_shift_production") as batch:
        batch.drop_index("ix_machine_shift_production_operator_id")
        batch.drop_constraint("fk_machine_shift_production_operator_id_oee_operators", type_="foreignkey")
        batch.drop_column("operator_id")
    op.drop_index("ix_oee_operators_normalized_name", table_name="oee_operators")
    op.drop_table("oee_operators")
