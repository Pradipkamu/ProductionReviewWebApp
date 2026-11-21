"""Register Android devices for chat push notifications.

Revision ID: 0028_chat_device_tokens
Revises: 0027_afms_telemetry_events
"""
from alembic import op
import sqlalchemy as sa

revision = "0028_chat_device_tokens"
down_revision = "0027_afms_telemetry_events"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "chat_device_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token", sa.String(length=512), nullable=False),
        sa.Column("platform", sa.String(length=20), nullable=False, server_default="ANDROID"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("token", name="uq_chat_device_tokens_token"),
    )
    op.create_index("ix_chat_device_tokens_token", "chat_device_tokens", ["token"], unique=True)\n    op.create_index("ix_chat_device_tokens_user_id", "chat_device_tokens", ["user_id"])
    op.create_index("ix_chat_device_tokens_is_active", "chat_device_tokens", ["is_active"])


def downgrade():
    op.drop_index("ix_chat_device_tokens_is_active", table_name="chat_device_tokens")
    op.drop_index("ix_chat_device_tokens_user_id", table_name="chat_device_tokens")
    op.drop_table("chat_device_tokens")
