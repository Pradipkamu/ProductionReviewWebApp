"""Add MOM owner tracking, automatic closure reason and owner requests."""
from alembic import op
import sqlalchemy as sa

revision = "0018_mom_owner_collaboration"
down_revision = "0017_sales_price_two_decimals"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("review_sessions", sa.Column("owner_id", sa.Integer(), nullable=True))
    op.add_column("review_sessions", sa.Column("auto_close_reason", sa.String(length=250), nullable=True))
    op.create_index("ix_review_sessions_owner_id", "review_sessions", ["owner_id"])
    # SQLite cannot add a foreign-key constraint with ALTER TABLE directly.
    # Use batch mode so fresh databases and legacy adoption tests follow the
    # same supported table-rebuild path; PostgreSQL retains native ALTER DDL.
    with op.batch_alter_table("review_sessions") as batch_op:
        batch_op.create_foreign_key(
            "fk_review_sessions_owner_id_users", "users", ["owner_id"], ["id"], ondelete="SET NULL"
        )
    op.create_table(
        "review_meeting_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("review_session_id", sa.Integer(), sa.ForeignKey("review_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requester_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("message", sa.String(length=500), nullable=True),
        sa.Column("responded_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_review_meeting_requests_review_session_id", "review_meeting_requests", ["review_session_id"])
    op.create_index("ix_review_meeting_requests_requester_id", "review_meeting_requests", ["requester_id"])
    op.create_index("ix_review_meeting_requests_owner_id", "review_meeting_requests", ["owner_id"])
    op.create_index("ix_review_meeting_requests_status", "review_meeting_requests", ["status"])
    op.create_table(
        "review_participant_presence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("review_session_id", sa.Integer(), sa.ForeignKey("review_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("review_session_id", "user_id", name="uq_review_participant_presence"),
    )
    op.create_index("ix_review_participant_presence_review_session_id", "review_participant_presence", ["review_session_id"])
    op.create_index("ix_review_participant_presence_user_id", "review_participant_presence", ["user_id"])


def downgrade():
    op.drop_table("review_participant_presence")
    op.drop_table("review_meeting_requests")
    with op.batch_alter_table("review_sessions") as batch_op:
        batch_op.drop_constraint("fk_review_sessions_owner_id_users", type_="foreignkey")
    op.drop_index("ix_review_sessions_owner_id", table_name="review_sessions")
    op.drop_column("review_sessions", "auto_close_reason")
    op.drop_column("review_sessions", "owner_id")
