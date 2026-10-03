"""Effective-dated machine capacity, manpower and monthly part allocation."""
from alembic import op
import sqlalchemy as sa

revision = '0007_machine_capacity_planning'
down_revision = '0006_report_performance'
branch_labels = None
depends_on = None


def stamps():
    return [
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    ]


def upgrade():
    with op.batch_alter_table('operation_machine_map') as batch:
        batch.add_column(sa.Column('reason', sa.String(250), nullable=True))
        batch.add_column(sa.Column('entered_by_id', sa.Integer(), nullable=True))
        batch.create_foreign_key('fk_operation_machine_map_entered_by', 'users', ['entered_by_id'], ['id'])
    with op.batch_alter_table('standard_cycle_times') as batch:
        batch.add_column(sa.Column('reason', sa.String(250), nullable=True))
        batch.add_column(sa.Column('entered_by_id', sa.Integer(), nullable=True))
        batch.create_foreign_key('fk_standard_cycle_times_entered_by', 'users', ['entered_by_id'], ['id'])

    op.create_table('operator_requirement_history',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('route_operation_id', sa.Integer(), sa.ForeignKey('route_operations.id'), nullable=False),
        sa.Column('machine_id', sa.Integer(), sa.ForeignKey('machines.id'), nullable=True),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('effective_to', sa.Date(), nullable=True),
        sa.Column('operators_per_machine', sa.Numeric(8, 3), nullable=False),
        sa.Column('reason', sa.String(250), nullable=False),
        sa.Column('entered_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        *stamps())
    op.create_index('ix_operator_requirement_history_route_operation_id', 'operator_requirement_history', ['route_operation_id'])
    op.create_index('ix_operator_requirement_history_machine_id', 'operator_requirement_history', ['machine_id'])
    op.create_index('ix_operator_requirement_history_effective_from', 'operator_requirement_history', ['effective_from'])

    op.create_table('machine_capacity_settings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('machine_id', sa.Integer(), sa.ForeignKey('machines.id'), nullable=False),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('effective_to', sa.Date(), nullable=True),
        sa.Column('shifts_per_day', sa.Integer(), nullable=False),
        sa.Column('shift_minutes', sa.Numeric(8, 2), nullable=False),
        sa.Column('planned_break_minutes', sa.Numeric(8, 2), nullable=False),
        sa.Column('planning_efficiency', sa.Numeric(8, 5), nullable=False),
        sa.Column('reason', sa.String(250), nullable=False),
        sa.Column('entered_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        *stamps())
    op.create_index('ix_machine_capacity_settings_machine_id', 'machine_capacity_settings', ['machine_id'])
    op.create_index('ix_machine_capacity_settings_effective_from', 'machine_capacity_settings', ['effective_from'])

    op.create_table('machine_monthly_allocations',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('month', sa.Date(), nullable=False),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('revision_no', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id'), nullable=False),
        sa.Column('route_operation_id', sa.Integer(), sa.ForeignKey('route_operations.id'), nullable=False),
        sa.Column('machine_id', sa.Integer(), sa.ForeignKey('machines.id'), nullable=False),
        sa.Column('allocated_qty', sa.Numeric(16, 3), nullable=False),
        sa.Column('schedule_qty_snapshot', sa.Numeric(16, 3), nullable=False),
        sa.Column('capacity_qty_snapshot', sa.Numeric(16, 3), nullable=False),
        sa.Column('planning_cycle_time_sec', sa.Numeric(12, 3), nullable=False),
        sa.Column('operators_per_machine_snapshot', sa.Numeric(8, 3), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('entered_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        *stamps(),
        sa.UniqueConstraint('product_id','route_operation_id','month','revision_no','machine_id',name='uq_machine_monthly_allocation'))
    for column in ('month','effective_from','product_id','route_operation_id','machine_id'):
        op.create_index(f'ix_machine_monthly_allocations_{column}', 'machine_monthly_allocations', [column])

    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        preparer = bind.dialect.identifier_preparer
        for table in ('operator_requirement_history','machine_capacity_settings','machine_monthly_allocations'):
            op.execute(sa.text(
                f'CREATE TRIGGER {preparer.quote("revision_" + table)} '
                f'AFTER INSERT OR UPDATE OR DELETE ON {preparer.quote(table)} '
                'FOR EACH STATEMENT EXECUTE FUNCTION bump_business_data_revision()'
            ))


def downgrade():
    raise RuntimeError('Restore a verified backup; capacity and manpower history must not be discarded.')
