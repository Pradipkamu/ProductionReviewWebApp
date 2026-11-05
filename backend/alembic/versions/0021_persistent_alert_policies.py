"""Persist configurable alert policies and in-app delivery audit."""

import sqlalchemy as sa
from alembic import op

revision = "0021_alert_policies"
down_revision = "0020_quality_ppm_indexes"
branch_labels = None
depends_on = None


def upgrade():
    alert_policies = op.create_table(
        "alert_policies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(80), nullable=False, unique=True),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("threshold", sa.Numeric(18, 6), nullable=True),
        sa.Column("quiet_start", sa.String(5), nullable=True),
        sa.Column("quiet_end", sa.String(5), nullable=True),
        sa.Column("recipient_roles", sa.String(180), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "alert_delivery_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("policy_id", sa.Integer(), sa.ForeignKey("alert_policies.id"), nullable=True),
        sa.Column("event_key", sa.String(180), nullable=False),
        sa.Column("channel", sa.String(40), nullable=False, server_default="IN_APP"),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("recipient_role", sa.String(60), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("policy_id", "event_key", "channel", name="uq_alert_delivery_event"),
    )

    seed_rows = [
        ("dispatch_compliance", "Dispatch compliance minimum", 0.9, "MANAGEMENT,ADMIN"),
        ("high_ppm", "High PPM threshold", 1000.0, "QUALITY,MANAGEMENT,ADMIN"),
        ("oee_minimum", "OEE minimum", 0.85, "PRODUCTION,MANAGEMENT,ADMIN"),
        ("major_loss_minutes", "Major machine-loss threshold", 60.0, "PRODUCTION,MANAGEMENT,ADMIN"),
    ]
    bind = op.get_bind()
    for code, name, threshold, roles in seed_rows:
        exists = bind.execute(
            sa.select(alert_policies.c.id).where(alert_policies.c.code == code)
        ).scalar()
        if exists is None:
            bind.execute(
                alert_policies.insert().values(
                    code=code,
                    name=name,
                    threshold=threshold,
                    recipient_roles=roles,
                )
            )


def downgrade():
    op.drop_table("alert_delivery_log")
    op.drop_table("alert_policies")
