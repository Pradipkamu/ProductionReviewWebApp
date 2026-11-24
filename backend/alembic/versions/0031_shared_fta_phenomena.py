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
    # normalized-name match exists. Use Python normalization so the migration
    # behaves identically on PostgreSQL and SQLite legacy-adoption tests.
    import re
    bind = op.get_bind()
    defects = bind.execute(sa.text(
        "SELECT code, name, category, description, is_active FROM fta_defect_library"
    )).mappings().all()
    canonical = {
        row["normalized_name"]: row["id"]
        for row in bind.execute(sa.text(
            "SELECT id, normalized_name FROM quality_rejection_phenomena"
        )).mappings().all()
    }
    for defect in defects:
        normalized = re.sub(r"\s+", " ", (defect["name"] or "").strip().lower())
        phenomenon_id = canonical.get(normalized)
        if phenomenon_id is None:
            result = bind.execute(sa.text("""
                INSERT INTO quality_rejection_phenomena
                    (code, name, normalized_name, phenomenon_group,
                     default_responsible_team, criticality, is_active,
                     created_at, updated_at)
                VALUES
                    (:code, :name, :normalized, 'Machining Rejection',
                     NULL, 'NORMAL', :active, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                RETURNING id
            """), {
                "code": "FTA_" + re.sub(r"[^A-Za-z0-9]+", "_", defect["code"]),
                "name": defect["name"],
                "normalized": normalized,
                "active": defect["is_active"],
            })
            phenomenon_id = result.scalar_one()
            canonical[normalized] = phenomenon_id

        bind.execute(sa.text("""
            UPDATE quality_rejection_phenomena
            SET fta_category = :category,
                fta_description = :description,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :id
        """), {
            "category": defect["category"],
            "description": defect["description"],
            "id": phenomenon_id,
        })
        bind.execute(sa.text("""
            INSERT INTO fta_phenomenon_code_map (legacy_defect_code, phenomenon_id)
            VALUES (:code, :phenomenon_id)
        """), {"code": defect["code"], "phenomenon_id": phenomenon_id})

    missing = bind.execute(sa.text("""
        SELECT COUNT(*)
        FROM fta_defect_library d
        LEFT JOIN fta_phenomenon_code_map m
          ON m.legacy_defect_code = d.code
        WHERE m.legacy_defect_code IS NULL
    """)).scalar_one()
    if missing:
        raise RuntimeError(
            "FTA shared-phenomena migration left one or more defect codes unmapped"
        )


def downgrade():
    # Preserve the mapping and metadata once used by the application. A
    # verified backup/forward repair is safer than removing shared references.
    raise RuntimeError(
        "This migration is intentionally irreversible; restore a verified backup "
        "or use a reviewed forward migration."
    )
