"""Add historical Siddharth Machining + Silver Production PPM denominator."""
from alembic import op
import sqlalchemy as sa

revision = "0013_historical_ppm_production"
down_revision = "0012_casting_customer_quality"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "quality_historical_ppm_production",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("siddharth_machining_qty", sa.Numeric(16, 3), nullable=False, server_default="0"),
        sa.Column("silver_production_qty", sa.Numeric(16, 3), nullable=False, server_default="0"),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("month", "product_id", name="uq_quality_historical_ppm_month_product"),
    )
    op.create_index("ix_quality_historical_ppm_month", "quality_historical_ppm_production", ["month"])
    op.create_index("ix_quality_historical_ppm_product", "quality_historical_ppm_production", ["product_id"])

def downgrade():
    op.drop_index("ix_quality_historical_ppm_product", table_name="quality_historical_ppm_production")
    op.drop_index("ix_quality_historical_ppm_month", table_name="quality_historical_ppm_production")
    op.drop_table("quality_historical_ppm_production")
