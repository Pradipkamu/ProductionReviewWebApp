"""Persist AFMS MQTT telemetry with device-scoped event idempotency.

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
        sa.Column(
            "device_id",
            sa.Integer(),
            sa.ForeignKey("afms_devices.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("event_id", sa.String(length=180), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("event_timestamp", sa.DateTime(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "device_id", "event_id", name="uq_afms_telemetry_device_event"
        ),
    )
    op.create_index(
        "ix_afms_telemetry_device_received",
        "afms_telemetry_events",
        ["device_id", "received_at"],
    )
    op.create_index(
        "ix_afms_telemetry_type_received",
        "afms_telemetry_events",
        ["event_type", "received_at"],
    )


def downgrade():
    op.drop_index("ix_afms_telemetry_type_received", table_name="afms_telemetry_events")
    op.drop_index("ix_afms_telemetry_device_received", table_name="afms_telemetry_events")
    op.drop_table("afms_telemetry_events")
