"""Add protected chat attachments and moderation reports.

Revision ID: 0025_chat_attachments_moderation
Revises: 0024_employee_chat
"""
from alembic import op
import sqlalchemy as sa

revision = "0025_chat_attachments_moderation"
down_revision = "0024_employee_chat"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "chat_attachments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("file_name", sa.String(180), nullable=False),
        sa.Column("stored_name", sa.String(180), nullable=False, unique=True),
        sa.Column("relative_path", sa.String(500), nullable=False),
        sa.Column("mime_type", sa.String(160), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("uploaded_by_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["message_id"], ["chat_messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_chat_attachments_message_id", "chat_attachments", ["message_id"])
    op.create_index("ix_chat_attachments_uploaded_by_id", "chat_attachments", ["uploaded_by_id"])
    op.create_table(
        "chat_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("reported_by_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="OPEN"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("resolved_by_id", sa.Integer(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["message_id"], ["chat_messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reported_by_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resolved_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("message_id", "reported_by_id", name="uq_chat_reporter_message"),
    )
    op.create_index("ix_chat_reports_message_id", "chat_reports", ["message_id"])
    op.create_index("ix_chat_reports_reported_by_id", "chat_reports", ["reported_by_id"])


def downgrade():
    op.drop_table("chat_reports")
    op.drop_table("chat_attachments")
