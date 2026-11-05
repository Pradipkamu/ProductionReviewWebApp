"""Persist configurable alert policies and in-app delivery audit."""

from alembic import op

revision = "0021_alert_policies"
down_revision = "0020_quality_ppm_indexes"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS alert_policies (
            id SERIAL PRIMARY KEY,
            code VARCHAR(80) NOT NULL UNIQUE,
            name VARCHAR(180) NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            threshold NUMERIC(18,6),
            quiet_start VARCHAR(5),
            quiet_end VARCHAR(5),
            recipient_roles VARCHAR(180),
            updated_by_id INTEGER REFERENCES users(id),
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS alert_delivery_log (
            id SERIAL PRIMARY KEY,
            policy_id INTEGER REFERENCES alert_policies(id),
            event_key VARCHAR(180) NOT NULL,
            channel VARCHAR(40) NOT NULL DEFAULT 'IN_APP',
            status VARCHAR(40) NOT NULL,
            recipient_role VARCHAR(60),
            message TEXT NOT NULL,
            delivered_at TIMESTAMP,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_alert_delivery_event UNIQUE (policy_id, event_key, channel)
        )
    """)
    op.execute("""
        INSERT INTO alert_policies (code, name, threshold, recipient_roles)
        VALUES
            ('dispatch_compliance', 'Dispatch compliance minimum', 0.900000, 'MANAGEMENT,ADMIN'),
            ('high_ppm', 'High PPM threshold', 1000.000000, 'QUALITY,MANAGEMENT,ADMIN'),
            ('oee_minimum', 'OEE minimum', 0.850000, 'PRODUCTION,MANAGEMENT,ADMIN'),
            ('major_loss_minutes', 'Major machine-loss threshold', 60.000000, 'PRODUCTION,MANAGEMENT,ADMIN')
        ON CONFLICT (code) DO NOTHING
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS alert_delivery_log")
    op.execute("DROP TABLE IF EXISTS alert_policies")
