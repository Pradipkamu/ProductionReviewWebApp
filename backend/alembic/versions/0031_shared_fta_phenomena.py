"""Introduce the shared Quality Phenomena master to FTA with legacy-code compatibility.

Revision ID: 0031_shared_fta_phenomena
Revises: 0030_fta_discovered_causes

This is additive only: it preserves the legacy FTA defect library and all template
codes/versions, while mapping every existing FTA code to a canonical phenomenon.
"""
from alembic import op
import sqlalchemy as sa

revision = "0031_shared_fta_phenomena"
down_revision = "0030_fta_discovered_causes"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "quality_rejection_phenomena",
        sa.Column("fta_category", sa.String(80), nullable=True),
    )
    op.add_column(
        "quality_rejection_phenomena",
        sa.Column("fta_description", sa.Text(), nullable=True),
    )

    op.create_table(
        "fta_phenomenon_code_map",
        sa.Column(
            "legacy_defect_code",
            sa.String(60),
            sa.ForeignKey("fta_defect_library.code", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "phenomenon_id",
            sa.Integer(),
            sa.ForeignKey("quality_rejection_phenomena.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "legacy_defect_code", "phenomenon_id",
            name="uq_fta_phenomenon_code_map_code_phenomenon",
        ),
    )
    op.create_index(
        "ix_fta_phenomenon_code_map_phenomenon_id",
        "fta_phenomenon_code_map",
        ["phenomenon_id"],
    )

    # Preserve existing Quality IDs/codes. Add a canonical row only when no
    # normalized-name match exists. FTA codes remain unchanged in the map and
    # in fta_templates.defect_code for compatibility with existing templates.
    op.execute(sa.text("""
        INSERT INTO quality_rejection_phenomena
            (code, name, normalized_name, phenomenon_group,
             default_responsible_team, criticality, is_active,
             created_at, updated_at)
        SELECT
            'FTA_' || regexp_replace(d.code, '[^A-Za-z0-9]+', '_', 'g'),
            d.name,
            regexp_replace(lower(replace(trim(d.name), E'\\n', ' ')), '\s+', ' ', 'g'),
            'Machining Rejection',
            NULL,
            'NORMAL',
            d.is_active,
            now(),
            now()
        FROM fta_defect_library d
        WHERE NOT EXISTS (
            SELECT 1
            FROM quality_rejection_phenomena q
            WHERE q.normalized_name =
                regexp_replace(lower(replace(trim(d.name), E'\\n', ' ')), '\s+', ' ', 'g')
        )
    """))

    # Attach FTA metadata to the canonical row. Do not overwrite Quality
    # grouping, responsibility, criticality, name, code, or active state.
    op.execute(sa.text("""
        UPDATE quality_rejection_phenomena q
        SET fta_category = d.category,
            fta_description = d.description,
            updated_at = now()
        FROM fta_defect_library d
        WHERE q.normalized_name =
            regexp_replace(lower(replace(trim(d.name), E'\\n', ' ')), '\s+', ' ', 'g')
    """))

    op.execute(sa.text("""
        INSERT INTO fta_phenomenon_code_map (legacy_defect_code, phenomenon_id)
        SELECT d.code, q.id
        FROM fta_defect_library d
        JOIN quality_rejection_phenomena q
          ON q.normalized_name =
             regexp_replace(lower(replace(trim(d.name), E'\\n', ' ')), '\s+', ' ', 'g')
    """))

    # Fail the migration rather than silently leaving an FTA code unmapped.
    op.execute(sa.text("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM fta_defect_library d
                LEFT JOIN fta_phenomenon_code_map m
                  ON m.legacy_defect_code = d.code
                WHERE m.legacy_defect_code IS NULL
            ) THEN
                RAISE EXCEPTION 'FTA shared-phenomena migration left one or more defect codes unmapped';
            END IF;
        END $$;
    """))


def downgrade():
    # Preserve the mapping and metadata once used by the application. A
    # verified backup/forward repair is safer than removing shared references.
    raise RuntimeError(
        "This migration is intentionally irreversible; restore a verified backup "
        "or use a reviewed forward migration."
    )
