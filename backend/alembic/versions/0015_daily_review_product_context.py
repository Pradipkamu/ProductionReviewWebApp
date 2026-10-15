from alembic import op
import sqlalchemy as sa

revision = "0015_mom_product_ctx"
down_revision = "0014_daily_review_mom"
branch_labels = None
depends_on = None


def upgrade():
    # Batch mode supports both PostgreSQL and SQLite migration tests.
    with op.batch_alter_table("review_points") as batch_op:
        batch_op.add_column(sa.Column("product_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_review_points_product_id_products",
            "products", ["product_id"], ["id"], ondelete="SET NULL",
        )
        batch_op.create_index("ix_review_points_product_id", ["product_id"])


def downgrade():
    with op.batch_alter_table("review_points") as batch_op:
        batch_op.drop_index("ix_review_points_product_id")
        batch_op.drop_constraint("fk_review_points_product_id_products", type_="foreignkey")
        batch_op.drop_column("product_id")
