"""Standardize sales price precision to two decimal places."""
from alembic import op
import sqlalchemy as sa

revision = "0017_sales_price_two_decimals"
down_revision = "0016_quality_salvage_approval"
branch_labels = None
depends_on = None


def upgrade():
    # SQLite requires batch table recreation for type changes; PostgreSQL
    # performs the native ALTER COLUMN and rounds existing values to paisa.
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("sales_price_history") as batch:
            batch.alter_column("price", existing_type=sa.Numeric(14, 4),
                               type_=sa.Numeric(14, 2), existing_nullable=False)
        with op.batch_alter_table("daily_mis") as batch:
            batch.alter_column("sales_price", existing_type=sa.Numeric(14, 4),
                               type_=sa.Numeric(14, 2), existing_nullable=False)
    else:
        op.alter_column(
            "sales_price_history", "price",
            existing_type=sa.Numeric(14, 4), type_=sa.Numeric(14, 2),
            existing_nullable=False,
        )
        op.alter_column(
            "daily_mis", "sales_price",
            existing_type=sa.Numeric(14, 4), type_=sa.Numeric(14, 2),
            existing_nullable=False,
        )


def downgrade():
    # Restore the wider column precision; values already rounded cannot be recovered.
    op.alter_column(
        "daily_mis", "sales_price",
        existing_type=sa.Numeric(14, 2), type_=sa.Numeric(14, 4),
        existing_nullable=False,
    )
    op.alter_column(
        "sales_price_history", "price",
        existing_type=sa.Numeric(14, 2), type_=sa.Numeric(14, 4),
        existing_nullable=False,
    )
