"""Index report filters and track business writes for import previews."""
from alembic import op
import sqlalchemy as sa

revision = '0006_report_performance'
down_revision = '0005_shop_capture'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index('ix_quality_daily_date_phenomenon', 'quality_rejection_daily', ['rejection_date', 'phenomenon_id'])
    op.create_index('ix_quality_history_month_product_phenomenon', 'quality_rejection_monthly_history', ['month', 'product_id', 'phenomenon_id'])
    op.create_index('ix_machine_shift_date_machine_product', 'machine_shift_production', ['production_date', 'machine_id', 'product_id'])
    op.create_index('ix_machine_loss_date_machine_product', 'machine_loss_events', ['loss_date', 'machine_id', 'product_id'])
    op.create_index('ix_vendor_product_expected_return', 'vendor_movements', ['product_id', 'expected_return_date'])
    op.create_table('business_data_revision',
                    sa.Column('id', sa.Integer(), primary_key=True),
                    sa.Column('revision', sa.BigInteger(), nullable=False))
    op.execute(sa.text('INSERT INTO business_data_revision (id, revision) VALUES (1, 0)'))

    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return
    op.execute(sa.text('''
        CREATE FUNCTION bump_business_data_revision() RETURNS trigger AS $$
        BEGIN
            UPDATE business_data_revision SET revision = revision + 1 WHERE id = 1;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql
    '''))
    excluded = {'business_data_revision', 'alembic_version', 'governance_audit',
                'action_reminders', 'historical_correction_grants', 'import_batches',
                'quality_rejection_import_batches'}
    preparer = bind.dialect.identifier_preparer
    for table in sa.inspect(bind).get_table_names():
        if table in excluded:
            continue
        quoted = preparer.quote(table)
        op.execute(sa.text(
            f'CREATE TRIGGER {preparer.quote("revision_" + table)} '
            f'AFTER INSERT OR UPDATE OR DELETE ON {quoted} '
            'FOR EACH STATEMENT EXECUTE FUNCTION bump_business_data_revision()'
        ))


def downgrade():
    raise RuntimeError('Restore a verified backup; report migration should not discard business data.')
