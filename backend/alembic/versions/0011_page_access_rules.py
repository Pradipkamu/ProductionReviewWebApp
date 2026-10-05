"""Add administrator-managed page visibility by role."""
from alembic import op
import sqlalchemy as sa


revision = "0011_page_access_rules"
down_revision = "0010_security_sessions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "page_access_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=40), nullable=False),
        sa.Column("page_key", sa.String(length=80), nullable=False),
        sa.Column("is_visible", sa.Boolean(), nullable=False),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("role", "page_key", name="uq_page_access_role_page"),
    )
    op.create_index("ix_page_access_rules_role", "page_access_rules", ["role"], unique=False)


def downgrade():
    op.drop_index("ix_page_access_rules_role", table_name="page_access_rules")
    op.drop_table("page_access_rules")
