"""Laboratory provider, acceptance criteria and calibration certificate metadata.

Revision ID: 0038_calibration_labs_criteria
Revises: 0037_calibration_controls
"""
from alembic import op
import sqlalchemy as sa

revision = "0038_calibration_labs_criteria"
down_revision = "0037_calibration_controls"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "calibration_laboratory_providers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(180), nullable=False, unique=True),
        sa.Column("address", sa.Text()),
        sa.Column("contact_person", sa.String(160)),
        sa.Column("email", sa.String(180)),
        sa.Column("phone", sa.String(60)),
        sa.Column("accreditation_body", sa.String(160)),
        sa.Column("accreditation_number", sa.String(120)),
        sa.Column("accreditation_valid_to", sa.Date()),
        sa.Column("iso_iec_17025", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("scope_reference", sa.String(200)),
        sa.Column("scope_parameters", sa.Text()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("remarks", sa.Text()),
        sa.Column("created_by", sa.Integer()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "calibration_acceptance_criteria",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("equipment_type", sa.String(100), nullable=False),
        sa.Column("parameter", sa.String(160)),
        sa.Column("range_text", sa.String(200)),
        sa.Column("permissible_error", sa.String(200), nullable=False),
        sa.Column("max_uncertainty", sa.String(160)),
        sa.Column("tur_requirement", sa.String(160)),
        sa.Column("decision_rule", sa.String(32), nullable=False, server_default="SIMPLE_ACCEPTANCE"),
        sa.Column("source_type", sa.String(24), nullable=False, server_default="INTERNAL_QMS"),
        sa.Column("source_reference", sa.String(240)),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        sa.Column("approval_status", sa.String(16), nullable=False, server_default="DRAFT"),
        sa.Column("approved_by", sa.String(120)),
        sa.Column("remarks", sa.Text()),
        sa.Column("created_by", sa.Integer()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("decision_rule IN ('SIMPLE_ACCEPTANCE','GUARD_BAND','CUSTOMER_RULE')", name="ck_calibration_criteria_decision"),
        sa.CheckConstraint("source_type IN ('INTERNAL_QMS','CUSTOMER','DRAWING','OEM','STANDARD')", name="ck_calibration_criteria_source"),
        sa.CheckConstraint("approval_status IN ('DRAFT','APPROVED','OBSOLETE')", name="ck_calibration_criteria_approval"),
    )
    op.create_index("ix_calibration_criteria_type_status", "calibration_acceptance_criteria", ["equipment_type", "approval_status"])
    op.add_column("calibration_events", sa.Column("laboratory_provider_id", sa.Integer()))
    op.add_column("calibration_events", sa.Column("acceptance_criteria_id", sa.Integer()))
    op.add_column("calibration_events", sa.Column("certificate_file_path", sa.Text()))
    op.add_column("calibration_events", sa.Column("certificate_file_name", sa.String(180)))
    op.add_column("calibration_events", sa.Column("certificate_mime_type", sa.String(120)))
    op.add_column("calibration_events", sa.Column("certificate_size_bytes", sa.BigInteger()))
    op.add_column("calibration_events", sa.Column("certificate_sha256", sa.String(64)))
    op.create_foreign_key("fk_calibration_event_lab_provider", "calibration_events", "calibration_laboratory_providers", ["laboratory_provider_id"], ["id"])
    op.create_foreign_key("fk_calibration_event_acceptance_criteria", "calibration_events", "calibration_acceptance_criteria", ["acceptance_criteria_id"], ["id"])


def downgrade():
    op.drop_constraint("fk_calibration_event_acceptance_criteria", "calibration_events", type_="foreignkey")
    op.drop_constraint("fk_calibration_event_lab_provider", "calibration_events", type_="foreignkey")
    for name in ("certificate_sha256", "certificate_size_bytes", "certificate_mime_type", "certificate_file_name", "certificate_file_path", "acceptance_criteria_id", "laboratory_provider_id"):
        op.drop_column("calibration_events", name)
    op.drop_index("ix_calibration_criteria_type_status", table_name="calibration_acceptance_criteria")
    op.drop_table("calibration_acceptance_criteria")
    op.drop_table("calibration_laboratory_providers")
