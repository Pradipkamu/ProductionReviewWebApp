from alembic import op
import sqlalchemy as sa

revision = "0015_daily_review_product_context"
down_revision = "0014_daily_review_mom"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("review_points", sa.Column("product_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_review_points_product_id_products",
        "review_points", "products", ["product_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_review_points_product_id", "review_points", ["product_id"])


def downgrade():
    op.drop_index("ix_review_points_product_id", table_name="review_points")
    op.drop_constraint("fk_review_points_product_id_products", "review_points", type_="foreignkey")
    op.drop_column("review_points", "product_id")
