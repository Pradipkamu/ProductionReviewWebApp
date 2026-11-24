"""Add plant, part, operation and machine scope mappings for calibration instruments.

Revision ID: 0039_calibration_instrument_scope
Revises: 0038_calibration_labs_criteria
"""
from alembic import op
import sqlalchemy as sa

revision = "0039_calibration_instrument_scope"
down_revision = "0038_calibration_labs_criteria"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("calibration_instruments", sa.Column("home_plant", sa.String(120)))
    op.create_table(
        "calibration_instrument_plants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("calibration_instruments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plant_name", sa.String(120), nullable=False),
        sa.Column("is_home", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.Integer()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("instrument_id", "plant_name", name="uq_calibration_instrument_plant"),
    )
    op.create_table(
        "calibration_instrument_products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("calibration_instruments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_by", sa.Integer()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("instrument_id", "product_id", name="uq_calibration_instrument_product"),
    )
    op.create_table(
        "calibration_instrument_operations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("calibration_instruments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("route_operation_id", sa.Integer(), sa.ForeignKey("route_operations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_by", sa.Integer()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("instrument_id", "route_operation_id", name="uq_calibration_instrument_route_operation"),
    )
    op.create_table(
        "calibration_instrument_machines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("calibration_instruments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("machine_id", sa.Integer(), sa.ForeignKey("machines.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_by", sa.Integer()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("instrument_id", "machine_id", name="uq_calibration_instrument_machine"),
    )
    for table, col in (
        ("calibration_instrument_plants", "instrument_id"),
        ("calibration_instrument_products", "instrument_id"),
        ("calibration_instrument_operations", "instrument_id"),
        ("calibration_instrument_machines", "instrument_id"),
    ):
        op.create_index("ix_" + table + "_instrument", table, [col])
    op.execute("""
      INSERT INTO calibration_instrument_plants (instrument_id, plant_name, is_home)
      SELECT id, home_plant, true FROM calibration_instruments
      WHERE home_plant IS NOT NULL AND trim(home_plant) <> ''
    """)


def downgrade():
    for table in ("calibration_instrument_machines", "calibration_instrument_operations",
                  "calibration_instrument_products", "calibration_instrument_plants"):
        op.drop_index("ix_" + table + "_instrument", table_name=table)
        op.drop_table(table)
    op.drop_column("calibration_instruments", "home_plant")
