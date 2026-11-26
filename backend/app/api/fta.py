from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from datetime import date, datetime, timedelta
from io import BytesIO
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from ..auth import get_current_user
from ..db import get_db
from ..config import get_settings
from ..services.file_security import UploadSecurityError, safe_original_name, safe_path, save_limited_stream, validate_attachment_file
from ..models import Action, ActionContext, ActionHistory, User
from ..services.action_notifications import send_action_chat_notification

router = APIRouter(prefix="/fta", tags=["fault-tree-analysis"])

READ_ROLES = {"ADMIN", "MANAGEMENT", "QUALITY", "PRODUCTION"}
WRITE_ROLES = {"ADMIN", "QUALITY", "PRODUCTION"}
TEMPLATE_ROLES = {"ADMIN", "QUALITY"}
NODE_STATUSES = {"NOT_INVESTIGATED", "UNDER_INVESTIGATION", "SUSPECTED", "CONFIRMED", "RULED_OUT", "UNABLE_TO_DETERMINE", "NOT_APPLICABLE"}
INVESTIGATION_STATUSES = {"OPEN", "IN_PROGRESS", "VERIFIED_PENDING_ACTIONS", "CLOSED"}
MAX_FTA_EVIDENCE_BYTES = 20 * 1024 * 1024
MAX_FTA_EVIDENCE_FILES = 40
FTA_EVIDENCE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".pdf", ".xlsx", ".csv", ".txt"}


def _role_name(user: User) -> str:
    return str(getattr(user.role, "value", user.role))


def _assert_investigation_access(db: Session, investigation_id: int, user: User,
                                 allowed: set[str] = READ_ROLES):
    _role(user, allowed)
    row = db.execute(text("""
        SELECT id, owner_id, created_by_id, status, plant
        FROM fta_investigations WHERE id=:id
    """), {"id": investigation_id}).mappings().first()
    if not row:
        raise HTTPException(404, "FTA investigation not found")
    # Production users can access only investigations they created or own.
    if _role_name(user) == "PRODUCTION" and user.id not in {row["owner_id"], row["created_by_id"]}:
        raise HTTPException(404, "FTA investigation not found")
    return row


def _role(user: User, allowed: set[str]) -> None:
    role = getattr(user.role, "value", user.role)
    if role not in allowed:
        raise HTTPException(status_code=403, detail="You do not have permission to access this FTA function.")


def _json(value: str | None, fallback: Any = None) -> Any:
    try:
        return json.loads(value) if value else fallback
    except (TypeError, ValueError):
        return fallback


def _flatten_nodes(node: dict, output: list[dict]) -> None:
    if not isinstance(node, dict):
        return
    output.append({
        "node_id": str(node.get("id") or ""),
        "node_label": str(node.get("label") or "Unnamed cause"),
        "node_type": str(node.get("type") or "BASIC_EVENT"),
    })
    for child in node.get("children") or []:
        _flatten_nodes(child, output)


def _validate_tree(tree: dict) -> list[dict]:
    if not isinstance(tree, dict) or tree.get("type") != "TOP_EVENT":
        raise HTTPException(422, "The root node must be a TOP_EVENT")
    nodes: list[dict] = []
    def visit(node: dict, depth: int = 0) -> None:
        if depth > 8 or len(nodes) >= 300:
            raise HTTPException(422, "Fault tree exceeds the supported depth or node limit")
        if not isinstance(node, dict):
            raise HTTPException(422, "Every fault-tree child must be a node object")
        node_type = node.get("type")
        if node_type not in {"TOP_EVENT", "INTERMEDIATE_EVENT", "BASIC_EVENT", "EXTERNAL_EVENT", "UNDEVELOPED_EVENT"}:
            raise HTTPException(422, "Unsupported fault-tree node type")
        if depth > 0 and node_type == "TOP_EVENT":
            raise HTTPException(422, "A TOP_EVENT node can only be used as the tree root")
        node_id = str(node.get("id") or "")
        node_label = str(node.get("label") or "").strip()
        if len(node_id) > 120 or len(node_label) > 240:
            raise HTTPException(422, "Fault-tree node IDs are limited to 120 characters and labels to 240 characters")
        children = node.get("children") or []
        if not isinstance(children, list):
            raise HTTPException(422, "Fault-tree children must be a list")
        if node_type in {"TOP_EVENT", "INTERMEDIATE_EVENT"} and not children:
            raise HTTPException(422, "Top and intermediate events must contain child events")
        if node_type in {"BASIC_EVENT", "EXTERNAL_EVENT", "UNDEVELOPED_EVENT"} and children:
            raise HTTPException(422, "Basic, external and undeveloped events must be leaf nodes")
        gate = node.get("gate")
        if children and gate not in {"AND", "OR"}:
            raise HTTPException(422, "Every node with children must have an AND or OR gate")
        if not children and gate not in {None, ""}:
            raise HTTPException(422, "A leaf event cannot have a logic gate")
        nodes.append({
            "node_id": node_id,
            "node_label": node_label,
            "node_type": node_type,
        })
        for child in children:
            visit(child, depth + 1)
    visit(tree)
    ids = [node["node_id"] for node in nodes]
    if any(not node["node_id"] or not node["node_label"] for node in nodes) or len(ids) != len(set(ids)):
        raise HTTPException(422, "Every fault-tree node must have a unique ID and non-empty label")
    return nodes


def _validate_cause_classification(node_type: str, payload: "FindingUpdate") -> None:
    is_cause = payload.is_root_cause or payload.is_occurrence_cause or payload.is_escape_cause
    if is_cause and node_type not in {"BASIC_EVENT", "EXTERNAL_EVENT"}:
        raise HTTPException(422, "Only basic or external event nodes can be classified as causes")
    if is_cause and payload.investigation_status != "CONFIRMED":
        raise HTTPException(422, "Root, occurrence and escape causes must have CONFIRMED investigation status")


def _validate_action_plants(investigation_plant: str | None, action_plants: set[str]) -> None:
    plants = {str(plant).strip() for plant in action_plants if plant and str(plant).strip()}
    expected = str(investigation_plant).strip() if investigation_plant else ""
    if plants and (not expected or plants != {expected}):
        raise HTTPException(422, "The action contains context from a different or unspecified plant than this FTA investigation")


def _decorate_tree(node: dict, status_by_id: dict[str, str]) -> dict:
    children = [_decorate_tree(child, status_by_id) for child in (node.get("children") or [])]
    if children:
        states = [child["logic_state"] for child in children]
        gate = node.get("gate")
        if gate == "AND":
            state = "SATISFIED" if all(x == "SATISFIED" for x in states) else (
                "NOT_SATISFIED" if any(x == "NOT_SATISFIED" for x in states) else "UNKNOWN")
        elif gate == "OR":
            state = "SATISFIED" if any(x == "SATISFIED" for x in states) else (
                "NOT_SATISFIED" if all(x == "NOT_SATISFIED" for x in states) else "UNKNOWN")
        else:
            state = "UNKNOWN"
    else:
        status = status_by_id.get(str(node.get("id")), "NOT_INVESTIGATED")
        state = "SATISFIED" if status == "CONFIRMED" else (
            "NOT_SATISFIED" if status == "RULED_OUT" else "UNKNOWN")
    return {**node, "logic_state": state, "children": children}


def _investigation(row, db: Session) -> dict:
    result = dict(row)
    result["template_snapshot"] = _json(result.pop("template_snapshot_json", None), {})
    source = db.execute(text("""
        SELECT q.rejection_date, q.shift, q.reject_qty, p.code AS part_code,
               p.name AS part_name, ph.name AS defect_name, m.name AS machine_name
        FROM quality_rejection_daily q
        JOIN products p ON p.id=q.product_id
        JOIN quality_rejection_phenomena ph ON ph.id=q.phenomenon_id
        LEFT JOIN machines m ON m.id=COALESCE((SELECT machine_id FROM fta_investigations WHERE id=:id),q.machine_id)
        WHERE q.id=:rejection_id
    """), {"id": result["id"], "rejection_id": result["rejection_id"]}).mappings().first()
    result["source_rejection"] = dict(source) if source else {}
    findings = db.execute(text("""
        SELECT id, node_id, node_label, node_type, investigation_status, priority, observation,
               measured_value, expected_value, verification_method, verification_result,
               is_root_cause, is_occurrence_cause, is_escape_cause, updated_by_id, updated_at
        FROM fta_findings WHERE investigation_id=:id ORDER BY id
    """), {"id": result["id"]}).mappings().all()
    result["findings"] = [dict(x) for x in findings]
    finding_history = db.execute(text("""
        SELECT h.id, h.finding_id, h.old_snapshot_json, h.new_snapshot_json,
               h.changed_by_id, h.created_at
        FROM fta_finding_history h JOIN fta_findings f ON f.id=h.finding_id
        WHERE f.investigation_id=:id ORDER BY h.created_at DESC, h.id DESC
    """), {"id": result["id"]}).mappings().all()
    result["finding_history"] = [{
        "id": h["id"], "finding_id": h["finding_id"],
        "old": _json(h["old_snapshot_json"], {}), "new": _json(h["new_snapshot_json"], {}),
        "changed_by_id": h["changed_by_id"], "created_at": h["created_at"],
    } for h in finding_history]
    status_by_id = {str(x["node_id"]): x["investigation_status"] for x in findings}
    if result["template_snapshot"].get("tree"):
        result["template_snapshot"]["tree"] = _decorate_tree(result["template_snapshot"]["tree"], status_by_id)
    evidence = db.execute(text("""
        SELECT id, finding_id, file_name, mime_type, size_bytes, caption, uploaded_by_id, created_at
        FROM fta_evidence WHERE investigation_id=:id ORDER BY created_at, id
    """), {"id": result["id"]}).mappings().all()
    result["evidence"] = [dict(x) for x in evidence]
    history = db.execute(text("""
        SELECT id, old_status, new_status, remarks, changed_by_id, created_at
        FROM fta_status_history WHERE investigation_id=:id ORDER BY created_at, id
    """), {"id": result["id"]}).mappings().all()
    result["status_history"] = [dict(x) for x in history]
    actions = db.execute(text("""
        SELECT l.id AS link_id, l.relationship_type, a.id, a.action_no, a.problem_description,
               a.action_description, a.status, a.owner_id, u.full_name AS owner_name,
               a.due_at, a.requires_whywhy, a.action_type
        FROM fta_action_links l JOIN actions a ON a.id=l.action_id
        LEFT JOIN users u ON u.id=a.owner_id
        WHERE l.investigation_id=:id ORDER BY l.id
    """), {"id": result["id"]}).mappings().all()
    result["actions"] = [dict(x) for x in actions]
    action_history = db.execute(text("""
        SELECT h.id, h.action_id, a.action_no, h.changed_at, h.comment,
               h.old_status, h.new_status, u.full_name AS changed_by_name
        FROM action_history h
        JOIN fta_action_links l ON l.action_id=h.action_id
        JOIN actions a ON a.id=h.action_id
        LEFT JOIN users u ON u.id=h.changed_by_id
        WHERE l.investigation_id=:id
        ORDER BY h.changed_at, h.id
    """), {"id": result["id"]}).mappings().all()
    result["action_history"] = [dict(x) for x in action_history]
    action_evidence = db.execute(text("""
        SELECT aa.id, aa.action_id, a.action_no, aa.file_name, aa.caption, aa.size_bytes,
               aa.created_at, u.full_name AS uploaded_by_name
        FROM action_attachments aa
        JOIN fta_action_links l ON l.action_id=aa.action_id
        JOIN actions a ON a.id=aa.action_id
        LEFT JOIN users u ON u.id=aa.uploaded_by_id
        WHERE l.investigation_id=:id ORDER BY aa.created_at, aa.id
    """), {"id": result["id"]}).mappings().all()
    result["action_evidence"] = [dict(x) for x in action_evidence]
    discovered = db.execute(text("""
        SELECT c.id, c.action_id, a.action_no, c.cause_description, c.evidence_reference,
               c.status, c.reported_by_id, reporter.full_name AS reported_by_name,
               c.reviewed_by_id, reviewer.full_name AS reviewed_by_name,
               c.review_remarks, c.verification_method, c.created_at, c.reviewed_at
        FROM fta_discovered_causes c
        JOIN actions a ON a.id=c.action_id
        LEFT JOIN users reporter ON reporter.id=c.reported_by_id
        LEFT JOIN users reviewer ON reviewer.id=c.reviewed_by_id
        WHERE c.investigation_id=:id ORDER BY c.created_at, c.id
    """), {"id": result["id"]}).mappings().all()
    result["discovered_causes"] = [dict(x) for x in discovered]
    recurrences = db.execute(text("""
        SELECT r.id, r.rejection_id, r.classification, r.recurrence_reason,
               r.containment_action, r.new_evidence, r.previous_action_status,
               r.previous_verification_result, r.review_remarks, r.reviewed_at,
               r.created_at, r.related_investigation_id,
               ri.investigation_no AS related_investigation_no,
               q.rejection_date, q.reject_qty, p.code AS part_code,
               ph.name AS phenomenon
        FROM fta_recurrences r
        JOIN quality_rejection_daily q ON q.id=r.rejection_id
        JOIN products p ON p.id=q.product_id
        JOIN quality_rejection_phenomena ph ON ph.id=q.phenomenon_id
        LEFT JOIN fta_investigations ri ON ri.id=r.related_investigation_id
        WHERE r.original_investigation_id=:id
        ORDER BY q.rejection_date DESC, r.id DESC
    """), {"id": result["id"]}).mappings().all()
    result["recurrences"] = [dict(x) for x in recurrences]
    return result


class OperationCreate(BaseModel):
    code: str = Field(min_length=2, max_length=40, pattern="^[A-Z0-9_-]+$")
    name: str = Field(min_length=2, max_length=120)


class DefectCreate(BaseModel):
    code: str = Field(min_length=2, max_length=60, pattern="^[A-Z0-9_-]+$")
    category: str = Field(min_length=2, max_length=80)
    name: str = Field(min_length=2, max_length=180)
    description: str | None = Field(default=None, max_length=2000)


class TemplateCreate(BaseModel):
    code: str = Field(min_length=2, max_length=80, pattern="^[A-Z0-9_-]+$")
    name: str = Field(min_length=2, max_length=220)
    operation_code: str
    defect_code: str
    tree: dict


class TemplateTreeUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=220)
    tree: dict


class TemplateRevisionCreate(BaseModel):
    name: str | None = Field(default=None, max_length=220)
    tree: dict


class TemplateVersionUpgrade(BaseModel):
    template_id: int = Field(gt=0)
    reason: str = Field(min_length=5, max_length=2000)


class InvestigationCreate(BaseModel):
    rejection_id: int = Field(gt=0)
    template_id: int = Field(gt=0)
    machine_id: int | None = Field(default=None, gt=0)
    owner_id: int | None = Field(default=None, gt=0)
    summary: str | None = Field(default=None, max_length=4000)


class FindingUpdate(BaseModel):
    investigation_status: str = "NOT_INVESTIGATED"
    observation: str | None = Field(default=None, max_length=8000)
    measured_value: str | None = Field(default=None, max_length=120)
    expected_value: str | None = Field(default=None, max_length=120)
    verification_method: str | None = Field(default=None, max_length=4000)
    verification_result: str | None = Field(default=None, max_length=4000)
    priority: str = Field(default="MEDIUM", pattern="^(HIGH|MEDIUM|LOW)$")
    is_root_cause: bool = False
    is_occurrence_cause: bool = False
    is_escape_cause: bool = False


class InvestigationUpdate(BaseModel):
    summary: str | None = Field(default=None, max_length=4000)
    owner_id: int | None = Field(default=None, gt=0)
    occurrence_cause_summary: str | None = Field(default=None, max_length=8000)
    escape_cause_summary: str | None = Field(default=None, max_length=8000)


class ActionLinkCreate(BaseModel):
    action_id: int = Field(gt=0)
    finding_id: int | None = Field(default=None, gt=0)
    relationship_type: str = Field(default="CORRECTIVE", pattern="^(CORRECTIVE|PREVENTIVE|CONTAINMENT)$")


class FtaActionCreate(BaseModel):
    action_description: str = Field(min_length=3, max_length=8000)
    finding_id: int | None = Field(default=None, gt=0)


class DiscoveredCauseCreate(BaseModel):
    cause_description: str = Field(min_length=5, max_length=4000)
    evidence_reference: str = Field(min_length=3, max_length=2000)


class DiscoveredCauseReview(BaseModel):
    status: str = Field(pattern="^(ACCEPTED|CONFIRMED|RULED_OUT)$")
    review_remarks: str = Field(min_length=5, max_length=4000)
    verification_method: str | None = Field(default=None, max_length=2000)


class VerifyRequest(BaseModel):
    remarks: str = Field(min_length=5, max_length=4000)


class CloseRequest(BaseModel):
    remarks: str = Field(min_length=5, max_length=4000)


@router.get("/operations")
def list_operations(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _role(user, READ_ROLES)
    rows = db.execute(text("SELECT id, code, name FROM fta_operations WHERE is_active=true ORDER BY name")).mappings().all()
    return [dict(x) for x in rows]


@router.get("/defects")
def list_defects(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _role(user, READ_ROLES)
    rows = db.execute(text("""
        SELECT l.id, l.code, q.fta_category AS category, q.name,
               q.fta_description AS description, q.id AS phenomenon_id
        FROM fta_phenomenon_code_map fm
        JOIN fta_defect_library l ON l.code=fm.legacy_defect_code
        JOIN quality_rejection_phenomena q ON q.id=fm.phenomenon_id
        WHERE l.is_active=true AND q.is_active=true
        ORDER BY q.fta_category, q.name
    """)).mappings().all()
    return [dict(x) for x in rows]


@router.get("/rejections")
def list_rejections(limit: int = 100, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _role(user, READ_ROLES)
    limit = max(1, min(limit, 300))
    rows = db.execute(text("""
        SELECT q.id, q.product_id, q.phenomenon_id, q.rejection_date, q.shift,
               COALESCE(q.plant,p.plant) AS plant, q.machine_id,
               q.reject_qty, q.remark, p.code AS part_code, p.name AS part_name,
               ph.name AS phenomenon, m.name AS machine
        FROM quality_rejection_daily q
        JOIN products p ON p.id=q.product_id
        JOIN quality_rejection_phenomena ph ON ph.id=q.phenomenon_id
        LEFT JOIN machines m ON m.id=q.machine_id
        WHERE UPPER(COALESCE(ph.phenomenon_group,'')) NOT LIKE '%CAST%'
          AND UPPER(ph.name) NOT LIKE '%CASTING%'
          AND NOT EXISTS (SELECT 1 FROM fta_investigations fi WHERE fi.rejection_id=q.id)
          AND NOT EXISTS (SELECT 1 FROM fta_recurrences fr WHERE fr.rejection_id=q.id)
        ORDER BY q.rejection_date DESC, q.id DESC LIMIT :limit
    """), {"limit": limit}).mappings().all()
    return [dict(x) for x in rows]


@router.post("/operations", status_code=201)
def create_operation(payload: OperationCreate, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    _role(user, TEMPLATE_ROLES)
    try:
        row = db.execute(text("""
            INSERT INTO fta_operations (code, name) VALUES (:code, :name) RETURNING id, code, name
        """), {"code": payload.code.upper(), "name": payload.name.strip()}).mappings().one()
        db.commit()
        return dict(row)
    except Exception:
        db.rollback()
        raise HTTPException(409, "Operation code already exists or could not be created")


@router.post("/defects", status_code=201)
def create_defect(payload: DefectCreate, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    _role(user, TEMPLATE_ROLES)
    try:
        code = payload.code.upper()
        name = " ".join(payload.name.split())
        normalized = " ".join(name.replace("\n", " ").strip().lower().split())
        canonical_code = "FTA_" + re.sub(r"[^A-Z0-9]+", "_", code).strip("_")
        row = db.execute(text("""
            INSERT INTO fta_defect_library (code, category, name, description)
            VALUES (:code, :category, :name, :description)
            RETURNING id, code, category, name, description
        """), {"code": code, "category": payload.category.strip(),
               "name": name, "description": payload.description}).mappings().one()
        phenomenon = db.execute(text("""
            INSERT INTO quality_rejection_phenomena
                (code, name, normalized_name, phenomenon_group,
                 criticality, is_active, fta_category, fta_description,
                 created_at, updated_at)
            VALUES
                (:canonical_code, :name, :normalized, 'Machining Rejection',
                 'NORMAL', true, :category, :description, now(), now())
            ON CONFLICT (normalized_name) DO UPDATE
            SET fta_category=EXCLUDED.fta_category,
                fta_description=EXCLUDED.fta_description,
                updated_at=now()
            RETURNING id
        """), {"canonical_code": canonical_code, "name": name, "normalized": normalized,
               "category": payload.category.strip(), "description": payload.description}).mappings().one()
        db.execute(text("""
            INSERT INTO fta_phenomenon_code_map (legacy_defect_code, phenomenon_id)
            VALUES (:code, :phenomenon_id)
        """), {"code": code, "phenomenon_id": phenomenon["id"]})
        db.commit()
        return {**dict(row), "phenomenon_id": phenomenon["id"]}
    except Exception:
        db.rollback()
        raise HTTPException(409, "Defect code already exists or could not be created")


@router.post("/templates", status_code=201)
def create_template(payload: TemplateCreate, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    _role(user, TEMPLATE_ROLES)
    if not db.execute(text("SELECT code FROM fta_operations WHERE code=:code AND is_active=true"),
                      {"code": payload.operation_code}).first():
        raise HTTPException(422, "Select an active machining operation")
    if not db.execute(text("""
        SELECT l.code FROM fta_defect_library l
        JOIN fta_phenomenon_code_map fm ON fm.legacy_defect_code=l.code
        JOIN quality_rejection_phenomena q ON q.id=fm.phenomenon_id
        WHERE l.code=:code AND l.is_active=true AND q.is_active=true
    """), {"code": payload.defect_code}).first():
        raise HTTPException(422, "Select an active shared phenomenon")
    _validate_tree(payload.tree)
    try:
        row = db.execute(text("""
            INSERT INTO fta_templates
            (code, name, operation_code, defect_code, version, status, tree_json, created_by_id, updated_by_id)
            VALUES (:code, :name, :operation_code, :defect_code, 1, 'DRAFT', :tree_json, :user_id, :user_id)
            RETURNING id, code, name, operation_code, defect_code, version, status
        """), {"code": payload.code.upper(), "name": payload.name.strip(),
               "operation_code": payload.operation_code, "defect_code": payload.defect_code,
               "tree_json": json.dumps(payload.tree, ensure_ascii=False), "user_id": user.id}).mappings().one()
        db.commit()
        return dict(row)
    except Exception:
        db.rollback()
        raise HTTPException(409, "Template code already exists or could not be created")



@router.put("/templates/{template_id}")
def update_template(template_id: int, payload: TemplateTreeUpdate,
                    db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _role(user, TEMPLATE_ROLES)
    row = db.execute(text("SELECT status FROM fta_templates WHERE id=:id"), {"id": template_id}).mappings().first()
    if not row:
        raise HTTPException(404, "FTA template not found")
    if row["status"] != "DRAFT":
        raise HTTPException(409, "Published templates are immutable; create a new revision")
    _validate_tree(payload.tree)
    db.execute(text("""
        UPDATE fta_templates SET name=:name, tree_json=:tree, updated_by_id=:user_id,
          updated_at=:now WHERE id=:id
    """), {"name": payload.name.strip(), "tree": json.dumps(payload.tree, ensure_ascii=False),
           "user_id": user.id, "now": datetime.utcnow(), "id": template_id})
    db.commit()
    return {"success": True, "template_id": template_id, "status": "DRAFT"}


@router.post("/templates/{template_id}/revisions", status_code=201)
def create_template_revision(template_id: int, payload: TemplateRevisionCreate,
                             db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _role(user, TEMPLATE_ROLES)
    source = db.execute(text("SELECT * FROM fta_templates WHERE id=:id"), {"id": template_id}).mappings().first()
    if not source:
        raise HTTPException(404, "FTA template not found")
    _validate_tree(payload.tree)
    version = db.execute(text("SELECT COALESCE(MAX(version),0)+1 FROM fta_templates WHERE code=:code"),
                         {"code": source["code"]}).scalar_one()
    row = db.execute(text("""
        INSERT INTO fta_templates
        (code, name, operation_code, defect_code, version, status, tree_json, created_by_id, updated_by_id)
        VALUES (:code, :name, :operation_code, :defect_code, :version, 'DRAFT', :tree,
                :user_id, :user_id) RETURNING id, code, name, version, status
    """), {"code": source["code"], "name": payload.name or source["name"],
           "operation_code": source["operation_code"], "defect_code": source["defect_code"],
           "version": version, "tree": json.dumps(payload.tree, ensure_ascii=False),
           "user_id": user.id}).mappings().one()
    db.commit()
    return dict(row)


@router.post("/templates/{template_id}/publish")
def publish_template(template_id: int, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    _role(user, TEMPLATE_ROLES)
    row = db.execute(text("SELECT * FROM fta_templates WHERE id=:id"), {"id": template_id}).mappings().first()
    if not row:
        raise HTTPException(404, "FTA template not found")
    if row["status"] == "PUBLISHED":
        raise HTTPException(409, "Template is already published")
    tree = _json(row["tree_json"], {})
    _validate_tree(tree)
    db.execute(text("""
        UPDATE fta_templates SET status='PUBLISHED', updated_by_id=:user_id, updated_at=:now WHERE id=:id
    """), {"user_id": user.id, "now": datetime.utcnow(), "id": template_id})
    db.commit()
    return {"success": True, "template_id": template_id, "status": "PUBLISHED"}


@router.get("/templates")
def list_templates(operation_code: str | None = None, defect_code: str | None = None,
                   include_drafts: bool = False, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    _role(user, READ_ROLES)
    if include_drafts:
        _role(user, TEMPLATE_ROLES)
    query = """
        SELECT t.id, t.code, t.name, t.operation_code, o.name AS operation_name,
               t.defect_code, d.name AS defect_name, d.fta_category AS defect_category,
               t.version, t.status
        FROM fta_templates t
        JOIN fta_operations o ON o.code=t.operation_code
        JOIN fta_phenomenon_code_map fm ON fm.legacy_defect_code=t.defect_code
        JOIN quality_rejection_phenomena d ON d.id=fm.phenomenon_id
        WHERE (
          (t.status='PUBLISHED' AND t.version=(
              SELECT MAX(t2.version) FROM fta_templates t2
              WHERE t2.code=t.code AND t2.status='PUBLISHED'
          ))
          OR (:include_drafts=true AND t.status='DRAFT')
        )
    """
    params = {"include_drafts": include_drafts}
    if operation_code:
        query += " AND t.operation_code=:operation_code"
        params["operation_code"] = operation_code
    if defect_code:
        query += " AND t.defect_code=:defect_code"
        params["defect_code"] = defect_code
    query += " ORDER BY o.name, d.fta_category, d.name, t.version DESC"
    rows = db.execute(text(query), params).mappings().all()
    return [dict(x) for x in rows]


@router.get("/templates/{template_id}")
def get_template(template_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _role(user, READ_ROLES)
    row = db.execute(text("""
        SELECT t.id, t.code, t.name, t.operation_code, o.name AS operation_name,
               t.defect_code, d.name AS defect_name, d.fta_category AS defect_category,
               t.version, t.status, t.tree_json
        FROM fta_templates t JOIN fta_operations o ON o.code=t.operation_code
        JOIN fta_phenomenon_code_map fm ON fm.legacy_defect_code=t.defect_code
        JOIN quality_rejection_phenomena d ON d.id=fm.phenomenon_id WHERE t.id=:id
    """), {"id": template_id}).mappings().first()
    if not row:
        raise HTTPException(404, "FTA template not found")
    if row["status"] != "PUBLISHED":
        _role(user, TEMPLATE_ROLES)
    return {**dict(row), "tree": _json(row["tree_json"], {})}


@router.get("/investigations")
def list_investigations(status: str | None = None, rejection_id: int | None = None,
                        plant: str | None = None, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    _role(user, READ_ROLES)
    query = """
        SELECT i.id, i.investigation_no, i.rejection_id, i.template_id, i.operation_code,
               i.plant, i.machine_id, m.name AS machine_name, i.status, i.owner_id, i.summary, i.created_at,
               t.name AS template_name, d.name AS defect_name, p.code AS part_code, p.name AS part_name
        FROM fta_investigations i
        JOIN fta_templates t ON t.id=i.template_id
        JOIN fta_phenomenon_code_map fm ON fm.legacy_defect_code=t.defect_code
        JOIN quality_rejection_phenomena d ON d.id=fm.phenomenon_id
        JOIN quality_rejection_daily q ON q.id=i.rejection_id
        JOIN products p ON p.id=q.product_id
        LEFT JOIN machines m ON m.id=i.machine_id WHERE 1=1
    """
    params = {}
    if status:
        query += " AND i.status=:status"; params["status"] = status
    if rejection_id:
        query += " AND i.rejection_id=:rejection_id"; params["rejection_id"] = rejection_id
    if plant:
        query += " AND i.plant=:plant"; params["plant"] = plant
    if _role_name(user) == "PRODUCTION":
        query += " AND (i.owner_id=:user_id OR i.created_by_id=:user_id)"
        params["user_id"] = user.id
    query += " ORDER BY i.created_at DESC, i.id DESC LIMIT 500"
    return [dict(x) for x in db.execute(text(query), params).mappings().all()]


@router.post("/investigations", status_code=201)
def create_investigation(payload: InvestigationCreate, db: Session = Depends(get_db),
                         user: User = Depends(get_current_user)):
    _role(user, WRITE_ROLES)
    template = db.execute(text("""
        SELECT id, code, name, operation_code, defect_code, version, tree_json
        FROM fta_templates WHERE id=:id AND status='PUBLISHED'
    """), {"id": payload.template_id}).mappings().first()
    if not template:
        raise HTTPException(404, "Published FTA template not found")
    latest_published_version = db.execute(text("""
        SELECT MAX(version) FROM fta_templates
        WHERE code=:code AND status='PUBLISHED'
    """), {"code": template["code"]}).scalar_one()
    if template["version"] != latest_published_version:
        raise HTTPException(409, "This template revision is no longer current. Refresh and select the latest published revision.")
    rejection = db.execute(text("""
        SELECT q.id, COALESCE(q.plant,p.plant) AS plant, q.machine_id, q.product_id, q.phenomenon_id,
               q.rejection_date, q.shift, q.reject_qty, q.remark, p.code AS part_code,
               p.name AS part_name, ph.name AS rejection_phenomenon
        FROM quality_rejection_daily q
        JOIN products p ON p.id=q.product_id
        JOIN quality_rejection_phenomena ph ON ph.id=q.phenomenon_id
        WHERE q.id=:id
          AND UPPER(COALESCE(ph.phenomenon_group,'')) NOT LIKE '%CAST%'
          AND UPPER(ph.name) NOT LIKE '%CASTING%'
    """), {"id": payload.rejection_id}).mappings().first()
    if not rejection:
        raise HTTPException(404, "Machining-compatible Quality Rejection record not found")
    machine_id = payload.machine_id or rejection["machine_id"]
    if machine_id:
        machine = db.execute(text("SELECT id, plant FROM machines WHERE id=:id AND is_active=true"),
                              {"id": machine_id}).mappings().first()
        if not machine:
            raise HTTPException(422, "Selected machine is not active or does not exist")
        if rejection["plant"] and machine["plant"] and machine["plant"] != rejection["plant"]:
            raise HTTPException(422, "Selected machine belongs to a different plant than the rejection")
    if _role_name(user) == "PRODUCTION" and payload.owner_id not in {None, user.id}:
        raise HTTPException(403, "Production users can assign an investigation only to themselves")
    if payload.owner_id and not db.execute(text("SELECT id FROM users WHERE id=:id AND is_active=true"),
                                           {"id": payload.owner_id}).first():
        raise HTTPException(422, "Selected investigation owner is not active")
    # One Quality Rejection can be the primary trigger for only one FTA.
    # Later rejection rows are added to the original investigation as recurrence
    # records; changing template/version must not create a second primary FTA.
    existing = db.execute(text("""
        SELECT id, investigation_no, status FROM fta_investigations
        WHERE rejection_id=:rejection_id
        ORDER BY id DESC LIMIT 1
    """), {"rejection_id": payload.rejection_id}).mappings().first()
    if existing:
        raise HTTPException(
            409,
            detail=f"Quality Rejection #{payload.rejection_id} is already linked to "
                   f"{existing['investigation_no']}. Add a later rejection from the "
                   "original FTA's Recurrence Management section instead."
        )
    tree = _json(template["tree_json"], {})
    snapshot = {
        "template_id": template["id"], "template_code": template["code"],
        "template_name": template["name"], "template_version": template["version"],
        "operation_code": template["operation_code"], "defect_code": template["defect_code"],
        "rejection": {k: str(v) if v is not None else None for k, v in dict(rejection).items()},
        "tree": tree,
    }
    now = datetime.utcnow()
    try:
        new_id = db.execute(text("""
            INSERT INTO fta_investigations
            (investigation_no, rejection_id, template_id, template_version, template_snapshot_json,
             plant, machine_id, operation_code, summary, status, owner_id, created_by_id, created_at, updated_at)
            VALUES ('PENDING', :rejection_id, :template_id, :version, :snapshot,
                    :plant, :machine_id, :operation_code, :summary, 'OPEN', :owner_id, :user_id, :now, :now)
            RETURNING id
        """), {
            "rejection_id": payload.rejection_id, "template_id": payload.template_id,
            "version": template["version"], "snapshot": json.dumps(snapshot, ensure_ascii=False, default=str),
            "plant": rejection["plant"], "machine_id": machine_id, "operation_code": template["operation_code"],
            "summary": payload.summary, "owner_id": payload.owner_id or user.id, "user_id": user.id, "now": now,
        }).scalar_one()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "An active investigation already exists for this rejection and template") from exc
    number = f"FTA-{now.year}-{new_id:05d}"
    db.execute(text("UPDATE fta_investigations SET investigation_no=:number WHERE id=:id"),
               {"number": number, "id": new_id})
    nodes: list[dict] = []
    _flatten_nodes(tree, nodes)
    for node in nodes:
        db.execute(text("""
            INSERT INTO fta_findings
            (investigation_id, node_id, node_label, node_type, investigation_status, updated_by_id)
            VALUES (:investigation_id, :node_id, :node_label, :node_type, 'NOT_INVESTIGATED', :user_id)
        """), {**node, "investigation_id": new_id, "user_id": user.id})
    db.execute(text("""
        INSERT INTO fta_status_history (investigation_id, old_status, new_status, remarks, changed_by_id)
        VALUES (:id, NULL, 'OPEN', 'Investigation created from Quality Rejection.', :user_id)
    """), {"id": new_id, "user_id": user.id})
    db.commit()
    row = db.execute(text("SELECT * FROM fta_investigations WHERE id=:id"), {"id": new_id}).mappings().one()
    return _investigation(row, db)


@router.post("/investigations/{investigation_id}/template-version")
def upgrade_investigation_template_version(
    investigation_id: int,
    payload: TemplateVersionUpgrade,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Upgrade an open FTA to a newer published revision of the same template only."""
    row = _assert_investigation_access(db, investigation_id, user, WRITE_ROLES)
    if row["status"] not in {"OPEN", "IN_PROGRESS"}:
        raise HTTPException(409, "FTA template version can only be upgraded before verification.")

    confirmed_root_cause = db.execute(text("""
        SELECT EXISTS (
            SELECT 1 FROM fta_findings
            WHERE investigation_id=:id
              AND investigation_status='CONFIRMED'
              AND is_root_cause=true
        ) OR EXISTS (
            SELECT 1 FROM fta_discovered_causes
            WHERE investigation_id=:id AND status='CONFIRMED'
        )
    """), {"id": investigation_id}).scalar()
    if confirmed_root_cause:
        raise HTTPException(409, "FTA template version cannot be changed after root cause confirmation.")

    current = db.execute(text("""
        SELECT i.template_id, i.template_version, i.template_snapshot_json,
               t.code, t.operation_code, t.defect_code
        FROM fta_investigations i
        JOIN fta_templates t ON t.id=i.template_id
        WHERE i.id=:id
        FOR UPDATE OF i
    """), {"id": investigation_id}).mappings().one()

    target = db.execute(text("""
        SELECT id, code, name, operation_code, defect_code, version, status, tree_json
        FROM fta_templates WHERE id=:template_id
    """), {"template_id": payload.template_id}).mappings().first()
    if not target or target["status"] != "PUBLISHED":
        raise HTTPException(404, "Target published template version not found.")
    if target["code"] != current["code"]:
        raise HTTPException(422, "Only a newer version of the same FTA template can be selected.")
    if target["operation_code"] != current["operation_code"] or target["defect_code"] != current["defect_code"]:
        raise HTTPException(422, "The template version must retain the same operation and Quality defect.")
    latest = db.execute(text("""
        SELECT MAX(version) FROM fta_templates
        WHERE code=:code AND status='PUBLISHED'
    """), {"code": current["code"]}).scalar_one()
    if target["version"] != latest:
        raise HTTPException(409, "Select the latest published version of this template.")
    if int(target["version"]) <= int(current["template_version"]):
        raise HTTPException(409, "Only a newer template version can be applied.")

    new_tree = _json(target["tree_json"], {})
    new_nodes = _validate_tree(new_tree)
    old_snapshot = _json(current["template_snapshot_json"], {})
    new_snapshot = {
        **old_snapshot,
        "template_id": target["id"],        "template_code": target["code"],
        "template_name": target["name"],
        "template_version": target["version"],
        "operation_code": target["operation_code"],
        "defect_code": target["defect_code"],
        "tree": new_tree,
    }
    now = datetime.utcnow()
    try:
        # Keep existing findings (including nodes removed from the new tree) so their
        # evidence and finding history remain available for audit. Matching node IDs
        # retain all recorded investigation data; newly introduced IDs start blank.
        existing_nodes = {
            str(x["node_id"]) for x in db.execute(text("""
                SELECT node_id FROM fta_findings WHERE investigation_id=:id
            """), {"id": investigation_id}).mappings().all()
        }
        for node in new_nodes:
            if node["node_id"] in existing_nodes:
                db.execute(text("""
                    UPDATE fta_findings SET node_label=:label, node_type=:type
                    WHERE investigation_id=:id AND node_id=:node_id
                """), {"label": node["node_label"], "type": node["node_type"],
                       "id": investigation_id, "node_id": node["node_id"]})
            else:
                db.execute(text("""
                    INSERT INTO fta_findings
                    (investigation_id, node_id, node_label, node_type,
                     investigation_status, updated_by_id, updated_at)
                    VALUES (:id, :node_id, :label, :type, 'NOT_INVESTIGATED', :user_id, :now)
                """), {"id": investigation_id, "node_id": node["node_id"],
                       "label": node["node_label"], "type": node["node_type"],
                       "user_id": user.id, "now": now})

        db.execute(text("""
            UPDATE fta_investigations
            SET template_id=:template_id, template_version=:version,
                template_snapshot_json=:snapshot, updated_at=:now
            WHERE id=:id
        """), {"template_id": target["id"], "version": target["version"],
               "snapshot": json.dumps(new_snapshot, ensure_ascii=False, default=str),
               "now": now, "id": investigation_id})

        audit = {
            "event": "FTA_TEMPLATE_VERSION_UPGRADED",
            "reason": payload.reason.strip(),
            "old_template_id": current["template_id"],
            "old_template_version": current["template_version"],
            "new_template_id": target["id"],
            "new_template_version": target["version"],
            "old_template_snapshot": old_snapshot,
            "new_template_snapshot": new_snapshot,
        }
        db.execute(text("""
            INSERT INTO fta_status_history
            (investigation_id, old_status, new_status, remarks, changed_by_id, created_at)
            VALUES (:id, :status, :status, :remarks, :user_id, :now)
        """), {"id": investigation_id, "status": row["status"],
               "remarks": json.dumps(audit, ensure_ascii=False, default=str),
               "user_id": user.id, "now": now})
        db.commit()
    except Exception:
        db.rollback()
        raise
    updated = db.execute(text("SELECT * FROM fta_investigations WHERE id=:id"),
                         {"id": investigation_id}).mappings().one()
    return _investigation(updated, db)


@router.get("/investigations/{investigation_id}")
def get_investigation(investigation_id: int, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    _assert_investigation_access(db, investigation_id, user)
    row = db.execute(text("SELECT * FROM fta_investigations WHERE id=:id"), {"id": investigation_id}).mappings().one()
    return _investigation(row, db)




def _excel_value(value):
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.replace(tzinfo=None) if isinstance(value, datetime) else value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return value


def _fta_excel_workbook(data: dict) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "FTA Mind Map"
    navy = "17365D"
    grey = "E7E6E6"
    green = "E2F0D9"
    yellow = "FFF2CC"
    red = "FCE4D6"
    white = "FFFFFF"
    thin_grey = Side(style="thin", color="A6A6A6")

    ws.sheet_view.showGridLines = False
    ws.sheet_view.zoomScale = 70
    ws.merge_cells("A1:H1")
    ws["A1"] = f"FAULT TREE ANALYSIS — {data.get('investigation_no') or ''}"
    ws["A1"].font = Font(bold=True, size=16, color=white)
    ws["A1"].fill = PatternFill("solid", fgColor=navy)
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 30
    ws.merge_cells("A2:H2")
    src = data.get("source_rejection") or {}
    ws["A2"] = (
        f"Part: {src.get('part_code') or ''} {src.get('part_name') or ''} | "
        f"Defect: {src.get('defect_name') or ''} | Machine: {src.get('machine_name') or data.get('machine_id') or ''} | "
        f"Status: {data.get('status') or ''}"
    )
    ws["A2"].font = Font(italic=True, color="404040")
    ws["A2"].alignment = Alignment(wrap_text=True, vertical="center")
    ws.row_dimensions[2].height = 30
    ws.merge_cells("A3:H3")
    ws["A3"] = "Read from left to right. Each box is a fault-tree event; AND / OR indicates the logic gate connecting its child events."
    ws["A3"].font = Font(size=9, color="666666")
    ws["A3"].alignment = Alignment(wrap_text=True)
    ws.row_dimensions[3].height = 24

    findings = {str(x.get("node_id")): x for x in data.get("findings", [])}
    tree = (data.get("template_snapshot") or {}).get("tree")
    leaf_cursor = [5]
    node_positions = []

    def place(node, depth=0):
        children = node.get("children") or []
        if not children:
            start = end = leaf_cursor[0]
            leaf_cursor[0] += 3
        else:
            child_positions = [place(child, depth + 1) for child in children]
            start, end = child_positions[0][0], child_positions[-1][1]
        center = (start + end) // 2
        node_positions.append((node, depth, start, end, center))
        return start, end

    if isinstance(tree, dict):
        place(tree)
    max_depth = max((x[1] for x in node_positions), default=0)
    last_col = 1 + max_depth * 3
    for col in range(1, last_col + 1):
        ws.column_dimensions[get_column_letter(col)].width = 4 if (col - 1) % 3 else 34
    for row in range(5, max(6, leaf_cursor[0])):
        ws.row_dimensions[row].height = 18

    for node, depth, start, end, center in node_positions:
        col = 1 + depth * 3
        finding = findings.get(str(node.get("id")), {})
        status = finding.get("investigation_status") or "NOT_INVESTIGATED"
        fill = green if status == "CONFIRMED" else yellow if status in {"SUSPECTED", "UNDER_INVESTIGATION"} else red if status == "RULED_OUT" else grey
        flags = []
        if finding.get("is_root_cause"): flags.append("ROOT CAUSE")
        if finding.get("is_occurrence_cause"): flags.append("OCCURRENCE")
        if finding.get("is_escape_cause"): flags.append("ESCAPE")
        gate = node.get("gate") or "LEAF EVENT"
        label = str(node.get("label") or "Unnamed event")
        cell = ws.cell(center, col)
        cell.value = f"{label}\n[{node.get('type', 'EVENT').replace('_', ' ')}] · {gate}\nStatus: {status.replace('_', ' ')}"
        if flags:
            cell.value += "\n" + " / ".join(flags)
        cell.fill = PatternFill("solid", fgColor=fill)
        cell.font = Font(bold=True, size=9, color="202020")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = Border(left=thin_grey, right=thin_grey, top=thin_grey, bottom=thin_grey)
        ws.row_dimensions[center].height = max(ws.row_dimensions[center].height or 18, 66)
        children = node.get("children") or []
        if children:
            connector_col = col + 1
            child_centers = []
            for child, child_depth, child_start, child_end, child_center in node_positions:
                if child_depth == depth + 1 and child_start >= start and child_end <= end:
                    # Direct children are those whose parent is this node.
                    if child in children:
                        child_centers.append(child_center)
            if child_centers:
                top, bottom = min(child_centers), max(child_centers)
                for rr in range(top, bottom + 1):
                    ws.cell(rr, connector_col).border = Border(left=thin_grey)
                for rr in child_centers:
                    ws.cell(rr, connector_col).border = Border(left=thin_grey, bottom=thin_grey)
                    ws.cell(rr, col + 2).border = Border(bottom=thin_grey)

    ws.freeze_panes = "A5"
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A3
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.page_margins.left = 0.25
    ws.page_margins.right = 0.25
    ws.page_margins.top = 0.4
    ws.page_margins.bottom = 0.4
    ws.print_title_rows = "1:3"
    ws.sheet_properties.outlinePr.summaryRight = True

    def add_table_sheet(title, headers, rows):
        sh = wb.create_sheet(title[:31])
        sh.sheet_view.showGridLines = False
        sh.append([title])
        sh.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max(1, len(headers)))
        sh["A1"].font = Font(bold=True, size=14, color=white)
        sh["A1"].fill = PatternFill("solid", fgColor=navy)
        sh["A1"].alignment = Alignment(vertical="center")
        sh.row_dimensions[1].height = 26
        sh.append(headers)
        for cell in sh[2]:
            cell.font = Font(bold=True, color=white)
            cell.fill = PatternFill("solid", fgColor=navy)
            cell.alignment = Alignment(wrap_text=True, vertical="center")
        for row in rows:
            sh.append([_excel_value(v) for v in row])
        sh.freeze_panes = "A3"
        sh.auto_filter.ref = sh.dimensions
        for col_cells in sh.columns:
            letter = get_column_letter(col_cells[0].column)
            max_len = min(55, max((len(str(c.value or "")) for c in col_cells), default=12))
            sh.column_dimensions[letter].width = max(14, max_len + 2)
            for cell in col_cells[2:]:
                cell.alignment = Alignment(vertical="top", wrap_text=True)
        sh.sheet_properties.pageSetUpPr.fitToPage = True
        sh.page_setup.orientation = "landscape"
        sh.page_setup.fitToWidth = 1
        sh.page_setup.fitToHeight = 0
        return sh

    add_table_sheet("Investigation", ["Field", "Value"], [
        ("Investigation No.", data.get("investigation_no")),
        ("Status", data.get("status")),
        ("Plant", data.get("plant")),
        ("Operation", data.get("operation_code")),
        ("Machine", src.get("machine_name") or data.get("machine_id")),
        ("Part", f"{src.get('part_code') or ''} {src.get('part_name') or ''}".strip()),
        ("Defect", src.get("defect_name")),
        ("Rejection Date", src.get("rejection_date")),
        ("Rejected Quantity", src.get("reject_qty")),
        ("Summary", data.get("summary")),
        ("Occurrence Cause Analysis", data.get("occurrence_cause_summary")),
        ("Escape / Detection Analysis", data.get("escape_cause_summary")),
        ("Verification Date", data.get("verified_at")),
        ("Closure Date", data.get("closed_at")),
        ("Closure Remarks", data.get("closure_remarks")),
    ])
    add_table_sheet("Findings",
        ["Node", "Type", "Status", "Priority", "Observation / N/A Reason", "Measured Value", "Expected Value", "Verification Method", "Verification Result", "Root Cause", "Occurrence Cause", "Escape Cause"],
        [(x.get("node_label"), x.get("node_type"), x.get("investigation_status"), x.get("priority", "MEDIUM"), x.get("observation"),
          x.get("measured_value"), x.get("expected_value"), x.get("verification_method"), x.get("verification_result"),
          x.get("is_root_cause"), x.get("is_occurrence_cause"), x.get("is_escape_cause")) for x in data.get("findings", [])])
    add_table_sheet("Evidence Register",
        ["Finding", "File Name", "Caption", "MIME Type", "Size (bytes)", "Uploaded Date"],
        [(
            (findings.get(str(x.get("finding_id"))) or {}).get("node_label")
            if x.get("finding_id") else "Investigation-level",
            x.get("file_name"), x.get("caption"), x.get("mime_type"),
            x.get("size_bytes"), x.get("created_at")
        ) for x in data.get("evidence", [])])
    add_table_sheet("Actions",
        ["Action No.", "Relationship", "Problem", "Action Description", "Owner", "Due Date", "Status"],
        [(x.get("action_no"), x.get("relationship_type"), x.get("problem_description"), x.get("action_description"),
          x.get("owner_name"), x.get("due_at"), x.get("status")) for x in data.get("actions", [])])
    add_table_sheet("Action History",
        ["Action No.", "Changed By", "Changed At", "Old Status", "New Status", "Comment"],
        [(x.get("action_no"), x.get("changed_by_name"), x.get("changed_at"), x.get("old_status"), x.get("new_status"), x.get("comment"))
         for x in data.get("action_history", [])])
    add_table_sheet("Status History",
        ["Date", "From Status", "To Status", "Remarks", "Changed By"],
        [(x.get("created_at"), x.get("old_status"), x.get("new_status"), x.get("remarks"), x.get("changed_by_id"))
         for x in data.get("status_history", [])])
    add_table_sheet("Action Attachments",
        ["Action No.", "File Name", "Caption", "Uploaded By", "Uploaded Date", "Size (bytes)"],
        [(x.get("action_no"), x.get("file_name"), x.get("caption"), x.get("uploaded_by_name"), x.get("created_at"), x.get("size_bytes"))
         for x in data.get("action_evidence", [])])
    add_table_sheet("Discovered Causes",
        ["Cause", "Source Action", "Status", "Evidence Reference", "Verification Method", "Review Remarks", "Reported By", "Reviewed By"],
        [(x.get("cause_description"), x.get("action_no"), x.get("status"), x.get("evidence_reference"),
          x.get("verification_method"), x.get("review_remarks"), x.get("reported_by_name"), x.get("reviewed_by_name"))
         for x in data.get("discovered_causes", [])])
    add_table_sheet("Recurrences",
        ["Rejection ID", "Date", "Part", "Phenomenon", "Rejected Qty", "Classification",
         "Recurrence Reason", "Containment", "New Evidence", "Previous Action Status",
         "Previous Verification", "Quality Review", "Related FTA"],
        [(x.get("rejection_id"), x.get("rejection_date"), x.get("part_code"), x.get("phenomenon"),
          x.get("reject_qty"), x.get("classification"), x.get("recurrence_reason"),
          x.get("containment_action"), x.get("new_evidence"), x.get("previous_action_status"),
          x.get("previous_verification_result"), x.get("review_remarks"), x.get("related_investigation_no"))
         for x in data.get("recurrences", [])])
    output = BytesIO()
    wb.save(output)
    return output.getvalue()


@router.get("/investigations/{investigation_id}/export.xlsx")
def export_investigation_excel(investigation_id: int, db: Session = Depends(get_db),
                               user: User = Depends(get_current_user)):
    _assert_investigation_access(db, investigation_id, user)
    row = db.execute(text("SELECT * FROM fta_investigations WHERE id=:id"),
                     {"id": investigation_id}).mappings().one()
    data = _investigation(row, db)
    content = _fta_excel_workbook(data)
    safe_no = re.sub(r"[^A-Za-z0-9_-]+", "_", str(data.get("investigation_no") or investigation_id))
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="FTA_{safe_no}.xlsx"'},
    )


@router.patch("/investigations/{investigation_id}")
def update_investigation(investigation_id: int, payload: InvestigationUpdate,
                         db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _role(user, WRITE_ROLES)
    row = _assert_investigation_access(db, investigation_id, user, WRITE_ROLES)
    if row["status"] not in {"OPEN", "IN_PROGRESS"}:
        raise HTTPException(409, "Only open investigations can be edited")
    data = payload.model_dump(exclude_unset=True)
    if _role_name(user) == "PRODUCTION" and "owner_id" in data and data["owner_id"] not in {None, user.id}:
        raise HTTPException(403, "Production users cannot reassign investigation ownership")
    if "owner_id" in data and data["owner_id"] and not db.execute(
        text("SELECT id FROM users WHERE id=:id AND is_active=true"), {"id": data["owner_id"]}
    ).first():
        raise HTTPException(422, "Selected investigation owner is not active")
    if data:
        data["id"] = investigation_id
        data["now"] = datetime.utcnow()
        assignments = ", ".join(f"{key}=:{key}" for key in data if key not in {"id", "now"})
        db.execute(text(f"UPDATE fta_investigations SET {assignments}, updated_at=:now WHERE id=:id"), data)
    db.commit()
    result = db.execute(text("SELECT * FROM fta_investigations WHERE id=:id"), {"id": investigation_id}).mappings().one()
    return _investigation(result, db)


@router.put("/investigations/{investigation_id}/findings/{node_id}")
def update_finding(investigation_id: int, node_id: str, payload: FindingUpdate,
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _role(user, WRITE_ROLES)
    if payload.investigation_status not in NODE_STATUSES:
        raise HTTPException(422, "Invalid investigation status")
    investigation = _assert_investigation_access(db, investigation_id, user, WRITE_ROLES)
    if investigation["status"] not in {"OPEN", "IN_PROGRESS"}:
        raise HTTPException(409, "Only open investigations can be edited")
    finding = db.execute(text("""
        SELECT * FROM fta_findings WHERE investigation_id=:investigation_id AND node_id=:node_id
    """), {"investigation_id": investigation_id, "node_id": node_id}).mappings().first()
    if not finding:
        raise HTTPException(404, "Fault-tree node not found in this investigation")
    _validate_cause_classification(finding["node_type"], payload)
    if payload.investigation_status == "NOT_APPLICABLE" and not (payload.observation or "").strip():
        raise HTTPException(422, "Record why this cause is not applicable")
    if payload.investigation_status == "CONFIRMED" and not (payload.verification_method or "").strip():
        raise HTTPException(422, "Enter the verification method before confirming a cause")
    if payload.investigation_status == "CONFIRMED":
        evidence_count = db.execute(text("""
            SELECT COUNT(*) FROM fta_evidence
            WHERE investigation_id=:investigation_id AND finding_id=:finding_id
        """), {"investigation_id": investigation_id, "finding_id": finding["id"]}).scalar_one()
        if not evidence_count:
            raise HTTPException(422, "Attach at least one evidence file to this cause before confirming it")
    audit_fields = [
        "node_id", "node_label", "node_type", "investigation_status", "observation",
        "measured_value", "expected_value", "verification_method", "verification_result", "priority",
        "is_root_cause", "is_occurrence_cause", "is_escape_cause",
    ]
    old_snapshot = {key: finding[key] for key in audit_fields}
    new_snapshot = payload.model_dump()
    db.execute(text("""
        INSERT INTO fta_finding_history
        (finding_id, old_snapshot_json, new_snapshot_json, changed_by_id)
        VALUES (:finding_id, :old_snapshot, :new_snapshot, :user_id)
    """), {"finding_id": finding["id"], "old_snapshot": json.dumps(old_snapshot, ensure_ascii=False, default=str),
           "new_snapshot": json.dumps(new_snapshot, ensure_ascii=False, default=str), "user_id": user.id})
    db.execute(text("""
        UPDATE fta_findings SET investigation_status=:status, priority=:priority, observation=:observation,
          measured_value=:measured, expected_value=:expected, verification_method=:method,
          verification_result=:result, is_root_cause=:root, is_occurrence_cause=:occurrence,
          is_escape_cause=:escape, updated_by_id=:user_id, updated_at=:now
        WHERE id=:id
    """), {
        "status": payload.investigation_status, "priority": payload.priority, "observation": payload.observation,
        "measured": payload.measured_value, "expected": payload.expected_value,
        "method": payload.verification_method, "result": payload.verification_result,
        "root": payload.is_root_cause, "occurrence": payload.is_occurrence_cause,
        "escape": payload.is_escape_cause, "user_id": user.id, "now": datetime.utcnow(),
        "id": finding["id"],
    })
    db.execute(text("""
        UPDATE fta_investigations SET status='IN_PROGRESS', updated_at=:now
        WHERE id=:id AND status='OPEN'
    """), {"now": datetime.utcnow(), "id": investigation_id})
    if investigation["status"] == "OPEN":
        db.execute(text("""
            INSERT INTO fta_status_history (investigation_id, old_status, new_status, remarks, changed_by_id)
            VALUES (:id, 'OPEN', 'IN_PROGRESS', 'Investigation findings updated.', :user_id)
        """), {"id": investigation_id, "user_id": user.id})
    db.commit()
    row = db.execute(text("SELECT * FROM fta_investigations WHERE id=:id"), {"id": investigation_id}).mappings().one()
    return _investigation(row, db)



@router.get("/investigations/{investigation_id}/evidence")
def list_evidence(investigation_id: int, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    _assert_investigation_access(db, investigation_id, user)
    rows = db.execute(text("""
        SELECT id, finding_id, file_name, mime_type, size_bytes, caption, uploaded_by_id, created_at
        FROM fta_evidence WHERE investigation_id=:id ORDER BY created_at, id
    """), {"id": investigation_id}).mappings().all()
    return [dict(x) for x in rows]


@router.post("/investigations/{investigation_id}/evidence", status_code=201)
def upload_evidence(investigation_id: int, file: UploadFile = File(...),
                    finding_id: int | None = Form(default=None),
                    caption: str | None = Form(default=None),
                    db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    investigation = _assert_investigation_access(db, investigation_id, user, WRITE_ROLES)
    if investigation["status"] not in {"OPEN", "IN_PROGRESS"}:
        raise HTTPException(409, "Evidence can only be added to an open investigation")
    if finding_id and not db.execute(text("""
        SELECT id FROM fta_findings WHERE id=:id AND investigation_id=:investigation_id
    """), {"id": finding_id, "investigation_id": investigation_id}).first():
        raise HTTPException(422, "Selected finding does not belong to this investigation")
    evidence_count = db.execute(text("SELECT COUNT(*) FROM fta_evidence WHERE investigation_id=:id"),
                                {"id": investigation_id}).scalar_one()
    if evidence_count >= MAX_FTA_EVIDENCE_FILES:
        raise HTTPException(409, f"An investigation can have at most {MAX_FTA_EVIDENCE_FILES} evidence files")
    original = safe_original_name(file.filename, "fta-evidence")
    extension = Path(original).suffix.lower()
    if extension not in FTA_EVIDENCE_EXTENSIONS:
        raise HTTPException(415, "Unsupported evidence file type")
    clean_caption = (caption or "").strip() or None
    if clean_caption and len(clean_caption) > 500:
        raise HTTPException(422, "Evidence caption cannot exceed 500 characters")
    stored_name = f"{uuid.uuid4().hex}{extension}"
    relative = Path("fta-evidence") / str(investigation_id) / stored_name
    settings = get_settings()
    target = safe_path(settings.attachments_dir, relative)
    try:
        size, sha = save_limited_stream(file.file, target, MAX_FTA_EVIDENCE_BYTES)
        mime_type = validate_attachment_file(
            target, original, FTA_EVIDENCE_EXTENSIONS,
            settings.office_max_uncompressed_mb * 1024 * 1024,
        )
    except UploadSecurityError as exc:
        target.unlink(missing_ok=True)
        raise HTTPException(exc.status_code, exc.detail) from exc
    duplicate = db.execute(text("""
        SELECT id, finding_id, file_name, mime_type, size_bytes, caption, uploaded_by_id, created_at
        FROM fta_evidence
        WHERE investigation_id=:id AND sha256=:sha
          AND ((finding_id IS NULL AND :finding_id IS NULL) OR finding_id=:finding_id)
    """), {"id": investigation_id, "sha": sha, "finding_id": finding_id}).mappings().first()
    if duplicate:
        target.unlink(missing_ok=True)
        return dict(duplicate)
    try:
        row = db.execute(text("""
            INSERT INTO fta_evidence
            (investigation_id, finding_id, file_name, stored_name, relative_path, mime_type,
             size_bytes, sha256, caption, uploaded_by_id)
            VALUES (:investigation_id, :finding_id, :file_name, :stored_name, :relative_path,
                    :mime_type, :size_bytes, :sha256, :caption, :user_id)
            RETURNING id, finding_id, file_name, mime_type, size_bytes, caption, uploaded_by_id, created_at
        """), {"investigation_id": investigation_id, "finding_id": finding_id, "file_name": original,
               "stored_name": stored_name, "relative_path": str(relative).replace(chr(92), "/"),
               "mime_type": mime_type, "size_bytes": size, "sha256": sha, "caption": clean_caption,
               "user_id": user.id}).mappings().one()
        db.commit()
        return dict(row)
    except Exception:
        db.rollback()
        target.unlink(missing_ok=True)
        raise


@router.get("/investigations/{investigation_id}/evidence/{evidence_id}")
def download_evidence(investigation_id: int, evidence_id: int, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    _assert_investigation_access(db, investigation_id, user)
    row = db.execute(text("""
        SELECT relative_path, file_name, mime_type FROM fta_evidence
        WHERE id=:evidence_id AND investigation_id=:investigation_id
    """), {"evidence_id": evidence_id, "investigation_id": investigation_id}).mappings().first()
    if not row:
        raise HTTPException(404, "FTA evidence not found")
    target = safe_path(get_settings().attachments_dir, row["relative_path"])
    if not target.is_file():
        raise HTTPException(404, "FTA evidence file is missing from protected storage")
    return FileResponse(target, media_type=row["mime_type"] or "application/octet-stream",
                        filename=row["file_name"], content_disposition_type="attachment")


@router.post("/investigations/{investigation_id}/actions", status_code=201)
def link_action(investigation_id: int, payload: ActionLinkCreate,
                db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    investigation = _assert_investigation_access(db, investigation_id, user, WRITE_ROLES)
    if investigation["status"] not in {"OPEN", "IN_PROGRESS"}:
        raise HTTPException(409, "Actions can only be linked to an open investigation")
    action = db.execute(text("SELECT id, owner_id FROM actions WHERE id=:id"), {"id": payload.action_id}).mappings().first()
    if not action:
        raise HTTPException(404, "Existing action not found")
    if _role_name(user) == "PRODUCTION" and action["owner_id"] != user.id:
        raise HTTPException(404, "Existing action not found")
    action_plants = set(db.scalars(text("""
        SELECT plant FROM (
            SELECT p.plant AS plant FROM action_contexts ac
            JOIN products p ON p.id=ac.product_id
            WHERE ac.action_id=:action_id
            UNION
            SELECT m.plant AS plant FROM action_contexts ac
            JOIN machines m ON m.id=ac.machine_id
            WHERE ac.action_id=:action_id
        ) AS action_plant_scope
        WHERE plant IS NOT NULL
    """), {"action_id": payload.action_id}).all())
    _validate_action_plants(investigation["plant"], action_plants)
    if payload.finding_id and not db.execute(text("""
        SELECT id FROM fta_findings WHERE id=:id AND investigation_id=:investigation_id
    """), {"id": payload.finding_id, "investigation_id": investigation_id}).first():
        raise HTTPException(422, "Selected finding does not belong to this investigation")
    try:
        db.execute(text("""
            INSERT INTO fta_action_links (investigation_id, finding_id, action_id, relationship_type, created_by_id)
            VALUES (:investigation_id, :finding_id, :action_id, :relationship_type, :user_id)
        """), {"investigation_id": investigation_id, "finding_id": payload.finding_id,
               "action_id": payload.action_id, "relationship_type": payload.relationship_type, "user_id": user.id})
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(409, "This action is already linked to the investigation")
    return {"success": True}


@router.post("/investigations/{investigation_id}/actions/create", status_code=201)
def create_fta_action(investigation_id: int, payload: FtaActionCreate,
                      db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Create an action owned by the FTA workflow; do not create a duplicate Why-Why plan."""
    investigation = _assert_investigation_access(db, investigation_id, user, WRITE_ROLES)
    if investigation["status"] not in {"OPEN", "IN_PROGRESS"}:
        raise HTTPException(409, "Actions can only be created for an open investigation")

    record = db.execute(text("""
        SELECT investigation_no, rejection_id, template_snapshot_json, owner_id, machine_id, summary
        FROM fta_investigations WHERE id=:id
    """), {"id": investigation_id}).mappings().one()
    snapshot = _json(record["template_snapshot_json"], {})
    rejection = snapshot.get("rejection") or {}
    raw_date = rejection.get("rejection_date")
    try:
        reference_date = date.fromisoformat(str(raw_date)[:10])
    except (TypeError, ValueError):
        raise HTTPException(422, "The source rejection does not contain a valid reference date")

    if payload.finding_id and not db.execute(text("""
        SELECT id FROM fta_findings WHERE id=:id AND investigation_id=:investigation_id
    """), {"id": payload.finding_id, "investigation_id": investigation_id}).first():
        raise HTTPException(422, "Selected finding does not belong to this investigation")

    count = db.query(Action).count() + 1
    action = Action(
        action_no=f"ACT-{reference_date.year}-{count:05d}",
        reference_date=reference_date,
        problem_category="FTA",
        problem_description=(
            f"FTA {record['investigation_no']}: "
            f"{record['summary'] or 'Machining defect root-cause investigation'}"
        ),
        action_description=payload.action_description.strip(),
        owner_id=record["owner_id"] or user.id,
        action_type="FTA",
        requires_whywhy=False,
    )
    db.add(action)
    db.flush()

    product_id = rejection.get("product_id")
    db.add(ActionContext(
        action_id=action.id,
        context_date=reference_date,
        product_id=int(product_id) if product_id is not None else None,
        machine_id=record["machine_id"],
    ))
    db.add(ActionHistory(
        action_id=action.id,
        changed_by_id=user.id,
        new_status=action.status,
        comment=(
            f"Action created from FTA {record['investigation_no']}. "
            "Root-cause analysis is recorded in the linked FTA; separate Why-Why is not required."
        ),
    ))
    db.execute(text("""
        INSERT INTO fta_action_links (investigation_id, finding_id, action_id, relationship_type, created_by_id)
        VALUES (:investigation_id, :finding_id, :action_id, 'CORRECTIVE', :user_id)
    """), {
        "investigation_id": investigation_id,
        "finding_id": payload.finding_id,
        "action_id": action.id,
        "user_id": user.id,
    })
    db.commit()
    db.refresh(action)

    # Preserve the normal assignment notification for FTA-originated actions.
    if action.owner_id:
        try:
            send_action_chat_notification(
                db,
                action,
                action.owner_id,
                kind="ACTION_ASSIGNED",
                event_key=f"action:{action.id}:ASSIGNED:user:{action.owner_id}",
                message=(
                    "A corrective action from FTA has been assigned to you. "
                    "Update implementation progress and evidence in Action Management. "
                    "The root-cause analysis is recorded in the linked FTA; no separate Why-Why form is required."
                ),
            )
            db.commit()
        except Exception:
            import logging
            db.rollback()
            logging.getLogger(__name__).exception(
                "Unable to send FTA action assignment notification for action %s", action.id
            )

    return {
        "success": True,
        "action": {
            "id": action.id,
            "action_no": action.action_no,
            "status": action.status.value,
            "requires_whywhy": action.requires_whywhy,
            "action_type": action.action_type,
        },
    }


@router.post("/actions/{action_id}/discovered-causes", status_code=201)
def report_discovered_cause(action_id: int, payload: DiscoveredCauseCreate,
                             db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _role(user, WRITE_ROLES)
    linked = db.execute(text("""
        SELECT l.investigation_id, i.status, i.investigation_no, a.owner_id, a.status AS action_status
        FROM fta_action_links l
        JOIN fta_investigations i ON i.id=l.investigation_id
        JOIN actions a ON a.id=l.action_id
        WHERE l.action_id=:action_id
        ORDER BY l.id LIMIT 1
    """), {"action_id": action_id}).mappings().first()
    if not linked:
        raise HTTPException(404, "FTA-linked action not found")
    if _role_name(user) == "PRODUCTION" and linked["owner_id"] != user.id:
        raise HTTPException(404, "FTA-linked action not found")
    if linked["status"] == "CLOSED":
        raise HTTPException(409, "Cannot report a new cause against a closed FTA investigation")
    if linked["action_status"] == "CLOSED":
        raise HTTPException(409, "Cannot report a new cause against a closed action")
    cause = db.execute(text("""
        INSERT INTO fta_discovered_causes
          (investigation_id, action_id, cause_description, evidence_reference, status, reported_by_id)
        VALUES (:investigation_id, :action_id, :description, :evidence, 'PROPOSED', :user_id)
        RETURNING id, investigation_id, action_id, cause_description, evidence_reference, status, reported_by_id, created_at
    """), {"investigation_id": linked["investigation_id"], "action_id": action_id,
           "description": payload.cause_description.strip(),
           "evidence": payload.evidence_reference.strip(),
           "user_id": user.id}).mappings().one()
    db.add(ActionHistory(
        action_id=action_id, changed_by_id=user.id,
        comment=f"New cause reported to FTA {linked['investigation_no']}: {payload.cause_description.strip()}",
    ))
    if linked["status"] == "VERIFIED_PENDING_ACTIONS":
        now = datetime.utcnow()
        db.execute(text("""
            UPDATE fta_investigations
            SET status='IN_PROGRESS', verified_by_id=NULL, verified_at=NULL, updated_at=:now
            WHERE id=:id
        """), {"now": now, "id": linked["investigation_id"]})
        db.execute(text("""
            INSERT INTO fta_status_history
              (investigation_id, old_status, new_status, remarks, changed_by_id)
            VALUES (:id, 'VERIFIED_PENDING_ACTIONS', 'IN_PROGRESS',
                    'Investigation reopened because a new cause was discovered during action implementation.',
                    :user_id)
        """), {"id": linked["investigation_id"], "user_id": user.id})
    db.commit()
    return dict(cause)


@router.post("/discovered-causes/{cause_id}/review")
def review_discovered_cause(cause_id: int, payload: DiscoveredCauseReview,
                            db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _role(user, TEMPLATE_ROLES)
    cause = db.execute(text("""
        SELECT c.*, i.status AS investigation_status
        FROM fta_discovered_causes c
        JOIN fta_investigations i ON i.id=c.investigation_id
        WHERE c.id=:id
    """), {"id": cause_id}).mappings().first()
    if not cause:
        raise HTTPException(404, "Discovered cause not found")
    if cause["investigation_status"] == "CLOSED":
        raise HTTPException(409, "Closed FTA investigations cannot be changed")
    if cause["status"] not in {"PROPOSED", "ACCEPTED"}:
        raise HTTPException(409, "This discovered cause has already been resolved")
    if payload.status == "CONFIRMED" and not (payload.verification_method or "").strip():
        raise HTTPException(422, "A verification method is required to confirm a discovered root cause")
    if payload.status == "CONFIRMED" and not (cause["evidence_reference"] or "").strip():
        raise HTTPException(422, "Evidence reference is required to confirm a discovered root cause")
    db.execute(text("""
        UPDATE fta_discovered_causes
        SET status=:status, review_remarks=:remarks, verification_method=:method,
            reviewed_by_id=:user_id, reviewed_at=:now, updated_at=:now
        WHERE id=:id
    """), {"status": payload.status, "remarks": payload.review_remarks.strip(),
           "method": (payload.verification_method or "").strip() or None,
           "user_id": user.id, "now": datetime.utcnow(), "id": cause_id})
    db.commit()
    return {"success": True, "status": payload.status}


@router.post("/investigations/{investigation_id}/verify")
def verify_investigation(investigation_id: int, payload: VerifyRequest,
                         db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _role(user, {"ADMIN", "QUALITY"})
    row = db.execute(text("SELECT status, template_snapshot_json FROM fta_investigations WHERE id=:id"),
                     {"id": investigation_id}).mappings().first()
    if not row:
        raise HTTPException(404, "FTA investigation not found")
    if row["status"] != "IN_PROGRESS":
        raise HTTPException(409, "Only an in-progress investigation can be submitted for verification")
    required_actions = db.execute(text("""
        SELECT COUNT(*) FROM fta_action_links
        WHERE investigation_id=:id AND relationship_type IN ('CORRECTIVE', 'PREVENTIVE')
    """), {"id": investigation_id}).scalar_one()
    if not required_actions:
        raise HTTPException(422, "Link at least one corrective or preventive action before verification")
    confirmed = db.execute(text("""
        SELECT COUNT(*) FROM fta_findings
        WHERE investigation_id=:id AND investigation_status='CONFIRMED' AND is_root_cause=true
    """), {"id": investigation_id}).scalar_one()
    if not confirmed:
        raise HTTPException(422, "Confirm at least one root cause before verification")
    unverified = db.execute(text("""
        SELECT COUNT(*) FROM fta_findings
        WHERE investigation_id=:id AND investigation_status='CONFIRMED'
          AND (verification_method IS NULL OR trim(verification_method)='')
    """), {"id": investigation_id}).scalar_one()
    if unverified:
        raise HTTPException(422, "Every confirmed cause must have a verification method")
    now = datetime.utcnow()
    db.execute(text("""
        UPDATE fta_investigations SET status='VERIFIED_PENDING_ACTIONS', verified_by_id=:user_id,
          verified_at=:now, updated_at=:now WHERE id=:id
    """), {"user_id": user.id, "now": now, "id": investigation_id})
    db.execute(text("""
        INSERT INTO fta_status_history (investigation_id, old_status, new_status, remarks, changed_by_id)
        VALUES (:id, :old, 'VERIFIED_PENDING_ACTIONS', :remarks, :user_id)
    """), {"id": investigation_id, "old": row["status"], "remarks": payload.remarks, "user_id": user.id})
    db.commit()
    return {"success": True, "status": "VERIFIED_PENDING_ACTIONS"}


@router.post("/investigations/{investigation_id}/close")
def close_investigation(investigation_id: int, payload: CloseRequest,
                        db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _role(user, {"ADMIN", "QUALITY"})
    row = db.execute(text("SELECT status FROM fta_investigations WHERE id=:id"),
                     {"id": investigation_id}).mappings().first()
    if not row:
        raise HTTPException(404, "FTA investigation not found")
    if row["status"] != "VERIFIED_PENDING_ACTIONS":
        raise HTTPException(409, "Investigation must be verified before closure")
    linked_total = db.execute(text("""
        SELECT COUNT(*) FROM fta_action_links
        WHERE investigation_id=:id AND relationship_type IN ('CORRECTIVE', 'PREVENTIVE')
    """), {"id": investigation_id}).scalar_one()
    if not linked_total:
        raise HTTPException(422, "Link at least one corrective or preventive action before closing the investigation")
    linked_open = db.execute(text("""
        SELECT COUNT(*) FROM fta_action_links l JOIN actions a ON a.id=l.action_id
        WHERE l.investigation_id=:id AND a.status <> 'CLOSED'
    """), {"id": investigation_id}).scalar_one()
    if linked_open:
        raise HTTPException(422, "Complete linked corrective actions before closing the investigation")
    unresolved_causes = db.execute(text("""
        SELECT COUNT(*) FROM fta_discovered_causes
        WHERE investigation_id=:id AND status IN ('PROPOSED','ACCEPTED')
    """), {"id": investigation_id}).scalar_one()
    if unresolved_causes:
        raise HTTPException(409, "Resolve every cause discovered during action implementation before closing this investigation.")
    now = datetime.utcnow()
    db.execute(text("""
        UPDATE fta_investigations SET status='CLOSED', closure_remarks=:remarks,
          closed_by_id=:user_id, closed_at=:now, updated_at=:now WHERE id=:id    """), {"remarks": payload.remarks, "user_id": user.id, "now": now, "id": investigation_id})
    db.execute(text("""
        INSERT INTO fta_status_history (investigation_id, old_status, new_status, remarks, changed_by_id)
        VALUES (:id, :old, 'CLOSED', :remarks, :user_id)
    """), {"id": investigation_id, "old": row["status"], "remarks": payload.remarks, "user_id": user.id})
    db.commit()
    return {"success": True, "status": "CLOSED"}



@router.get("/rejection-actions")
def rejection_actions_by_day(from_date: date, to_date: date, plant: str | None = None,
                             product_id: str | None = None, phenomenon_id: str | None = None,
                             operation_id: str | None = None, machine_id: str | None = None,
                             shift: str | None = None, db: Session = Depends(get_db),
                             user: User = Depends(get_current_user)):
    """Return FTA-linked corrective/preventive actions scoped to Quality dashboard filters."""
    _role(user, READ_ROLES)
    if to_date < from_date:
        raise HTTPException(422, "End date must be on or after start date")

    def ids(value: str | None) -> list[int]:
        if not value:
            return []
        try:
            return [int(part.strip()) for part in value.split(",") if part.strip()]
        except ValueError:
            raise HTTPException(422, "Invalid numeric filter")

    product_ids = ids(product_id)
    phenomenon_ids = ids(phenomenon_id)
    operation_ids = ids(operation_id)
    machine_ids = ids(machine_id)
    shifts = [part.strip() for part in (shift or "").split(",") if part.strip()]
    plants = [part.strip() for part in (plant or "").split(",") if part.strip()]

    query = """
        SELECT DISTINCT a.id, a.action_no,
               REGEXP_REPLACE(a.problem_description, '^FTA[[:space:]]+' || i.investigation_no || ':[[:space:]]*', '') AS problem_description,
               a.action_description,
               a.status, a.due_at, a.action_type, a.owner_id, u.full_name AS owner_name,
               CASE WHEN a.status <> 'CLOSED' AND a.due_at IS NOT NULL AND a.due_at::date < CURRENT_DATE
                    THEN CURRENT_DATE - a.due_at::date ELSE 0 END AS overdue_days,
               i.id AS investigation_id, i.investigation_no, i.operation_code,
               q.id AS rejection_id, q.rejection_date AS date, q.shift,
               COALESCE(q.plant, p.plant) AS plant, q.product_id, q.phenomenon_id,
               p.code AS part_code, p.name AS part_name, ph.name AS phenomenon,
               COALESCE(i.machine_id, q.machine_id) AS machine_id, m.name AS machine_name
        FROM fta_action_links l
        JOIN fta_investigations i ON i.id=l.investigation_id
        JOIN actions a ON a.id=l.action_id
        JOIN quality_rejection_daily q ON q.id=i.rejection_id
        JOIN products p ON p.id=q.product_id
        JOIN quality_rejection_phenomena ph ON ph.id=q.phenomenon_id
        LEFT JOIN machines m ON m.id=COALESCE(i.machine_id, q.machine_id)
        LEFT JOIN users u ON u.id=a.owner_id
        WHERE q.rejection_date BETWEEN :from_date AND :to_date
    """
    params: dict[str, Any] = {"from_date": from_date, "to_date": to_date}
    if plants:
        query += " AND COALESCE(q.plant, p.plant) = ANY(:plants)"
        params["plants"] = plants
    if product_ids:
        query += " AND q.product_id = ANY(:product_ids)"
        params["product_ids"] = product_ids
    if phenomenon_ids:
        query += " AND q.phenomenon_id = ANY(:phenomenon_ids)"
        params["phenomenon_ids"] = phenomenon_ids
    if operation_ids:
        query += " AND (q.detection_route_operation_id = ANY(:operation_ids) OR q.responsible_route_operation_id = ANY(:operation_ids))"
        params["operation_ids"] = operation_ids
    if machine_ids:
        query += " AND COALESCE(i.machine_id, q.machine_id) = ANY(:machine_ids)"
        params["machine_ids"] = machine_ids
    if shifts:
        query += " AND q.shift = ANY(:shifts)"
        params["shifts"] = shifts
    if _role_name(user) == "PRODUCTION":
        query += " AND (i.owner_id=:user_id OR i.created_by_id=:user_id)"
        params["user_id"] = user.id
    query += " ORDER BY q.rejection_date, a.id"
    action_rows = [dict(row) for row in db.execute(text(query), params).mappings().all()]

    # A recurrence is a separate quality event. Report it on the date the
    # recurrence was linked (IST), not on the original rejection date.
    recurrence_query = """
        SELECT -r.id AS id, NULL::text AS action_no,
               COALESCE(NULLIF(r.recurrence_reason, ''), NULLIF(i.summary, ''),
                        'FTA recurrence linked') AS problem_description,
               NULL::text AS action_description, r.classification AS status,
               NULL::timestamp AS due_at, 'FTA_RECURRENCE'::text AS action_type,
               i.owner_id, u.full_name AS owner_name, 0 AS overdue_days,
               i.id AS investigation_id, i.investigation_no, i.operation_code,
               q.id AS rejection_id,
               (r.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Kolkata')::date AS date,
               q.shift, COALESCE(q.plant, p.plant) AS plant, q.product_id,
               q.phenomenon_id, p.code AS part_code, p.name AS part_name,
               ph.name AS phenomenon, COALESCE(i.machine_id, q.machine_id) AS machine_id,
               m.name AS machine_name, r.id AS recurrence_id,
               r.classification, 'FTA Recurrence'::text AS source_type,
               ri.investigation_no AS related_investigation_no
        FROM fta_recurrences r
        JOIN fta_investigations i ON i.id=r.original_investigation_id
        JOIN quality_rejection_daily q ON q.id=r.rejection_id
        JOIN products p ON p.id=q.product_id
        JOIN quality_rejection_phenomena ph ON ph.id=q.phenomenon_id
        LEFT JOIN machines m ON m.id=COALESCE(i.machine_id, q.machine_id)
        LEFT JOIN users u ON u.id=i.owner_id
        LEFT JOIN fta_investigations ri ON ri.id=r.related_investigation_id
        WHERE (r.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Kolkata')::date
              BETWEEN :from_date AND :to_date
    """
    if plants:
        recurrence_query += " AND COALESCE(q.plant, p.plant) = ANY(:plants)"
    if product_ids:
        recurrence_query += " AND q.product_id = ANY(:product_ids)"
    if phenomenon_ids:
        recurrence_query += " AND q.phenomenon_id = ANY(:phenomenon_ids)"
    if operation_ids:
        recurrence_query += " AND (q.detection_route_operation_id = ANY(:operation_ids) OR q.responsible_route_operation_id = ANY(:operation_ids))"
    if machine_ids:
        recurrence_query += " AND COALESCE(i.machine_id, q.machine_id) = ANY(:machine_ids)"
    if shifts:
        recurrence_query += " AND q.shift = ANY(:shifts)"
    if _role_name(user) == "PRODUCTION":
        recurrence_query += " AND (i.owner_id=:user_id OR i.created_by_id=:user_id)"
    recurrence_query += " ORDER BY date, r.id"
    recurrence_rows = [dict(row) for row in db.execute(text(recurrence_query), params).mappings().all()]
    return action_rows + recurrence_rows


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _role(user, READ_ROLES)
    production_scope = " AND (i.owner_id=:user_id OR i.created_by_id=:user_id)" if _role_name(user) == "PRODUCTION" else ""
    params = {"user_id": user.id} if production_scope else {}
    counts = db.execute(text(f"""
        SELECT COUNT(*) AS total,
          SUM(CASE WHEN i.status IN ('OPEN','IN_PROGRESS') THEN 1 ELSE 0 END) AS open,
          SUM(CASE WHEN i.status='VERIFIED_PENDING_ACTIONS' THEN 1 ELSE 0 END) AS verified_pending_actions,
          SUM(CASE WHEN i.status='CLOSED' THEN 1 ELSE 0 END) AS closed
        FROM fta_investigations i WHERE 1=1 {production_scope}
    """), params).mappings().one()
    defects = db.execute(text(f"""
        SELECT d.name AS defect, COUNT(*) AS investigations
        FROM fta_investigations i JOIN fta_templates t ON t.id=i.template_id
        JOIN fta_phenomenon_code_map fm ON fm.legacy_defect_code=t.defect_code
        JOIN quality_rejection_phenomena d ON d.id=fm.phenomenon_id
        WHERE 1=1 {production_scope}
        GROUP BY d.name ORDER BY investigations DESC, d.name LIMIT 5
    """), params).mappings().all()
    causes = db.execute(text(f"""
        SELECT f.node_label AS cause, COUNT(*) AS occurrences
        FROM fta_findings f JOIN fta_investigations i ON i.id=f.investigation_id
        WHERE f.is_root_cause=true AND f.investigation_status='CONFIRMED' {production_scope}
        GROUP BY f.node_label ORDER BY occurrences DESC, f.node_label LIMIT 5
    """), params).mappings().all()
    recurrence_counts = db.execute(text(f"""
        SELECT COUNT(*) AS total,
          COALESCE(SUM(CASE WHEN r.classification='PENDING_REVIEW' THEN 1 ELSE 0 END),0) AS pending_review,
          COALESCE(SUM(CASE WHEN r.classification='SAME_ROOT_CAUSE' THEN 1 ELSE 0 END),0) AS same_root_cause,
          COALESCE(SUM(CASE WHEN r.classification='DIFFERENT_ROOT_CAUSE' THEN 1 ELSE 0 END),0) AS different_root_cause,
          COALESCE(SUM(CASE WHEN r.classification='UNRELATED' THEN 1 ELSE 0 END),0) AS unrelated
        FROM fta_recurrences r
        JOIN fta_investigations i ON i.id=r.original_investigation_id
        WHERE 1=1 {production_scope}
    """), params).mappings().one()
    return {"counts": dict(counts), "recurrence_counts": dict(recurrence_counts),
            "top_defects": [dict(x) for x in defects],
            "top_verified_causes": [dict(x) for x in causes]}



# ---------------------------------------------------------------------------
# FTA recurrence management. Recurrences are separate rejection events linked
# to the original investigation; original findings/actions are never replaced.
# ---------------------------------------------------------------------------

@router.get("/recurrence-candidates/{rejection_id}")
def recurrence_candidates(rejection_id: int, db: Session = Depends(get_db),
                         user: User = Depends(get_current_user)):
    _role(user, READ_ROLES)
    rejection = db.execute(text("""
        SELECT q.id, q.product_id, q.phenomenon_id, q.machine_id,
               COALESCE(q.plant,p.plant) AS plant
        FROM quality_rejection_daily q
        JOIN products p ON p.id=q.product_id
        WHERE q.id=:id
    """), {"id": rejection_id}).mappings().first()
    if not rejection:
        raise HTTPException(404, "Quality Rejection record not found")
    rows = db.execute(text("""
        SELECT i.id AS investigation_id, i.investigation_no, i.status,
               i.rejection_id AS original_rejection_id, oq.rejection_date AS original_rejection_date,
               p.code AS part_code, p.name AS part_name, ph.name AS phenomenon,
               COALESCE(i.machine_id, oq.machine_id) AS machine_id,
               om.name AS machine_name,
               COALESCE((SELECT string_agg(DISTINCT a.status::text, ', ')
                         FROM fta_action_links al JOIN actions a ON a.id=al.action_id
                         WHERE al.investigation_id=i.id), 'NO LINKED ACTION') AS previous_action_status,
               (SELECT string_agg(DISTINCT f.verification_result, '; ')
                FROM fta_findings f
                WHERE f.investigation_id=i.id AND f.is_root_cause=true
                  AND f.investigation_status='CONFIRMED'
                  AND NULLIF(f.verification_result,'') IS NOT NULL) AS previous_verification_result
        FROM fta_investigations i
        JOIN quality_rejection_daily oq ON oq.id=i.rejection_id
        JOIN products p ON p.id=oq.product_id
        JOIN quality_rejection_phenomena ph ON ph.id=oq.phenomenon_id
        LEFT JOIN machines om ON om.id=COALESCE(i.machine_id,oq.machine_id)
        WHERE oq.product_id=:product_id
          AND oq.phenomenon_id=:phenomenon_id
          AND i.rejection_id<>:rejection_id
          AND (:plant IS NULL OR COALESCE(oq.plant,p.plant)=:plant)
          AND (:machine_id IS NULL OR COALESCE(i.machine_id,oq.machine_id)=:machine_id)
        ORDER BY oq.rejection_date DESC, i.id DESC
        LIMIT 50
    """), {"product_id": rejection["product_id"], "phenomenon_id": rejection["phenomenon_id"],
           "rejection_id": rejection_id, "plant": rejection["plant"],
           "machine_id": rejection["machine_id"]}).mappings().all()
    visible = []
    for row in rows:
        if _role_name(user) != "PRODUCTION" or db.execute(text("""
            SELECT 1 FROM fta_investigations
            WHERE id=:id AND (owner_id=:uid OR created_by_id=:uid)
        """), {"id": row["investigation_id"], "uid": user.id}).first():
            visible.append(dict(row))
    return visible



@router.get("/investigations/{investigation_id}/recurrence-suggestions")
def recurrence_suggestions(investigation_id: int, db: Session = Depends(get_db),
                           user: User = Depends(get_current_user)):
    """Automatically find later Quality rejection events for the same defect."""
    _assert_investigation_access(db, investigation_id, user)
    original = db.execute(text("""
        SELECT i.id, i.investigation_no, i.operation_code, i.created_at AS fta_created_at,
               q.id AS rejection_id, q.rejection_date, q.product_id, q.phenomenon_id,
               COALESCE(q.plant,p.plant) AS plant, q.machine_id,
               p.code AS part_code, ph.name AS phenomenon_name,
               m.name AS machine_name
        FROM fta_investigations i
        JOIN quality_rejection_daily q ON q.id=i.rejection_id
        JOIN products p ON p.id=q.product_id
        JOIN quality_rejection_phenomena ph ON ph.id=q.phenomenon_id
        LEFT JOIN machines m ON m.id=COALESCE(i.machine_id,q.machine_id)
        WHERE i.id=:id
    """), {"id": investigation_id}).mappings().first()
    if not original:
        raise HTTPException(404, "FTA investigation not found")

    later = db.execute(text("""
        SELECT q.id AS rejection_id, q.rejection_date, q.shift, q.reject_qty,
               q.remark, COALESCE(q.plant,p.plant) AS plant, q.machine_id,
               p.code AS part_code, p.name AS part_name, m.name AS machine_name
        FROM quality_rejection_daily q
        JOIN products p ON p.id=q.product_id
        LEFT JOIN machines m ON m.id=q.machine_id
        WHERE q.phenomenon_id=:phenomenon_id
          AND (q.rejection_date > :original_date
               OR (q.rejection_date=:original_date AND q.id>:original_rejection_id))
          AND NOT EXISTS (
              SELECT 1 FROM fta_investigations fi WHERE fi.rejection_id=q.id
          )
          AND NOT EXISTS (
              SELECT 1 FROM fta_recurrences fr WHERE fr.rejection_id=q.id
          )
          -- A recurrence belongs to the most recent prior FTA for this same
          -- part and defect, not to every older investigation in its history.
          AND NOT EXISTS (
              SELECT 1
              FROM fta_investigations newer_i
              JOIN quality_rejection_daily newer_q ON newer_q.id=newer_i.rejection_id
              WHERE newer_q.product_id=:original_product_id
                AND newer_q.phenomenon_id=:phenomenon_id
                AND newer_i.id<>:original_investigation_id
                AND (
                    newer_q.rejection_date > :original_date
                    OR (newer_q.rejection_date=:original_date
                        AND newer_q.id>:original_rejection_id)
                )
                AND (
                    newer_q.rejection_date < q.rejection_date
                    OR (newer_q.rejection_date=q.rejection_date AND newer_q.id<q.id)
                )
          )
        ORDER BY q.rejection_date DESC, q.id DESC
        LIMIT 100
    """), {"phenomenon_id": original["phenomenon_id"],
           "original_date": original["rejection_date"],
           "original_rejection_id": original["rejection_id"],
           "original_product_id": original["product_id"],
           "original_investigation_id": investigation_id}).mappings().all()

    suggestions = []
    for item in later:
        # A rejection recorded before the original investigation was opened
        # is historical context, not a recurrence after that FTA.
        if original["fta_created_at"] and item["rejection_date"] < original["fta_created_at"].date():
            continue
        row = dict(item)
        row["same_part"] = row["part_code"] == original["part_code"]
        row["same_plant"] = bool(row["plant"] and original["plant"] and row["plant"] == original["plant"])
        row["same_machine"] = bool(row["machine_id"] and original["machine_id"]
                                   and row["machine_id"] == original["machine_id"])
        row["days_after_original"] = (
            (row["rejection_date"] - original["rejection_date"]).days
            if row["rejection_date"] and original["rejection_date"] else None
        )
        suggestions.append(row)

    return {
        "original_investigation_id": investigation_id,
        "original_investigation_no": original["investigation_no"],
        "original_rejection_id": original["rejection_id"],
        "original_rejection_date": original["rejection_date"],
        "original_fta_date": original["fta_created_at"],
        "phenomenon_id": original["phenomenon_id"],
        "phenomenon_name": original["phenomenon_name"],
        "last_matching_rejection_date": suggestions[0]["rejection_date"] if suggestions else None,
        "suggestion_count": len(suggestions),
        "suggestions": suggestions,
    }


@router.get("/investigations/{investigation_id}/recurrences")
def list_recurrences(investigation_id: int, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    _assert_investigation_access(db, investigation_id, user)
    rows = db.execute(text("""
        SELECT r.id, r.original_investigation_id, r.rejection_id, r.classification,
               r.same_root_cause, r.recurrence_reason, r.containment_action, r.new_evidence,
               r.previous_action_status, r.previous_verification_result, r.review_remarks,
               r.reviewed_by_id, r.reviewed_at, r.created_by_id, r.created_at,
               r.related_investigation_id, ri.investigation_no AS related_investigation_no,
               q.rejection_date, q.reject_qty, p.code AS part_code, p.name AS part_name,
               ph.name AS phenomenon, m.name AS machine_name
        FROM fta_recurrences r
        JOIN quality_rejection_daily q ON q.id=r.rejection_id
        JOIN products p ON p.id=q.product_id
        JOIN quality_rejection_phenomena ph ON ph.id=q.phenomenon_id
        LEFT JOIN machines m ON m.id=q.machine_id
        LEFT JOIN fta_investigations ri ON ri.id=r.related_investigation_id
        WHERE r.original_investigation_id=:id
        ORDER BY q.rejection_date DESC, r.id DESC
    """), {"id": investigation_id}).mappings().all()
    return [dict(row) for row in rows]


class RecurrenceCreate(BaseModel):
    rejection_id: int = Field(gt=0)
    recurrence_reason: str = Field(min_length=5, max_length=8000)
    containment_action: str | None = Field(default=None, max_length=4000)
    new_evidence: str | None = Field(default=None, max_length=8000)


class RecurrenceReview(BaseModel):
    classification: str = Field(pattern="^(SAME_ROOT_CAUSE|DIFFERENT_ROOT_CAUSE|UNRELATED)$")
    review_remarks: str = Field(min_length=5, max_length=4000)


@router.post("/investigations/{investigation_id}/recurrences", status_code=201)
def create_recurrence(investigation_id: int, payload: RecurrenceCreate,
                      db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _assert_investigation_access(db, investigation_id, user, WRITE_ROLES)
    rejection_id = payload.rejection_id
    reason = payload.recurrence_reason.strip()
    original = db.execute(text("""
        SELECT i.id, i.rejection_id, oq.product_id, oq.phenomenon_id
        FROM fta_investigations i
        JOIN quality_rejection_daily oq ON oq.id=i.rejection_id
        WHERE i.id=:id
    """), {"id": investigation_id}).mappings().first()
    new_rejection = db.execute(text("""
        SELECT id, product_id, phenomenon_id FROM quality_rejection_daily WHERE id=:id
    """), {"id": rejection_id}).mappings().first()
    if not new_rejection:
        raise HTTPException(404, "New Quality Rejection record not found")
    if rejection_id == original["rejection_id"]:
        raise HTTPException(422, "The original rejection cannot be linked as its own recurrence")
    if (new_rejection["product_id"], new_rejection["phenomenon_id"]) != (
        original["product_id"], original["phenomenon_id"]
    ):
        raise HTTPException(422, "A recurrence must match the original part and shared phenomenon")
    # Initial linkage is always pending. Quality owns the final classification.
    classification = "PENDING_REVIEW"
    already_primary = db.execute(text("""
        SELECT 1 FROM fta_investigations WHERE rejection_id=:rejection_id
    """), {"rejection_id": rejection_id}).first()
    if already_primary:
        raise HTTPException(409, "This rejection already has a primary FTA investigation; it cannot be linked again as a recurrence")
    already_recurrence = db.execute(text("""
        SELECT 1 FROM fta_recurrences WHERE rejection_id=:rejection_id
    """), {"rejection_id": rejection_id}).first()
    if already_recurrence:
        raise HTTPException(409, "This rejection is already linked to an FTA recurrence")
    previous = db.execute(text("""
        SELECT string_agg(DISTINCT a.status::text, ', ') AS action_status
        FROM fta_action_links l JOIN actions a ON a.id=l.action_id
        WHERE l.investigation_id=:id
    """), {"id": investigation_id}).mappings().one()
    verification = db.execute(text("""
        SELECT string_agg(DISTINCT verification_result, '; ')
        FROM fta_findings
        WHERE investigation_id=:id AND is_root_cause=true
          AND investigation_status='CONFIRMED'
          AND NULLIF(verification_result,'') IS NOT NULL
    """), {"id": investigation_id}).scalar()
    try:
        row = db.execute(text("""
            INSERT INTO fta_recurrences
              (original_investigation_id,rejection_id,classification,same_root_cause,
               recurrence_reason,containment_action,new_evidence,previous_action_status,
               previous_verification_result,created_by_id)
            VALUES (:investigation_id,:rejection_id,:classification,:same_root_cause,
                    :reason,:containment,:evidence,:action_status,:verification,:user_id)
            RETURNING id
        """), {
            "investigation_id": investigation_id, "rejection_id": rejection_id,
            "classification": classification,
            "same_root_cause": True if classification == "SAME_ROOT_CAUSE" else (
                False if classification == "DIFFERENT_ROOT_CAUSE" else None),
            "reason": reason, "containment": (payload.containment_action or "").strip() or None,
            "evidence": (payload.new_evidence or "").strip() or None,
            "action_status": previous["action_status"], "verification": verification,
            "user_id": user.id,
        }).mappings().one()
        db.commit()
        return {"id": row["id"], "original_investigation_id": investigation_id,
                "rejection_id": rejection_id, "classification": classification}
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "This Quality Rejection is already linked to an FTA recurrence") from exc


@router.patch("/recurrences/{recurrence_id}/review")
def review_recurrence(recurrence_id: int, payload: RecurrenceReview,
                      db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _role(user, TEMPLATE_ROLES)
    row = db.execute(text("""
        SELECT id, original_investigation_id FROM fta_recurrences WHERE id=:id
    """), {"id": recurrence_id}).mappings().first()
    if not row:
        raise HTTPException(404, "FTA recurrence record not found")
    classification = payload.classification
    remarks = payload.review_remarks.strip()
    db.execute(text("""
        UPDATE fta_recurrences
        SET classification=:classification,
            same_root_cause=:same_root_cause,
            review_remarks=:remarks,
            reviewed_by_id=:user_id,
            reviewed_at=now()
        WHERE id=:id
    """), {"classification": classification,
           "same_root_cause": classification == "SAME_ROOT_CAUSE",
           "remarks": remarks, "user_id": user.id, "id": recurrence_id})
    db.commit()
    return {"success": True, "id": recurrence_id, "classification": classification}


class RelatedInvestigationCreate(BaseModel):
    template_id: int = Field(gt=0)
    owner_id: int | None = Field(default=None, gt=0)
    summary: str | None = Field(default=None, max_length=4000)


@router.post("/recurrences/{recurrence_id}/related-investigation", status_code=201)
def create_related_investigation(recurrence_id: int, payload: RelatedInvestigationCreate,
                                 db: Session = Depends(get_db),
                                 user: User = Depends(get_current_user)):
    _role(user, WRITE_ROLES)
    rec = db.execute(text("""
        SELECT r.id, r.original_investigation_id, r.rejection_id, r.classification,
               r.related_investigation_id, oi.investigation_no AS original_investigation_no,
               oq.plant AS original_plant
        FROM fta_recurrences r
        JOIN fta_investigations oi ON oi.id=r.original_investigation_id
        LEFT JOIN quality_rejection_daily oq ON oq.id=oi.rejection_id
        WHERE r.id=:id
        FOR UPDATE OF r
    """), {"id": recurrence_id}).mappings().first()
    if not rec:
        raise HTTPException(404, "FTA recurrence record not found")
    _assert_investigation_access(db, rec["original_investigation_id"], user, WRITE_ROLES)
    if rec["classification"] != "DIFFERENT_ROOT_CAUSE":
        raise HTTPException(409, "Quality must classify this recurrence as a different root cause first")
    if rec["related_investigation_id"]:
        raise HTTPException(409, "A related investigation has already been created")
    rejection = db.execute(text("""
        SELECT q.id, COALESCE(q.plant,p.plant) AS plant, q.machine_id, q.product_id,
               q.phenomenon_id, q.rejection_date, q.shift, q.reject_qty, q.remark,
               p.code AS part_code, p.name AS part_name, ph.name AS rejection_phenomenon
        FROM quality_rejection_daily q
        JOIN products p ON p.id=q.product_id
        JOIN quality_rejection_phenomena ph ON ph.id=q.phenomenon_id
        WHERE q.id=:id
    """), {"id": rec["rejection_id"]}).mappings().first()
    if not rejection:
        raise HTTPException(404, "Linked Quality Rejection record not found")
    template = db.execute(text("""
        SELECT t.id, t.code, t.name, t.operation_code, t.defect_code,
               t.version, t.tree_json
        FROM fta_templates t
        JOIN fta_phenomenon_code_map fm ON fm.legacy_defect_code=t.defect_code
        WHERE t.id=:id AND t.status='PUBLISHED'
          AND fm.phenomenon_id=:phenomenon_id
    """), {"id": payload.template_id, "phenomenon_id": rejection["phenomenon_id"]}).mappings().first()
    if not template:
        raise HTTPException(422, "Select a published template mapped to this rejection phenomenon")
    latest = db.execute(text("""
        SELECT MAX(version) FROM fta_templates WHERE code=:code AND status='PUBLISHED'
    """), {"code": template["code"]}).scalar_one()
    if template["version"] != latest:
        raise HTTPException(409, "Template revision is no longer current; refresh and select the latest")
    machine_id = rejection["machine_id"]
    if machine_id:
        machine = db.execute(text("SELECT id, plant FROM machines WHERE id=:id AND is_active=true"),
                             {"id": machine_id}).mappings().first()
        if not machine:
            machine_id = None
        elif rejection["plant"] and machine["plant"] and machine["plant"] != rejection["plant"]:
            raise HTTPException(422, "The rejection machine belongs to a different plant")
    if _role_name(user) == "PRODUCTION" and payload.owner_id not in {None, user.id}:
        raise HTTPException(403, "Production users can assign an investigation only to themselves")
    owner_id = payload.owner_id or user.id
    if not db.execute(text("SELECT id FROM users WHERE id=:id AND is_active=true"),
                      {"id": owner_id}).first():
        raise HTTPException(422, "Selected investigation owner is not active")
    tree = _json(template["tree_json"], {})
    snapshot = {
        "template_id": template["id"], "template_code": template["code"],
        "template_name": template["name"], "template_version": template["version"],
        "operation_code": template["operation_code"], "defect_code": template["defect_code"],
        "rejection": {k: str(v) if v is not None else None for k, v in dict(rejection).items()},
        "related_to_investigation_id": rec["original_investigation_id"],
        "related_to_investigation_no": rec["original_investigation_no"],
        "recurrence_id": recurrence_id, "tree": tree,
    }
    now = datetime.utcnow()
    try:
        new_id = db.execute(text("""
            INSERT INTO fta_investigations
              (investigation_no,rejection_id,template_id,template_version,template_snapshot_json,
               plant,machine_id,operation_code,summary,status,owner_id,created_by_id,created_at,updated_at)
            VALUES ('PENDING',:rejection_id,:template_id,:version,:snapshot,
                    :plant,:machine_id,:operation_code,:summary,'OPEN',:owner_id,:user_id,:now,:now)
            RETURNING id
        """), {
            "rejection_id": rec["rejection_id"], "template_id": template["id"],
            "version": template["version"], "snapshot": json.dumps(snapshot, ensure_ascii=False, default=str),
            "plant": rejection["plant"], "machine_id": machine_id,
            "operation_code": template["operation_code"], "summary": payload.summary,
            "owner_id": owner_id, "user_id": user.id, "now": now,
        }).scalar_one()
        number = f"FTA-{now.year}-{new_id:05d}"
        db.execute(text("UPDATE fta_investigations SET investigation_no=:number WHERE id=:id"),
                   {"number": number, "id": new_id})
        nodes: list[dict] = []
        _flatten_nodes(tree, nodes)
        for node in nodes:
            db.execute(text("""
                INSERT INTO fta_findings
                  (investigation_id,node_id,node_label,node_type,investigation_status,updated_by_id)
                VALUES (:investigation_id,:node_id,:node_label,:node_type,'NOT_INVESTIGATED',:user_id)
            """), {**node, "investigation_id": new_id, "user_id": user.id})
        db.execute(text("""
            INSERT INTO fta_status_history
              (investigation_id,old_status,new_status,remarks,changed_by_id)
            VALUES (:id,NULL,'OPEN',:remarks,:user_id)
        """), {"id": new_id, "remarks": f"Separate investigation for different root cause; related to recurrence {recurrence_id} and original FTA {rec['original_investigation_id']}.", "user_id": user.id})
        linked = db.execute(text("""
            UPDATE fta_recurrences SET related_investigation_id=:new_id
            WHERE id=:id AND related_investigation_id IS NULL
        """), {"new_id": new_id, "id": recurrence_id})
        if linked.rowcount != 1:
            db.rollback()
            raise HTTPException(409, "A related investigation was linked concurrently; refresh the FTA")
        db.commit()
        return {"id": new_id, "investigation_no": number,
                "original_investigation_id": rec["original_investigation_id"],
                "recurrence_id": recurrence_id}
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "A related investigation already exists for this rejection and template") from exc


@router.get("/defect-history/{defect_code}")
def defect_history(defect_code: str, rejection_id: int | None = None,
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Show the latest investigations for the selected shared Quality phenomenon.

    When a new rejection is selected, only FTA events preceding that rejection
    are returned. This is an automatic history match, not an automatic
    recurrence classification; Quality confirms the relationship.
    """
    _role(user, READ_ROLES)
    mapping = db.execute(text("""
        SELECT fm.phenomenon_id, ph.name AS phenomenon_name
        FROM fta_phenomenon_code_map fm
        JOIN fta_defect_library d ON d.code=fm.legacy_defect_code
        JOIN quality_rejection_phenomena ph ON ph.id=fm.phenomenon_id
        WHERE fm.legacy_defect_code=:code AND d.is_active=true AND ph.is_active=true
    """), {"code": defect_code}).mappings().first()
    if not mapping:
        raise HTTPException(404, "Selected FTA defect is not linked to an active Quality phenomenon")

    target = None
    if rejection_id is not None:
        target = db.execute(text("""
            SELECT id, rejection_date, product_id, phenomenon_id
            FROM quality_rejection_daily WHERE id=:id
        """), {"id": rejection_id}).mappings().first()
        if not target:
            raise HTTPException(404, "Selected Quality Rejection record not found")
        if target["phenomenon_id"] != mapping["phenomenon_id"]:
            raise HTTPException(422, "Selected rejection does not match this Quality defect")

    params = {
        "phenomenon_id": mapping["phenomenon_id"],
        "target_fta_cutoff": (
            datetime.combine(target["rejection_date"] + timedelta(days=1), datetime.min.time())
            if target else None
        ),
        "target_product_id": target["product_id"] if target else None,
        "user_id": user.id,
    }
    production_scope = ""
    if _role_name(user) == "PRODUCTION":
        production_scope = " AND (i.owner_id=:user_id OR i.created_by_id=:user_id)"

    rows = db.execute(text(f"""
        SELECT i.id AS investigation_id, i.investigation_no, i.status,
               i.operation_code, i.plant, i.machine_id, m.name AS machine_name,
               i.rejection_id, i.created_at AS fta_date, q.rejection_date AS rejection_date, q.shift,
               p.code AS part_code, p.name AS part_name, q.reject_qty,
               CASE WHEN :target_product_id IS NOT NULL AND q.product_id=:target_product_id
                    THEN true ELSE false END AS same_part,
               ph.name AS phenomenon_name, t.name AS template_name,
               COALESCE((
                   SELECT string_agg(DISTINCT a.status::text, ', ')
                   FROM fta_action_links al JOIN actions a ON a.id=al.action_id
                   WHERE al.investigation_id=i.id
               ), 'NO LINKED ACTION') AS linked_action_status,
               (
                   SELECT COUNT(*) FROM fta_recurrences r
                   WHERE r.original_investigation_id=i.id
               ) AS linked_recurrence_count,
               (
                   SELECT string_agg(DISTINCT f.node_label, '; ')
                   FROM fta_findings f
                   WHERE f.investigation_id=i.id
                     AND f.is_root_cause=true
                     AND f.investigation_status='CONFIRMED'
               ) AS confirmed_root_causes
        FROM fta_investigations i
        JOIN fta_templates t ON t.id=i.template_id
        JOIN fta_phenomenon_code_map fm ON fm.legacy_defect_code=t.defect_code
        JOIN quality_rejection_daily q ON q.id=i.rejection_id
        JOIN products p ON p.id=q.product_id
        JOIN quality_rejection_phenomena ph ON ph.id=q.phenomenon_id
        LEFT JOIN machines m ON m.id=COALESCE(i.machine_id,q.machine_id)
        WHERE fm.phenomenon_id=:phenomenon_id
          AND (:target_fta_cutoff IS NULL OR i.created_at < :target_fta_cutoff)
          {production_scope}
        ORDER BY i.created_at DESC, i.id DESC
        LIMIT 50
    """), params).mappings().all()
    matches = [dict(row) for row in rows]
    return {
        "defect_code": defect_code,
        "phenomenon_id": mapping["phenomenon_id"],
        "phenomenon_name": mapping["phenomenon_name"],
        "selected_rejection_id": target["id"] if target else None,
        "selected_rejection_date": target["rejection_date"] if target else None,
        "total_previous_investigations": len(matches),
        "last_fta_date": matches[0]["fta_date"] if matches else None,
        "last_investigation_no": matches[0]["investigation_no"] if matches else None,
        "matches": matches,
    }