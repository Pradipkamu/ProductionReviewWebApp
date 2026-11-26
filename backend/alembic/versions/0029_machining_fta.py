"""Add configurable machining fault-tree analysis and investigations.

Revision ID: 0029_machining_fta
Revises: 0028_chat_device_tokens
"""
from alembic import op
import sqlalchemy as sa
import json

revision = "0029_machining_fta"
down_revision = "0028_chat_device_tokens"
branch_labels = None
depends_on = None


OPERATIONS = [
    ("TURN", "Turning"), ("CNC_TURN", "CNC Turning"),
    ("MILL", "Milling"), ("CNC_MILL", "CNC Milling"),
    ("DRILL", "Drilling"), ("BORE", "Boring"), ("REAM", "Reaming"),
    ("GRIND", "Grinding"), ("TAP", "Tapping"), ("THREAD", "Threading"),
    ("FACE", "Facing"), ("SLOT", "Slotting"), ("HONE", "Honing"),
    ("BROACH", "Broaching"), ("OTHER", "Other Machining"),
]

DEFECTS = [
    ("DIM-OVERSIZE", "Dimensional", "Diameter oversize", "Dimension exceeds the specified upper limit."),
    ("DIM-UNDERSIZE", "Dimensional", "Diameter undersize", "Dimension is below the specified lower limit."),
    ("DIM-LENGTH", "Dimensional", "Length variation", "Machined length is outside specification."),
    ("GEO-TAPER", "Geometrical", "Taper", "Diameter or profile varies along the machined length."),
    ("GEO-OVALITY", "Geometrical", "Ovality", "Round feature is outside roundness tolerance."),
    ("GEO-RUNOUT", "Geometrical", "Runout", "Radial or axial runout exceeds specification."),
    ("GEO-POSITION", "Geometrical", "Hole position error", "Feature position is outside positional tolerance."),
    ("GEO-FLATNESS", "Geometrical", "Flatness error", "Surface flatness is outside specification."),
    ("SURF-ROUGH", "Surface", "Poor surface finish", "Surface roughness exceeds the specified limit."),
    ("SURF-CHATTER", "Surface", "Chatter marks", "Periodic vibration marks are present on the machined surface."),
    ("BURR", "Edge", "Excessive burr", "Unacceptable burr or sharp edge remains after machining."),
    ("THREAD", "Thread", "Thread damage or incorrect thread", "Thread profile, pitch or fit is non-conforming."),
    ("GRIND-BURN", "Grinding", "Grinding burn", "Thermal damage or burn marks are visible after grinding."),
    ("TOOL-BREAK", "Tooling", "Tool breakage or tool marks", "Tool failure or abnormal tool marks affect the component."),
]

CAUSE_GROUPS = [
    ("Machine", ["Spindle runout or bearing condition", "Axis backlash or positioning accuracy", "Machine thermal growth", "Machine rigidity or vibration"]),
    ("Tooling", ["Incorrect tool geometry or size", "Tool wear or edge damage", "Tool runout or tool holder condition", "Tool deflection or insufficient rigidity"]),
    ("Method / Parameters", ["Incorrect cutting speed or feed", "Incorrect depth of cut or machining sequence", "Incorrect tool offset or compensation", "Incorrect or missing setup instruction"]),
    ("Fixture / Workholding", ["Incorrect locating or datum reference", "Insufficient or excessive clamping", "Fixture wear or poor rigidity", "Component movement during machining"]),
    ("Material", ["Hardness or material property variation", "Residual stress or material distortion", "Material / batch mix-up"]),
    ("Measurement", ["Gauge calibration or resolution issue", "Incorrect measurement method or datum", "Temperature or operator measurement variation"]),
    ("Operator / Program", ["Incorrect program or revision selected", "Incorrect setup or offset entry", "Missed first-off or in-process inspection"]),
]

def _tree_for_defect(code, name):
    children = []
    for group, causes in CAUSE_GROUPS:
        children.append({
            "id": group.lower().replace(" / ", "_").replace(" ", "_"),
            "label": group,
            "type": "INTERMEDIATE_EVENT",
            "gate": "OR",
            "children": [
                {"id": f"{group.lower().replace(' / ', '_').replace(' ', '_')}_{i+1}",
                 "label": cause, "type": "BASIC_EVENT", "gate": None, "children": []}
                for i, cause in enumerate(causes)
            ],
        })
    return {
        "id": "top_event",
        "label": f"{name} – non-conforming component",
        "type": "TOP_EVENT",
        "gate": "OR",
        "children": children,
        "notes": "Potential causes are investigation prompts, not verified conclusions. Confirm using objective evidence.",
    }


def upgrade():
    op.create_table(
        "fta_operations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(40), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "fta_defect_library",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(60), nullable=False, unique=True),
        sa.Column("category", sa.String(80), nullable=False),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "fta_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("name", sa.String(220), nullable=False),
        sa.Column("operation_code", sa.String(40), nullable=False),
        sa.Column("defect_code", sa.String(60), sa.ForeignKey("fta_defect_library.code"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(20), nullable=False, server_default="DRAFT"),
        sa.Column("tree_json", sa.Text(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("code", "version", name="uq_fta_template_code_version"),
    )
    op.create_index("ix_fta_templates_operation_defect", "fta_templates", ["operation_code", "defect_code"])
    op.create_table(
        "fta_investigations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("investigation_no", sa.String(40), nullable=False, unique=True),
        sa.Column("rejection_id", sa.Integer(), sa.ForeignKey("quality_rejection_daily.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("template_id", sa.Integer(), sa.ForeignKey("fta_templates.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("template_version", sa.Integer(), nullable=False),
        sa.Column("template_snapshot_json", sa.Text(), nullable=False),
        sa.Column("plant", sa.String(120), nullable=True),
        sa.Column("machine_id", sa.Integer(), sa.ForeignKey("machines.id", ondelete="SET NULL"), nullable=True),
        sa.Column("operation_code", sa.String(40), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="OPEN"),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("occurrence_cause_summary", sa.Text(), nullable=True),
        sa.Column("escape_cause_summary", sa.Text(), nullable=True),
        sa.Column("closure_remarks", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("verified_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("closed_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_fta_investigations_rejection", "fta_investigations", ["rejection_id"])
    op.create_index("ix_fta_investigations_status", "fta_investigations", ["status"])
    op.create_index("ix_fta_investigations_plant", "fta_investigations", ["plant"])
    op.create_index(
        "uq_fta_open_rejection_template", "fta_investigations",
        ["rejection_id", "template_id"], unique=True,
        postgresql_where=sa.text("status <> 'CLOSED'"),
        sqlite_where=sa.text("status <> 'CLOSED'"),
    )
    op.create_table(
        "fta_findings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("investigation_id", sa.Integer(), sa.ForeignKey("fta_investigations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_id", sa.String(120), nullable=False),
        sa.Column("node_label", sa.String(240), nullable=False),
        sa.Column("node_type", sa.String(40), nullable=False),
        sa.Column("investigation_status", sa.String(30), nullable=False, server_default="NOT_INVESTIGATED"),
        sa.Column("observation", sa.Text(), nullable=True),
        sa.Column("measured_value", sa.String(120), nullable=True),
        sa.Column("expected_value", sa.String(120), nullable=True),
        sa.Column("verification_method", sa.Text(), nullable=True),
        sa.Column("verification_result", sa.Text(), nullable=True),
        sa.Column("is_root_cause", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_occurrence_cause", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_escape_cause", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("investigation_id", "node_id", name="uq_fta_finding_investigation_node"),
    )
    op.create_index("ix_fta_findings_investigation", "fta_findings", ["investigation_id"])
    op.create_table(
        "fta_finding_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("finding_id", sa.Integer(), sa.ForeignKey("fta_findings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("old_snapshot_json", sa.Text(), nullable=False),
        sa.Column("new_snapshot_json", sa.Text(), nullable=False),
        sa.Column("changed_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_fta_finding_history_finding", "fta_finding_history", ["finding_id"])
    op.create_table(
        "fta_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("investigation_id", sa.Integer(), sa.ForeignKey("fta_investigations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("finding_id", sa.Integer(), sa.ForeignKey("fta_findings.id", ondelete="CASCADE"), nullable=True),
        sa.Column("file_name", sa.String(260), nullable=False),
        sa.Column("stored_name", sa.String(260), nullable=False),
        sa.Column("relative_path", sa.String(500), nullable=False),
        sa.Column("mime_type", sa.String(160), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("caption", sa.String(500), nullable=True),
        sa.Column("uploaded_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_fta_evidence_investigation", "fta_evidence", ["investigation_id"])
    op.create_index("ix_fta_evidence_sha256", "fta_evidence", ["sha256"])
    op.create_table(
        "fta_action_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("investigation_id", sa.Integer(), sa.ForeignKey("fta_investigations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("finding_id", sa.Integer(), sa.ForeignKey("fta_findings.id", ondelete="CASCADE"), nullable=True),
        sa.Column("action_id", sa.Integer(), sa.ForeignKey("actions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("relationship_type", sa.String(30), nullable=False, server_default="CORRECTIVE"),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("investigation_id", "action_id", "relationship_type", name="uq_fta_action_link"),
    )
    op.create_table(
        "fta_status_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("investigation_id", sa.Integer(), sa.ForeignKey("fta_investigations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("old_status", sa.String(30), nullable=True),
        sa.Column("new_status", sa.String(30), nullable=False),
        sa.Column("remarks", sa.Text(), nullable=True),
        sa.Column("changed_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    bind = op.get_bind()
    bind.execute(sa.text("INSERT INTO fta_operations (code, name) VALUES (:code, :name)"),
                 [{"code": code, "name": name} for code, name in OPERATIONS])
    bind.execute(sa.text("INSERT INTO fta_defect_library (code, category, name, description) VALUES (:code, :category, :name, :description)"),
                 [{"code": code, "category": category, "name": name, "description": description}
                  for code, category, name, description in DEFECTS])

    templates = []
    for operation_code, operation_name in OPERATIONS:
        for defect_code, _category, defect_name, _description in DEFECTS:
            code = f"{operation_code}-{defect_code}"
            templates.append({
                "code": code, "name": f"{operation_name} – {defect_name}",
                "operation_code": operation_code, "defect_code": defect_code,
                "tree_json": json.dumps(_tree_for_defect(defect_code, defect_name), ensure_ascii=False),
            })
    bind.execute(sa.text(
        "INSERT INTO fta_templates (code, name, operation_code, defect_code, version, status, tree_json) "
        "VALUES (:code, :name, :operation_code, :defect_code, 1, 'PUBLISHED', :tree_json)"
    ), templates)


def downgrade():
    op.drop_table("fta_status_history")
    op.drop_table("fta_action_links")
    op.drop_index("ix_fta_finding_history_finding", table_name="fta_finding_history")
    op.drop_table("fta_finding_history")
    op.drop_index("ix_fta_evidence_sha256", table_name="fta_evidence")
    op.drop_index("ix_fta_evidence_investigation", table_name="fta_evidence")
    op.drop_table("fta_evidence")
    op.drop_index("ix_fta_findings_investigation", table_name="fta_findings")
    op.drop_table("fta_findings")
    op.drop_index("uq_fta_open_rejection_template", table_name="fta_investigations")
    op.drop_index("ix_fta_investigations_plant", table_name="fta_investigations")
    op.drop_index("ix_fta_investigations_status", table_name="fta_investigations")
    op.drop_index("ix_fta_investigations_rejection", table_name="fta_investigations")
    op.drop_index("ix_fta_templates_operation_defect", table_name="fta_templates")
    op.drop_table("fta_investigations")
    op.drop_table("fta_templates")
    op.drop_table("fta_defect_library")
    op.drop_table("fta_operations")
