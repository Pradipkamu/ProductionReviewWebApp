"""Add controlled gauge lifecycle states and QR identity.

Revision ID: 0041_calibration_gauge_lifecycle
Revises: 0040_calibration_location_issue
"""
from alembic import op
import sqlalchemy as sa
import uuid

revision = "0041_calibration_gauge_lifecycle"
down_revision = "0040_calibration_location_issue"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("ck_calibration_instrument_status", "calibration_instruments", type_="check")
    op.create_check_constraint(
        "ck_calibration_instrument_status", "calibration_instruments",
        "status IN ('PENDING','IN_CALIBRATION','CALIBRATED','OVERDUE','FAILED','QUARANTINED','RETIRED','PENDING_APPROVAL','ACTIVE','DUE','OUT_FOR_CALIBRATION','OOT')",
    )
    op.add_column("calibration_instruments", sa.Column("qr_token", sa.String(36), nullable=True, server_default=sa.text("gen_random_uuid()::text")))
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id FROM calibration_instruments WHERE qr_token IS NULL")).fetchall()
    for row in rows:
        connection.execute(sa.text("UPDATE calibration_instruments SET qr_token=:token WHERE id=:id"),
                           {"token": str(uuid.uuid4()), "id": row[0]})
    op.alter_column("calibration_instruments", "qr_token", nullable=False)
    op.create_unique_constraint("uq_calibration_instruments_qr_token", "calibration_instruments", ["qr_token"])
    op.create_index("ix_calibration_instruments_lifecycle", "calibration_instruments", ["status", "is_active"])


def downgrade():
    op.drop_index("ix_calibration_instruments_lifecycle", table_name="calibration_instruments")
    op.drop_constraint("uq_calibration_instruments_qr_token", "calibration_instruments", type_="unique")
    op.drop_column("calibration_instruments", "qr_token")
    op.drop_constraint("ck_calibration_instrument_status", "calibration_instruments", type_="check")
    op.create_check_constraint(
        "ck_calibration_instrument_status", "calibration_instruments",
        "status IN ('PENDING','IN_CALIBRATION','CALIBRATED','OVERDUE','FAILED','QUARANTINED','RETIRED')",
    )
