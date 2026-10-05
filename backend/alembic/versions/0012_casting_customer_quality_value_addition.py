"""Add casting/customer quality and effective-dated product value addition."""
from alembic import op
import sqlalchemy as sa


revision = "0012_casting_customer_quality"
down_revision = "0011_page_access_rules"
branch_labels = None
depends_on = None


def stamps():
    return [
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    ]


def upgrade():
    with op.batch_alter_table("products") as batch:
        batch.add_column(sa.Column("value_addition_per_piece", sa.Numeric(14, 3), nullable=True))

    op.create_table(
        "product_value_addition_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("value_addition_per_piece", sa.Numeric(14, 3), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("changed_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        *stamps(),
        sa.UniqueConstraint("product_id", "effective_from", name="uq_product_value_addition_effective"),
    )
    op.create_index("ix_product_value_addition_history_product_id", "product_value_addition_history", ["product_id"])
    op.create_index("ix_product_value_addition_history_effective_from", "product_value_addition_history", ["effective_from"])
    op.create_index("ix_product_value_addition_product_effective", "product_value_addition_history", ["product_id", "effective_from"])

    op.create_table(
        "casting_defect_phenomena",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("name", sa.String(220), nullable=False),
        sa.Column("normalized_name", sa.String(220), nullable=False),
        sa.Column("phenomenon_group", sa.String(120), nullable=True),
        sa.Column("criticality", sa.String(40), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *stamps(),
    )
    for column in ("code", "name", "normalized_name", "phenomenon_group"):
        op.create_index(f"ix_casting_defect_phenomena_{column}", "casting_defect_phenomena", [column], unique=column in {"code", "normalized_name"})

    op.create_table(
        "casting_defect_import_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("file_name", sa.String(260), nullable=False),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("stats_json", sa.Text(), nullable=True),
        sa.Column("imported_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        *stamps(),
    )
    op.create_index("ix_casting_defect_import_batches_file_sha256", "casting_defect_import_batches", ["file_sha256"], unique=True)

    op.create_table(
        "casting_defect_daily",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("record_key", sa.String(500), nullable=False),
        sa.Column("defect_date", sa.Date(), nullable=False),
        sa.Column("shift", sa.String(40), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("plant", sa.String(120), nullable=True),
        sa.Column("vendor_id", sa.Integer(), sa.ForeignKey("vendors.id"), nullable=True),
        sa.Column("heat_batch_no", sa.String(120), nullable=True),
        sa.Column("phenomenon_id", sa.Integer(), sa.ForeignKey("casting_defect_phenomena.id"), nullable=False),
        sa.Column("inspected_qty", sa.Numeric(16, 3), nullable=False),
        sa.Column("defect_qty", sa.Numeric(16, 3), nullable=False),
        sa.Column("rework_qty", sa.Numeric(16, 3), nullable=False),
        sa.Column("scrap_qty", sa.Numeric(16, 3), nullable=False),
        sa.Column("ppm", sa.Numeric(18, 3), nullable=False),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("import_batch_id", sa.Integer(), sa.ForeignKey("casting_defect_import_batches.id"), nullable=True),
        sa.Column("entered_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        *stamps(),
    )
    for column in ("record_key", "defect_date", "shift", "product_id", "plant", "vendor_id", "heat_batch_no", "phenomenon_id", "import_batch_id"):
        op.create_index(f"ix_casting_defect_daily_{column}", "casting_defect_daily", [column], unique=column == "record_key")
    op.create_index("ix_casting_defect_date_product", "casting_defect_daily", ["defect_date", "product_id"])
    op.create_index("ix_casting_defect_date_phenomenon", "casting_defect_daily", ["defect_date", "phenomenon_id"])

    op.create_table(
        "customer_rejection_phenomena",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("name", sa.String(220), nullable=False),
        sa.Column("normalized_name", sa.String(220), nullable=False),
        sa.Column("phenomenon_group", sa.String(120), nullable=True),
        sa.Column("criticality", sa.String(40), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *stamps(),
    )
    for column in ("code", "name", "normalized_name", "phenomenon_group"):
        op.create_index(f"ix_customer_rejection_phenomena_{column}", "customer_rejection_phenomena", [column], unique=column in {"code", "normalized_name"})

    op.create_table(
        "customer_rejection_import_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("file_name", sa.String(260), nullable=False),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("stats_json", sa.Text(), nullable=True),
        sa.Column("imported_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        *stamps(),
    )
    op.create_index("ix_customer_rejection_import_batches_file_sha256", "customer_rejection_import_batches", ["file_sha256"], unique=True)

    op.create_table(
        "customer_rejection_daily",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("record_key", sa.String(500), nullable=False),
        sa.Column("rejection_date", sa.Date(), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("reference_no", sa.String(120), nullable=True),
        sa.Column("batch_no", sa.String(120), nullable=True),
        sa.Column("phenomenon_id", sa.Integer(), sa.ForeignKey("customer_rejection_phenomena.id"), nullable=False),
        sa.Column("dispatch_qty", sa.Numeric(16, 3), nullable=False),
        sa.Column("reject_qty", sa.Numeric(16, 3), nullable=False),
        sa.Column("ppm", sa.Numeric(18, 3), nullable=False),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("import_batch_id", sa.Integer(), sa.ForeignKey("customer_rejection_import_batches.id"), nullable=True),
        sa.Column("entered_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        *stamps(),
    )
    for column in ("record_key", "rejection_date", "customer_id", "product_id", "reference_no", "batch_no", "phenomenon_id", "import_batch_id"):
        op.create_index(f"ix_customer_rejection_daily_{column}", "customer_rejection_daily", [column], unique=column == "record_key")
    op.create_index("ix_customer_rejection_date_customer", "customer_rejection_daily", ["rejection_date", "customer_id"])
    op.create_index("ix_customer_rejection_date_product", "customer_rejection_daily", ["rejection_date", "product_id"])
    op.create_index("ix_customer_rejection_date_phenomenon", "customer_rejection_daily", ["rejection_date", "phenomenon_id"])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        preparer = bind.dialect.identifier_preparer
        for table in (
            "product_value_addition_history", "casting_defect_phenomena", "casting_defect_daily",
            "customer_rejection_phenomena", "customer_rejection_daily",
        ):
            op.execute(sa.text(
                f'CREATE TRIGGER {preparer.quote("revision_" + table)} '
                f'AFTER INSERT OR UPDATE OR DELETE ON {preparer.quote(table)} '
                'FOR EACH STATEMENT EXECUTE FUNCTION bump_business_data_revision()'
            ))


def downgrade():
    raise RuntimeError("Restore a verified backup; quality and value-addition history must not be discarded.")
