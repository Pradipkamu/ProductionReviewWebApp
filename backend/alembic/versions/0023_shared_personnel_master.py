"""Create shared personnel master and link OEE shift records.

Revision ID: 0023_shared_personnel_master
Revises: 0022_rejection_photos
"""
from alembic import op
import sqlalchemy as sa

revision = "0023_shared_personnel_master"
down_revision = "0022_rejection_photos"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "personnel",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("last_name", sa.String(length=100), nullable=False),
        sa.Column("full_name", sa.String(length=201), nullable=False),
        sa.Column("normalized_name", sa.String(length=201), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_personnel_first_name", "personnel", ["first_name"])
    op.create_index("ix_personnel_last_name", "personnel", ["last_name"])
    op.create_index("ix_personnel_full_name", "personnel", ["full_name"])
    op.create_index("ix_personnel_normalized_name", "personnel", ["normalized_name"])
    op.create_index("ix_personnel_is_active", "personnel", ["is_active"])
    with op.batch_alter_table("machine_shift_production") as batch:
        batch.add_column(sa.Column("operator_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_machine_shift_production_operator_id_personnel",
            "personnel", ["operator_id"], ["id"], ondelete="SET NULL",
        )
        batch.create_index("ix_machine_shift_production_operator_id", ["operator_id"])


def downgrade():
    with op.batch_alter_table("machine_shift_production") as batch:
        batch.drop_index("ix_machine_shift_production_operator_id")
        batch.drop_constraint("fk_machine_shift_production_operator_id_personnel", type_="foreignkey")
        batch.drop_column("operator_id")
    op.drop_index("ix_personnel_is_active", table_name="personnel")
    op.drop_index("ix_personnel_normalized_name", table_name="personnel")
    op.drop_index("ix_personnel_full_name", table_name="personnel")
    op.drop_index("ix_personnel_last_name", table_name="personnel")
    op.drop_index("ix_personnel_first_name", table_name="personnel")
    op.drop_table("personnel")
