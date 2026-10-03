"""Expand machine master for PM, utilities, fractional manpower and costing."""
from alembic import op
import sqlalchemy as sa

revision = '0008_machine_master_costing'
down_revision = '0007_machine_capacity_planning'
branch_labels = None
depends_on = None


def upgrade():
    columns = [
        sa.Column('plant', sa.String(120), nullable=True),
        sa.Column('cost_center', sa.String(80), nullable=True),
        sa.Column('manufacturer', sa.String(120), nullable=True),
        sa.Column('model_number', sa.String(120), nullable=True),
        sa.Column('serial_number', sa.String(120), nullable=True),
        sa.Column('commissioned_on', sa.Date(), nullable=True),
        sa.Column('pm_done_date', sa.Date(), nullable=True),
        sa.Column('pm_frequency_days', sa.Integer(), nullable=True),
        sa.Column('default_manpower_required', sa.Numeric(8, 3), nullable=True),
        sa.Column('rated_power_kw', sa.Numeric(12, 3), nullable=True),
        sa.Column('power_load_factor', sa.Numeric(8, 5), nullable=True),
        sa.Column('air_consumption_cfm', sa.Numeric(12, 3), nullable=True),
        sa.Column('labor_rate_per_operator_hour', sa.Numeric(14, 3), nullable=True),
        sa.Column('electricity_rate_per_kwh', sa.Numeric(14, 3), nullable=True),
        sa.Column('compressed_air_rate_per_1000_cuft', sa.Numeric(14, 3), nullable=True),
        sa.Column('maintenance_cost_per_hour', sa.Numeric(14, 3), nullable=True),
        sa.Column('consumables_cost_per_hour', sa.Numeric(14, 3), nullable=True),
        sa.Column('depreciation_cost_per_hour', sa.Numeric(14, 3), nullable=True),
        sa.Column('other_overhead_cost_per_hour', sa.Numeric(14, 3), nullable=True),
        sa.Column('remarks', sa.String(500), nullable=True),
    ]
    with op.batch_alter_table('machines') as batch:
        for column in columns:
            batch.add_column(column)
        batch.create_index('ix_machines_plant', ['plant'])
    with op.batch_alter_table('machine_monthly_allocations') as batch:
        batch.add_column(sa.Column('estimated_hourly_cost_snapshot', sa.Numeric(16, 3), nullable=True))
        batch.add_column(sa.Column('estimated_cost_per_piece_snapshot', sa.Numeric(16, 6), nullable=True))
    op.create_table('machine_master_history',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('machine_id', sa.Integer(), sa.ForeignKey('machines.id'), nullable=False),
        sa.Column('change_type', sa.String(20), nullable=False),
        sa.Column('snapshot_json', sa.Text(), nullable=False),
        sa.Column('reason', sa.String(500), nullable=False),
        sa.Column('changed_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_machine_master_history_machine_id', 'machine_master_history', ['machine_id'])
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        op.execute(sa.text('CREATE TRIGGER revision_machine_master_history AFTER INSERT OR UPDATE OR DELETE ON machine_master_history FOR EACH STATEMENT EXECUTE FUNCTION bump_business_data_revision()'))


def downgrade():
    raise RuntimeError('Restore a verified backup; machine PM and costing history must not be discarded.')
