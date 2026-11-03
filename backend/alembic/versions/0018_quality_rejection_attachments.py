"""Add reusable defect-photo attachment metadata for quality rejections."""
from alembic import op
import sqlalchemy as sa

revision = "0018_quality_rejection_attachments"
down_revision = "0017_sales_price_two_decimals"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "quality_rejection_attachments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("daily_rejection_id", sa.Integer(), sa.ForeignKey("quality_rejection_daily.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_name", sa.String(length=260), nullable=False),
        sa.Column("stored_name", sa.String(length=260), nullable=False),
        sa.Column("relative_path", sa.String(length=500), nullable=False),
        sa.Column("mime_type", sa.String(length=160), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("caption", sa.String(length=500), nullable=True),
        sa.Column("uploaded_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_quality_rejection_attachments_daily_rejection_id", "quality_rejection_attachments", ["daily_rejection_id"])
    op.create_index("ix_quality_rejection_attachments_sha256", "quality_rejection_attachments", ["sha256"])
    op.create_index("uq_quality_rejection_attachment_hash", "quality_rejection_attachments", ["daily_rejection_id", "sha256"], unique=True)


def downgrade():
    op.drop_index("uq_quality_rejection_attachment_hash", table_name="quality_rejection_attachments")
    op.drop_index("ix_quality_rejection_attachments_sha256", table_name="quality_rejection_attachments")
    op.drop_index("ix_quality_rejection_attachments_daily_rejection_id", table_name="quality_rejection_attachments")
    op.drop_table("quality_rejection_attachments")
