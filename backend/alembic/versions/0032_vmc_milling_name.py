"""Rename production FTA CNC Milling to VMC Milling, including its templates.

Preserves operation IDs, template IDs/codes/versions, fault-tree JSON and
investigation snapshots. Intended for the production database only.
"""
from alembic import op
import sqlalchemy as sa

revision = "0032_vmc_milling_name"
down_revision = "0031_shared_fta_phenomena"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    # Do not risk violating the unique operation-code constraint.
    conflict = bind.execute(sa.text("""
        SELECT 1
        FROM fta_operations
        WHERE code = 'VMC_MILL'
    """)).first()
    source = bind.execute(sa.text("""
        SELECT 1
        FROM fta_operations
        WHERE code = 'CNC_MILL'
    """)).first()
    if conflict and source:
        raise RuntimeError(
            "Both CNC_MILL and VMC_MILL operations exist. "
            "Resolve the duplicate operation before applying this migration."
        )

    # Move template and investigation operation references with the master.
    # These columns are stored codes, not foreign keys to fta_operations.
    templates = bind.execute(sa.text("""
        SELECT id, name FROM fta_templates WHERE operation_code = 'CNC_MILL'
    """)).mappings().all()
    for template in templates:
        name = template["name"] or ""
        if name.startswith("CNC Milling"):
            name = "VMC Milling" + name[len("CNC Milling"):]
        bind.execute(sa.text("""
            UPDATE fta_templates
            SET operation_code='VMC_MILL', name=:name
            WHERE id=:id
        """), {"name": name, "id": template["id"]})
    bind.execute(sa.text("""
        UPDATE fta_investigations
        SET operation_code = 'VMC_MILL'
        WHERE operation_code = 'CNC_MILL'
    """))
    bind.execute(sa.text("""
        UPDATE fta_operations
        SET code = 'VMC_MILL',
            name = 'VMC Milling',
            updated_at = CURRENT_TIMESTAMP
        WHERE code = 'CNC_MILL'
    """))


def downgrade():
    bind = op.get_bind()

    conflict = bind.execute(sa.text("""
        SELECT 1
        FROM fta_operations
        WHERE code = 'CNC_MILL'
    """)).first()
    source = bind.execute(sa.text("""
        SELECT 1
        FROM fta_operations
        WHERE code = 'VMC_MILL'
    """)).first()
    if conflict and source:
        raise RuntimeError(
            "Both CNC_MILL and VMC_MILL operations exist. "
            "Resolve the duplicate operation before downgrading this migration."
        )

    templates = bind.execute(sa.text("""
        SELECT id, name FROM fta_templates WHERE operation_code = 'VMC_MILL'
    """)).mappings().all()
    for template in templates:
        name = template["name"] or ""
        if name.startswith("VMC Milling"):
            name = "CNC Milling" + name[len("VMC Milling"):]
        bind.execute(sa.text("""
            UPDATE fta_templates
            SET operation_code='CNC_MILL', name=:name
            WHERE id=:id
        """), {"name": name, "id": template["id"]})
    bind.execute(sa.text("""
        UPDATE fta_investigations
        SET operation_code = 'CNC_MILL'
        WHERE operation_code = 'VMC_MILL'
    """))
    bind.execute(sa.text("""
        UPDATE fta_operations
        SET code = 'CNC_MILL',
            name = 'CNC Milling',
            updated_at = now()
        WHERE code = 'VMC_MILL'
    """))
