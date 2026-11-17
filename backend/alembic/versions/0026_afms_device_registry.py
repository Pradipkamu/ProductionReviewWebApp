"""Create AFMS device registry linked to the existing PRW machine master.

Revision ID: 0026_afms_device_registry
Revises: 0025_chat_attachments_moderation
"""
from alembic import op
import sqlalchemy as sa

revision = "0026_afms_device_registry"
down_revision = "0025_chat_attachments_moderation"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("afms_devices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("machine_id", sa.Integer(), sa.ForeignKey("machines.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("device_uid", sa.String(100), nullable=False),
        sa.Column("device_name", sa.String(120), nullable=True),
        sa.Column("device_role", sa.String(40), nullable=False, server_default="MAIN_CONTROLLER"),
        sa.Column("hardware_model", sa.String(120), nullable=True),
        sa.Column("firmware_version", sa.String(80), nullable=True),
        sa.Column("protocol_version", sa.String(30), nullable=False, server_default="1.0"),
        sa.Column("credential_hash", sa.String(64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("registered_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("device_uid", name="uq_afms_devices_device_uid"),
    )
    op.create_index("ix_afms_devices_machine_id", "afms_devices", ["machine_id"])
    op.create_index("ix_afms_devices_device_uid", "afms_devices", ["device_uid"])
    op.create_index("ix_afms_devices_is_active", "afms_devices", ["is_active"])

def downgrade():
    op.drop_index("ix_afms_devices_is_active", table_name="afms_devices")
    op.drop_index("ix_afms_devices_device_uid", table_name="afms_devices")
    op.drop_index("ix_afms_devices_machine_id", table_name="afms_devices")
    op.drop_table("afms_devices")
