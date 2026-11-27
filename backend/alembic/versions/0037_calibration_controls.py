"""Complete calibration controls, MSA records and approval evidence.

Revision ID: 0037_calibration_controls
Revises: 0036_calibration_mgmt
"""
from alembic import op
import sqlalchemy as sa

revision = "0037_calibration_controls"
down_revision = "0036_calibration_mgmt"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("calibration_instruments", sa.Column("owner_type", sa.String(20), nullable=False, server_default="INTERNAL"))
    op.add_column("calibration_instruments", sa.Column("control_plan_reference", sa.String(160)))
    op.add_column("calibration_instruments", sa.Column("special_characteristic", sa.String(160)))
    op.drop_constraint("ck_calibration_instrument_status", "calibration_instruments", type_="check")
    op.create_check_constraint(
        "ck_calibration_instrument_status", "calibration_instruments",
        "status IN ('PENDING','IN_CALIBRATION','PENDING_APPROVAL','CALIBRATED','OVERDUE','FAILED','QUARANTINED','RETIRED')"
    )
    op.create_check_constraint(
        "ck_calibration_instrument_owner_type", "calibration_instruments",
        "owner_type IN ('INTERNAL','CUSTOMER','SUPPLIER','EMPLOYEE')"
    )
    op.add_column("calibration_events", sa.Column("approval_reason", sa.Text()))
    op.add_column("calibration_events", sa.Column("approved_at", sa.DateTime()))
    op.add_column("calibration_events", sa.Column("laboratory_scope_reference", sa.String(200)))
    op.add_column("calibration_impact_assessments", sa.Column("shipped_to_customer", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("calibration_impact_assessments", sa.Column("customer_notified", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("calibration_impact_assessments", sa.Column("customer_notification_reference", sa.String(200)))
    op.create_table(
        "calibration_msa_studies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("study_type", sa.String(24), nullable=False),
        sa.Column("measurement_system", sa.String(160), nullable=False),
        sa.Column("characteristic", sa.String(160), nullable=False),
        sa.Column("control_plan_reference", sa.String(160)),
        sa.Column("study_date", sa.Date(), nullable=False),
        sa.Column("method_reference", sa.String(200)),
        sa.Column("acceptance_criteria", sa.Text(), nullable=False),
        sa.Column("result_summary", sa.Text(), nullable=False),
        sa.Column("result", sa.String(40), nullable=False),
        sa.Column("customer_approval_reference", sa.String(200)),
        sa.Column("instrument_ids", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("remarks", sa.Text()),
        sa.Column("created_by", sa.Integer()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("study_type IN ('GAGE_RR','BIAS','LINEARITY','STABILITY','OTHER')", name="ck_calibration_msa_type"),
        sa.CheckConstraint("result IN ('ACCEPTABLE','UNACCEPTABLE','CONDITIONAL','CUSTOMER_APPROVED_ALTERNATIVE')", name="ck_calibration_msa_result"),
    )
    op.create_index("ix_calibration_msa_studies_date", "calibration_msa_studies", ["study_date"])


def downgrade():
    op.drop_index("ix_calibration_msa_studies_date", table_name="calibration_msa_studies")
    op.drop_table("calibration_msa_studies")
    op.drop_column("calibration_impact_assessments", "customer_notification_reference")
    op.drop_column("calibration_impact_assessments", "customer_notified")
    op.drop_column("calibration_impact_assessments", "shipped_to_customer")
    op.drop_column("calibration_events", "laboratory_scope_reference")
    op.drop_column("calibration_events", "approved_at")
    op.drop_column("calibration_events", "approval_reason")
    op.drop_constraint("ck_calibration_instrument_owner_type", "calibration_instruments", type_="check")
    op.drop_column("calibration_instruments", "special_characteristic")
    op.drop_column("calibration_instruments", "control_plan_reference")
    op.drop_column("calibration_instruments", "owner_type")
    op.drop_constraint("ck_calibration_instrument_status", "calibration_instruments", type_="check")
    op.create_check_constraint(
        "ck_calibration_instrument_status", "calibration_instruments",
        "status IN ('PENDING','IN_CALIBRATION','CALIBRATED','OVERDUE','FAILED','QUARANTINED','RETIRED')"
    )
