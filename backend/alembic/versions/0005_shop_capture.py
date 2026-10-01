"""Persist OCR source, reviewed drafts and import evidence; preserve existing facts."""
from alembic import op
import sqlalchemy as sa
revision = '0005_shop_capture'
down_revision = '0004_process_flows'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('shop_captures',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('owner_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('file_sha256', sa.String(64), nullable=False),
        sa.Column('source_name', sa.String(260), nullable=False),
        sa.Column('image_path', sa.String(260), nullable=False),
        sa.Column('original_text', sa.Text(), nullable=False),
        sa.Column('draft_json', sa.Text(), nullable=False),
        sa.Column('history_json', sa.Text(), nullable=False),
        sa.Column('receipt_json', sa.Text(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(30), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('owner_id', 'file_sha256', name='uq_capture_owner_hash'))
    op.create_index('ix_shop_captures_owner_id', 'shop_captures', ['owner_id'])


def downgrade():
    raise RuntimeError('Restore a verified backup; capture evidence must not be discarded.')
