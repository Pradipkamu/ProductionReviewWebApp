"""Approved versioned process definitions and append-only stage allocations.

No legacy master, schedule, actual, quality or vendor facts are rewritten.
"""
from alembic import op
import sqlalchemy as sa
revision='0004_process_flows'
down_revision='0003_wip_escalation'
branch_labels=None
depends_on=None

def stamps():
    return [sa.Column('created_at',sa.DateTime(),nullable=False),sa.Column('updated_at',sa.DateTime(),nullable=False)]

def upgrade():
    op.create_table('process_flow_versions',sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('product_id',sa.Integer(),sa.ForeignKey('products.id'),nullable=False),
        sa.Column('route_version_id',sa.Integer(),sa.ForeignKey('route_versions.id'),nullable=False,unique=True),
        sa.Column('effective_from',sa.Date(),nullable=False),sa.Column('revision_no',sa.Integer(),nullable=False),
        sa.Column('company',sa.String(180)),sa.Column('definition_sha256',sa.String(64),nullable=False),
        sa.Column('source_document',sa.String(260),nullable=False),sa.Column('reason',sa.Text(),nullable=False),
        *stamps(),sa.UniqueConstraint('product_id','revision_no',name='uq_flow_product_revision'))
    op.create_table('process_flow_stages',sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('flow_id',sa.Integer(),sa.ForeignKey('process_flow_versions.id'),nullable=False),
        sa.Column('code',sa.String(180),nullable=False),sa.Column('name',sa.String(180),nullable=False),
        sa.Column('route_operation_id',sa.Integer(),sa.ForeignKey('route_operations.id'),unique=True),
        sa.Column('source_column',sa.String(10),nullable=False),sa.Column('role',sa.String(40),nullable=False),
        sa.Column('branch',sa.String(180),nullable=False),sa.Column('variant',sa.String(120),nullable=False),
        sa.Column('vendor_name',sa.String(180),nullable=False),sa.Column('predecessors_json',sa.Text(),nullable=False),
        sa.Column('alias_of',sa.String(180),nullable=False),sa.Column('is_active',sa.Boolean(),nullable=False),
        sa.Column('parent_dispatch',sa.Boolean(),nullable=False),sa.Column('sequence_no',sa.Integer(),nullable=False),
        *stamps(),sa.UniqueConstraint('flow_id','code',name='uq_flow_stage_code'))
    op.create_table('stage_schedule_allocations',sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('stage_id',sa.Integer(),sa.ForeignKey('process_flow_stages.id'),nullable=False),
        sa.Column('month',sa.Date(),nullable=False),sa.Column('effective_from',sa.Date(),nullable=False),
        sa.Column('revision_no',sa.Integer(),nullable=False),sa.Column('allocated_qty',sa.Numeric(16,3),nullable=False),
        sa.Column('working_dates_json',sa.Text(),nullable=False),sa.Column('distribution_json',sa.Text(),nullable=False),
        sa.Column('reference',sa.String(160),nullable=False),sa.Column('reason',sa.Text(),nullable=False),
        *stamps(),sa.UniqueConstraint('stage_id','month','revision_no',name='uq_stage_schedule_revision'))

def downgrade():
    raise RuntimeError('Restore backup to preserve process definitions and stage allocation history.')
