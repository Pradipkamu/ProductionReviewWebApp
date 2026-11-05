"""Add indexes for historical quality PPM production records."""

from alembic import op

revision = "0020_quality_ppm_indexes"
down_revision = "0019_value_addition_same_date"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_quality_historical_ppm_month "
        "ON quality_historical_ppm_production (month)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_quality_historical_ppm_product "
        "ON quality_historical_ppm_production (product_id)"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_quality_historical_ppm_month")
    op.execute("DROP INDEX IF EXISTS ix_quality_historical_ppm_product")
