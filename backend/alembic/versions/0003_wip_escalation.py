"""Append-only receipts and in-app action reminders."""
from alembic import op
import sqlalchemy as sa
revision = '0003_wip_escalation'
down_revision = '0002_governance'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('vendor_receipts', sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('movement_id', sa.Integer(), sa.ForeignKey('vendor_movements.id'), nullable=False),
        sa.Column('receipt_date', sa.Date(), nullable=False), sa.Column('receipt_qty', sa.Numeric(16,3), nullable=False),
        sa.Column('reject_qty', sa.Numeric(16,3), nullable=False), sa.Column('reference', sa.String(160), nullable=False),
        sa.Column('entered_by_id', sa.Integer(), sa.ForeignKey('users.id')), sa.Column('remarks', sa.Text()),
        sa.Column('created_at', sa.DateTime(), nullable=False), sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('movement_id','reference',name='uq_vendor_receipt_reference'))
    op.create_index('ix_vendor_receipts_movement_id','vendor_receipts',['movement_id'])
    # Preserve pre-existing cumulative receipts as an explicit opening ledger entry.
    op.execute("INSERT INTO vendor_receipts (movement_id, receipt_date, receipt_qty, reject_qty, reference, remarks, created_at, updated_at) SELECT id, COALESCE(receipt_date, outward_date), receipt_qty, reject_qty, 'LEGACY-OPENING', 'Migrated cumulative receipt; original movement retained', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP FROM vendor_movements WHERE receipt_qty > 0 OR reject_qty > 0")
    op.create_table('action_reminders',sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('action_id',sa.Integer(),sa.ForeignKey('actions.id'),nullable=False),
        sa.Column('reminder_date',sa.Date(),nullable=False),sa.Column('kind',sa.String(60),nullable=False),
        sa.Column('level',sa.String(60),nullable=False),sa.Column('message',sa.Text(),nullable=False),
        sa.Column('acknowledged_by_id',sa.Integer(),sa.ForeignKey('users.id')),sa.Column('acknowledged_at',sa.DateTime()),
        sa.UniqueConstraint('action_id','reminder_date','kind',name='uq_action_reminder_day'))
    op.create_index('ix_action_reminders_action_id','action_reminders',['action_id'])

def downgrade():
    raise RuntimeError('Restore backup to preserve receipts and reminders.')
