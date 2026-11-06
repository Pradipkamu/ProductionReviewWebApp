"""Add protected photo attachments to daily quality rejection records."""

from alembic import op
import sqlalchemy as sa

revision = "0022_quality_rejection_attachments"
down_revision = "0021_alert_policies"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "quality_rejection_attachments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("daily_rejection_id", sa.Integer(),
                  sa.ForeignKey("quality_rejection_daily.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_name", sa.String(260), nullable=False),
        sa.Column("stored_name", sa.String(260), nullable=False),
        sa.Column("relative_path", sa.String(500), nullable=False),
        sa.Column("mime_type", sa.String(160), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("caption", sa.String(500), nullable=True),
        sa.Column("uploaded_by_id", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("daily_rejection_id", "sha256", name="uq_quality_rejection_attachment_hash"),
    )
    op.create_index("ix_quality_rejection_attachments_daily_rejection_id",
                    "quality_rejection_attachments", ["daily_rejection_id"])
    op.create_index("ix_quality_rejection_attachments_sha256",
                    "quality_rejection_attachments", ["sha256"])
    op.create_index("ix_quality_rejection_attachment_daily_created",
                    "quality_rejection_attachments", ["daily_rejection_id", "created_at"])


def downgrade():
    op.drop_index("ix_quality_rejection_attachment_daily_created", table_name="quality_rejection_attachments")
    op.drop_index("ix_quality_rejection_attachments_sha256", table_name="quality_rejection_attachments")
    op.drop_index("ix_quality_rejection_attachments_daily_rejection_id", table_name="quality_rejection_attachments")
    op.drop_table("quality_rejection_attachments")
