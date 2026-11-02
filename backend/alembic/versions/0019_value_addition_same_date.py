"""Allow multiple audited value-addition revisions on one effective date."""

from alembic import op

revision = "0019_value_addition_same_date"
down_revision = "0018_mom_owner_collaboration"
branch_labels = None
depends_on = None


def upgrade():
    # Batch mode makes the named-constraint removal work on SQLite as well as PostgreSQL.
    with op.batch_alter_table("product_value_addition_history") as batch_op:
        batch_op.drop_constraint(
            "uq_product_value_addition_effective",
            type_="unique",
        )


def downgrade():
    # A downgrade is only safe if no product has multiple revisions for one date.
    with op.batch_alter_table("product_value_addition_history") as batch_op:
        batch_op.create_unique_constraint(
            "uq_product_value_addition_effective",
            ["product_id", "effective_from"],
        )
