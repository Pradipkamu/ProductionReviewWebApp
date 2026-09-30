from contextlib import contextmanager

@contextmanager
def _connection(bind):
    if hasattr(bind, "connect"):
        with bind.begin() as conn:
            yield conn
    else:
        yield bind

from sqlalchemy import inspect, text


def ensure_compatibility_columns(engine) -> None:
    """Legacy compatibility additions used only during Alembic baseline adoption.

    Used only by the frozen Alembic baseline to adopt pre-v0.2.16 databases. These statements
    only add columns/indexes; they never delete or rewrite existing business data.
    """
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "products" in tables:
        cols = {c["name"] for c in inspector.get_columns("products")}
        stmts: list[str] = []
        if "plant" not in cols:
            stmts.append("ALTER TABLE products ADD COLUMN plant VARCHAR(120)")
        if "product_group" not in cols:
            stmts.append("ALTER TABLE products ADD COLUMN product_group VARCHAR(120)")
        with _connection(engine) as conn:
            for stmt in stmts:
                conn.execute(text(stmt))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_products_plant ON products (plant)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_products_product_group ON products (product_group)"))

    # v0.2.2 adds auditable/effective-dated price revisions. Keep existing rows
    # and mark legacy/imported rows as EXCEL so a manual revision can take over
    # without destroying the original source price.
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "sales_price_history" in tables:
        cols = {c["name"] for c in inspector.get_columns("sales_price_history")}
        stmts = []
        if "reason" not in cols:
            stmts.append("ALTER TABLE sales_price_history ADD COLUMN reason VARCHAR(250)")
        if "source" not in cols:
            stmts.append("ALTER TABLE sales_price_history ADD COLUMN source VARCHAR(30) DEFAULT 'EXCEL'")
        if "entered_by_id" not in cols:
            stmts.append("ALTER TABLE sales_price_history ADD COLUMN entered_by_id INTEGER")
        if "revision_reference" not in cols:
            stmts.append("ALTER TABLE sales_price_history ADD COLUMN revision_reference VARCHAR(160)")
        if "source_document" not in cols:
            stmts.append("ALTER TABLE sales_price_history ADD COLUMN source_document VARCHAR(260)")
        with _connection(engine) as conn:
            for stmt in stmts:
                conn.execute(text(stmt))
            conn.execute(text("UPDATE sales_price_history SET source='EXCEL' WHERE source IS NULL OR source=''"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_price_product_effective ON sales_price_history (product_id, effective_from)"))
