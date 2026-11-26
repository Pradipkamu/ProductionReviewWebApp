"""Add controlled inspection characteristics and gauge-linked measurements.

Revision ID: 0042_inspection_measurements
Revises: 0041_calibration_gauge_lifecycle
"""
from alembic import op
import sqlalchemy as sa

revision = "0042_inspection_measurements"
down_revision = "0041_calibration_gauge_lifecycle"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "inspection_characteristics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("operation_id", sa.Integer(), sa.ForeignKey("operations.id", ondelete="RESTRICT")),
        sa.Column("characteristic_code", sa.String(80), nullable=False),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("nominal_value", sa.Numeric(16, 5), nullable=False),
        sa.Column("lower_tolerance", sa.Numeric(16, 5), nullable=False),
        sa.Column("upper_tolerance", sa.Numeric(16, 5), nullable=False),
        sa.Column("unit", sa.String(40), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("control_plan_reference", sa.String(120)),
        sa.Column("special_characteristic", sa.String(30)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("lower_tolerance <= nominal_value AND nominal_value <= upper_tolerance", name="ck_inspection_characteristic_tolerance"),
        sa.CheckConstraint("sample_size BETWEEN 1 AND 100", name="ck_inspection_characteristic_sample_size"),
        sa.UniqueConstraint("product_id", "operation_id", "characteristic_code", name="uq_inspection_characteristic_scope_code"),
    )
    op.create_index("ix_inspection_characteristics_product_active", "inspection_characteristics", ["product_id", "is_active"])
    op.create_table(
        "inspection_measurements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("inspection_date", sa.Date(), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("operation_id", sa.Integer(), sa.ForeignKey("operations.id", ondelete="RESTRICT")),
        sa.Column("characteristic_id", sa.Integer(), sa.ForeignKey("inspection_characteristics.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("calibration_instruments.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("lot_reference", sa.String(120)),
        sa.Column("machine_reference", sa.String(120)),
        sa.Column("shift", sa.String(40)),
        sa.Column("operator_name", sa.String(120)),
        sa.Column("gauge_snapshot_json", sa.Text(), nullable=False),
        sa.Column("characteristic_snapshot_json", sa.Text(), nullable=False),
        sa.Column("result", sa.String(12), nullable=False),
        sa.Column("remarks", sa.Text()),
        sa.Column("recorded_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("result IN ('PASS','FAIL')", name="ck_inspection_measurement_result"),
    )
    op.create_index("ix_inspection_measurements_date_product", "inspection_measurements", ["inspection_date", "product_id"])
    op.create_index("ix_inspection_measurements_instrument", "inspection_measurements", ["instrument_id", "inspection_date"])
    op.create_table(
        "inspection_measurement_values",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("measurement_id", sa.Integer(), sa.ForeignKey("inspection_measurements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sample_no", sa.Integer(), nullable=False),
        sa.Column("measured_value", sa.Numeric(16, 5), nullable=False),
        sa.Column("is_within_tolerance", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("measurement_id", "sample_no", name="uq_inspection_measurement_sample"),
    )


def downgrade():
    op.drop_table("inspection_measurement_values")
    op.drop_index("ix_inspection_measurements_instrument", table_name="inspection_measurements")
    op.drop_index("ix_inspection_measurements_date_product", table_name="inspection_measurements")
    op.drop_table("inspection_measurements")
    op.drop_index("ix_inspection_characteristics_product_active", table_name="inspection_characteristics")
    op.drop_table("inspection_characteristics")
