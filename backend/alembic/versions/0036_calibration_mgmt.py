"""Add calibration instrument register, events and audit trail.

Revision ID: 0036_calibration_mgmt
Revises: 0035_fta_disp_priority
"""
from alembic import op
import sqlalchemy as sa

revision = "0036_calibration_mgmt"
down_revision = "0035_fta_disp_priority"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "calibration_instruments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instrument_code", sa.String(80), nullable=False, unique=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("equipment_type", sa.String(100), nullable=False),
        sa.Column("manufacturer", sa.String(120)),
        sa.Column("model", sa.String(120)),
        sa.Column("serial_number", sa.String(120)),
        sa.Column("range_text", sa.String(160)),
        sa.Column("resolution_text", sa.String(100)),
        sa.Column("accuracy_text", sa.String(100)),
        sa.Column("location", sa.String(160)),
        sa.Column("owner_department", sa.String(100)),
        sa.Column("calibration_interval_days", sa.Integer(), nullable=False, server_default="365"),
        sa.Column("last_calibration_date", sa.Date()),
        sa.Column("next_due_date", sa.Date()),
        sa.Column("status", sa.String(24), nullable=False, server_default="PENDING"),
        sa.Column("criticality", sa.String(20), nullable=False, server_default="NORMAL"),
        sa.Column("remarks", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Integer()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("calibration_interval_days > 0", name="ck_calibration_interval_positive"),
        sa.CheckConstraint("status IN ('PENDING','IN_CALIBRATION','CALIBRATED','OVERDUE','FAILED','QUARANTINED','RETIRED')", name="ck_calibration_instrument_status"),
        sa.CheckConstraint("criticality IN ('NORMAL','IMPORTANT','CRITICAL')", name="ck_calibration_instrument_criticality"),
    )
    op.create_index("ix_calibration_instruments_due", "calibration_instruments", ["next_due_date", "status"])
    op.create_table(
        "calibration_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("calibration_instruments.id"), nullable=False),
        sa.Column("event_type", sa.String(24), nullable=False),
        sa.Column("calibration_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date()),
        sa.Column("certificate_number", sa.String(120)),
        sa.Column("laboratory_name", sa.String(200)),
        sa.Column("laboratory_accreditation", sa.String(160)),
        sa.Column("traceability_reference", sa.String(200)),
        sa.Column("result", sa.String(24), nullable=False),
        sa.Column("as_found", sa.Text()),
        sa.Column("as_left", sa.Text()),
        sa.Column("uncertainty", sa.String(120)),
        sa.Column("certificate_uri", sa.Text()),
        sa.Column("remarks", sa.Text()),
        sa.Column("performed_by", sa.Integer()),
        sa.Column("approved_by", sa.Integer()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("event_type IN ('CALIBRATION','VERIFICATION','REPAIR','ADJUSTMENT')", name="ck_calibration_event_type"),
        sa.CheckConstraint("result IN ('PASS','FAIL','CONDITIONAL')", name="ck_calibration_event_result"),
    )
    op.create_index("ix_calibration_events_instrument_date", "calibration_events", ["instrument_id", "calibration_date"])
    op.create_table(
        "calibration_impact_assessments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("calibration_events.id"), nullable=False),
        sa.Column("period_from", sa.Date(), nullable=False),
        sa.Column("period_to", sa.Date(), nullable=False),
        sa.Column("affected_product_ids", sa.Text()),
        sa.Column("affected_lot_references", sa.Text()),
        sa.Column("affected_quantity", sa.Numeric(14,3), nullable=False, server_default="0"),
        sa.Column("assessment", sa.Text(), nullable=False),
        sa.Column("disposition", sa.String(32), nullable=False),
        sa.Column("action_id", sa.Integer()),
        sa.Column("assessed_by", sa.Integer(), nullable=False),
        sa.Column("assessed_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("period_to >= period_from", name="ck_calibration_impact_period"),
        sa.CheckConstraint("disposition IN ('REINSPECT','ACCEPT_JUSTIFIED','REJECT','NO_IMPACT','PENDING')", name="ck_calibration_impact_disposition"),
    )
    op.create_table(
        "calibration_audit_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("calibration_instruments.id"), nullable=False),
        sa.Column("event_id", sa.Integer()),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("before_json", sa.Text()),
        sa.Column("after_json", sa.Text()),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("changed_by", sa.Integer(), nullable=False),
        sa.Column("changed_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table("calibration_audit_log")
    op.drop_table("calibration_impact_assessments")
    op.drop_index("ix_calibration_events_instrument_date", table_name="calibration_events")
    op.drop_table("calibration_events")
    op.drop_index("ix_calibration_instruments_due", table_name="calibration_instruments")
    op.drop_table("calibration_instruments")
