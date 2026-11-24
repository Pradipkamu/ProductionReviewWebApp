"""Add controlled gauge locations and issue/return history.

Revision ID: 0040_calibration_location_issue
Revises: 0039_calibration_instrument_scope
"""
from alembic import op
import sqlalchemy as sa

revision = "0040_calibration_location_issue"
down_revision = "0039_calibration_instrument_scope"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "calibration_locations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("location_code", sa.String(40), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("plant_name", sa.String(120), nullable=False),
        sa.Column("department", sa.String(100), nullable=False),
        sa.Column("area", sa.String(100)),
        sa.Column("description", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Integer()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_calibration_locations_plant_department", "calibration_locations", ["plant_name", "department"])
    op.add_column("calibration_instruments", sa.Column("current_location_id", sa.Integer(),
                  sa.ForeignKey("calibration_locations.id", ondelete="RESTRICT")))
    op.add_column("calibration_instruments", sa.Column("custodian_name", sa.String(120)))
    op.create_table(
        "calibration_location_transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("calibration_instruments.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("from_location_id", sa.Integer(), sa.ForeignKey("calibration_locations.id", ondelete="RESTRICT")),
        sa.Column("to_location_id", sa.Integer(), sa.ForeignKey("calibration_locations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("transaction_type", sa.String(20), nullable=False),
        sa.Column("custodian_name", sa.String(120)),
        sa.Column("issued_to", sa.String(120)),
        sa.Column("purpose", sa.String(240)),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("transaction_date", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("recorded_by", sa.Integer(), nullable=False),
        sa.CheckConstraint("transaction_type IN ('ISSUE','TRANSFER','RETURN')", name="ck_calibration_location_txn_type"),
    )
    op.create_index("ix_calibration_location_txn_instrument_date", "calibration_location_transactions", ["instrument_id", "transaction_date"])


def downgrade():
    op.drop_index("ix_calibration_location_txn_instrument_date", table_name="calibration_location_transactions")
    op.drop_table("calibration_location_transactions")
    op.drop_column("calibration_instruments", "custodian_name")
    op.drop_column("calibration_instruments", "current_location_id")
    op.drop_index("ix_calibration_locations_plant_department", table_name="calibration_locations")
    op.drop_table("calibration_locations")
