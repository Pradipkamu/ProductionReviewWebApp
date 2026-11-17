"""Persist AFMS telemetry with device-scoped idempotency.

Revision ID: 0027_afms_telemetry_events
Revises: 0026_afms_device_registry
"""
from alembic import op
import sqlalchemy as sa

revision = "0027_afms_telemetry_events"
down_revision = "0026_afms_device_registry"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "afms_telemetry_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("device_id", sa.Integer(), sa.ForeignKey("afms_devices.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("event_id", sa.String(128), nullable=False),
        sa.Column("event_type", sa.String(48), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("processing_status", sa.String(32), nullable=False, server_default="RECEIVED"),
        sa.Column("processing_error", sa.String(500), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.UniqueConstraint("device_id", "event_id", name="uq_afms_telemetry_device_event"),
    )
    op.create_index("ix_afms_telemetry_events_device_id", "afms_telemetry_events", ["device_id"])
    op.create_index("ix_afms_telemetry_events_event_type", "afms_telemetry_events", ["event_type"])
    op.create_index("ix_afms_telemetry_events_occurred_at", "afms_telemetry_events", ["occurred_at"])
    op.create_index("ix_afms_telemetry_events_received_at", "afms_telemetry_events", ["received_at"])
    op.create_index("ix_afms_telemetry_events_processing_status", "afms_telemetry_events", ["processing_status"])
    op.create_index("ix_afms_telemetry_device_received", "afms_telemetry_events", ["device_id", "received_at"])


def downgrade():
    op.drop_index("ix_afms_telemetry_device_received", table_name="afms_telemetry_events")
    op.drop_index("ix_afms_telemetry_events_processing_status", table_name="afms_telemetry_events")
    op.drop_index("ix_afms_telemetry_events_received_at", table_name="afms_telemetry_events")
    op.drop_index("ix_afms_telemetry_events_occurred_at", table_name="afms_telemetry_events")
    op.drop_index("ix_afms_telemetry_events_event_type", table_name="afms_telemetry_events")
    op.drop_index("ix_afms_telemetry_events_device_id", table_name="afms_telemetry_events")
    op.drop_table("afms_telemetry_events")
