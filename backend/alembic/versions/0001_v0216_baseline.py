"""Frozen v0.2.16 baseline, adopts existing tables without rewriting rows."""
import importlib.util
import sys
from pathlib import Path
from sqlalchemy import inspect
from alembic import op

revision = '0001_v0216'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    root = Path(__file__).resolve().parents[1] / 'snapshots'
    spec = importlib.util.spec_from_file_location('pms_baseline', root / 'enums.py', submodule_search_locations=[str(root)])
    pkg = importlib.util.module_from_spec(spec)
    sys.modules['pms_baseline'] = pkg
    spec.loader.exec_module(pkg)
    spec = importlib.util.spec_from_file_location('pms_baseline.models', root / 'v0216.py')
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pms_baseline.models"] = mod
    spec.loader.exec_module(mod)
    bind = op.get_bind()
    # Only the two known, additive legacy compatibility changes are accepted.
    from app.migrations import ensure_compatibility_columns
    ensure_compatibility_columns(bind)
    for table in mod.Base.metadata.sorted_tables:
        table.create(bind=bind, checkfirst=True)
        columns = {c['name'] for c in inspect(bind).get_columns(table.name)}
        missing = set(table.columns.keys()) - columns
        if missing:
            raise RuntimeError(f'Unrecognized legacy schema: {table.name} missing {sorted(missing)}. Restore backup and review schema.')


def downgrade():
    raise RuntimeError('Baseline downgrade is disabled: restore a verified backup instead.')
