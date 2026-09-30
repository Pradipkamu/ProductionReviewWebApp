"""Password lifecycle and month governance."""
from alembic import op
import sqlalchemy as sa
revision = '0002_governance'
down_revision = '0001_v0216'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('users', sa.Column('must_change_password', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column('users', sa.Column('token_version', sa.Integer(), nullable=False, server_default='0'))
    op.create_table('governance_audit', sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('actor_id', sa.Integer(), sa.ForeignKey('users.id')), sa.Column('event', sa.String(80), nullable=False),
        sa.Column('entity', sa.String(100), nullable=False), sa.Column('entity_id', sa.String(100)),
        sa.Column('month', sa.Date()), sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('before_json', sa.Text()), sa.Column('after_json', sa.Text()), sa.Column('created_at', sa.DateTime(), nullable=False))
    for col in ['event', 'month']:
        op.create_index('ix_governance_audit_' + col, 'governance_audit', [col])
    op.create_table('historical_correction_grants', sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('month', sa.Date(), nullable=False), sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('approved_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False), sa.Column('expires_at', sa.DateTime(), nullable=False), sa.Column('used_at', sa.DateTime()))
    op.create_index('ix_historical_correction_grants_month', 'historical_correction_grants', ['month'])

def downgrade():
    raise RuntimeError('Governance downgrade is disabled; restore backup rather than remove audit records.')
