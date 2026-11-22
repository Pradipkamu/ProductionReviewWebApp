from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..config import get_settings
from ..services.file_security import UploadSecurityError, safe_original_name, safe_path, save_limited_stream, validate_attachment_file
from ..models import User

router = APIRouter(prefix="/fta", tags=["fault-tree-analysis"])

READ_ROLES = {"ADMIN", "MANAGEMENT", "QUALITY", "PRODUCTION"}
WRITE_ROLES = {"ADMIN", "QUALITY", "PRODUCTION"}
TEMPLATE_ROLES = {"ADMIN", "QUALITY"}
NODE_STATUSES = {"NOT_INVESTIGATED", "UNDER_INVESTIGATION", "SUSPECTED", "CONFIRMED", "RULED_OUT", "UNABLE_TO_DETERMINE"}
INVESTIGATION_STATUSES = {"OPEN", "IN_PROGRESS", "PENDING_VERIFICATION", "CLOSED"}
MAX_FTA_EVIDENCE_BYTES = 20 * 1024 * 1024
MAX_FTA_EVIDENCE_FILES = 40
FTA_EVIDENCE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".pdf", ".xlsx", ".xls", ".csv", ".txt"}


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
        children = node.get("children") or []
        if not isinstance(children, list):
            raise HTTPException(422, "Fault-tree children must be a list")
        gate = node.get("gate")
        if children and gate not in {"AND", "OR"}:
            raise HTTPException(422, "Every node with children must have an AND or OR gate")
        if not children and gate not in {None, ""}:
            raise HTTPException(422, "A leaf event cannot have a logic gate")
        nodes.append({
            "node_id": str(node.get("id") or ""),
            "node_label": str(node.get("label") or "").strip(),
            "node_type": node_type,
        })
        for child in children:
            visit(child, depth + 1)
    visit(tree)
    ids = [node["node_id"] for node in nodes]
    if any(not node["node_id"] or not node["node_label"] for node in nodes) or len(ids) != len(set(ids)):
        raise HTTPException(422, "Every fault-tree node must have a unique ID and non-empty label")
    return nodes


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
    findings = db.execute(text("""
        SELECT id, node_id, node_label, node_type, investigation_status, observation,
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
               a.action_description, a.status, a.owner_id, a.due_at
        FROM fta_action_links l JOIN actions a ON a.id=l.action_id
        WHERE l.investigation_id=:id ORDER BY l.id
    """), {"id": result["id"]}).mappings().all()
    result["actions"] = [dict(x) for x in actions]
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
        SELECT id, code, category, name, description
        FROM fta_defect_library WHERE is_active=true ORDER BY category, name
    """)).mappings().all()
    return [dict(x) for x in rows]


@router.get("/rejections")
def list_rejections(limit: int = 100, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _role(user, READ_ROLES)
    limit = max(1, min(limit, 300))
    rows = db.execute(text("""
        SELECT q.id, q.rejection_date, q.shift, COALESCE(q.plant,p.plant) AS plant, q.machine_id,
               q.reject_qty, q.remark, p.code AS part_code, p.name AS part_name,
               ph.name AS phenomenon, m.name AS machine
        FROM quality_rejection_daily q
        JOIN products p ON p.id=q.product_id
        JOIN quality_rejection_phenomena ph ON ph.id=q.phenomenon_id
        LEFT JOIN machines m ON m.id=q.machine_id
        WHERE UPPER(COALESCE(ph.phenomenon_group,'')) NOT LIKE '%CAST%'
          AND UPPER(ph.name) NOT LIKE '%CASTING%'
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
        row = db.execute(text("""
            INSERT INTO fta_defect_library (code, category, name, description)
            VALUES (:code, :category, :name, :description) RETURNING id, code, category, name, description
        """), {"code": payload.code.upper(), "category": payload.category.strip(),
               "name": payload.name.strip(), "description": payload.description}).mappings().one()
        db.commit()
        return dict(row)
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
    if not db.execute(text("SELECT code FROM fta_defect_library WHERE code=:code AND is_active=true"),
                      {"code": payload.defect_code}).first():
        raise HTTPException(422, "Select an active defect")
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
               t.defect_code, d.name AS defect_name, d.category AS defect_category,
               t.version, t.status
        FROM fta_templates t
        JOIN fta_operations o ON o.code=t.operation_code
        JOIN fta_defect_library d ON d.code=t.defect_code
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
    query += " ORDER BY o.name, d.category, d.name, t.version DESC"
    rows = db.execute(text(query), params).mappings().all()
    return [dict(x) for x in rows]


@router.get("/templates/{template_id}")
def get_template(template_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _role(user, READ_ROLES)
    row = db.execute(text("""
        SELECT t.id, t.code, t.name, t.operation_code, o.name AS operation_name,
               t.defect_code, d.name AS defect_name, d.category AS defect_category,
               t.version, t.status, t.tree_json
        FROM fta_templates t JOIN fta_operations o ON o.code=t.operation_code
        JOIN fta_defect_library d ON d.code=t.defect_code WHERE t.id=:id
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
               i.plant, i.machine_id, i.status, i.owner_id, i.summary, i.created_at,
               t.name AS template_name, d.name AS defect_name, p.code AS part_code, p.name AS part_name
        FROM fta_investigations i
        JOIN fta_templates t ON t.id=i.template_id
        JOIN fta_defect_library d ON d.code=t.defect_code
        JOIN quality_rejection_daily q ON q.id=i.rejection_id
        JOIN products p ON p.id=q.product_id WHERE 1=1
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
    if payload.owner_id and not db.execute(text("SELECT id FROM users WHERE id=:id AND is_active=true"),
                                           {"id": payload.owner_id}).first():
        raise HTTPException(422, "Selected investigation owner is not active")
    existing = db.execute(text("""
        SELECT id, investigation_no FROM fta_investigations
        WHERE rejection_id=:rejection_id AND template_id=:template_id AND status <> 'CLOSED'
        ORDER BY id DESC LIMIT 1
    """), {"rejection_id": payload.rejection_id, "template_id": payload.template_id}).mappings().first()
    if existing:
        raise HTTPException(409, detail=f"An open investigation already exists: {existing['investigation_no']}")
    tree = _json(template["tree_json"], {})
    snapshot = {
        "template_id": template["id"], "template_code": template["code"],
        "template_name": template["name"], "template_version": template["version"],
        "operation_code": template["operation_code"], "defect_code": template["defect_code"],
        "rejection": {k: str(v) if v is not None else None for k, v in dict(rejection).items()},
        "tree": tree,
    }
    now = datetime.utcnow()
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


@router.get("/investigations/{investigation_id}")
def get_investigation(investigation_id: int, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    _assert_investigation_access(db, investigation_id, user)
    row = db.execute(text("SELECT * FROM fta_investigations WHERE id=:id"), {"id": investigation_id}).mappings().one()
    return _investigation(row, db)


@router.patch("/investigations/{investigation_id}")
def update_investigation(investigation_id: int, payload: InvestigationUpdate,
                         db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _role(user, WRITE_ROLES)
    row = _assert_investigation_access(db, investigation_id, user, WRITE_ROLES)
    if row["status"] not in {"OPEN", "IN_PROGRESS"}:
        raise HTTPException(409, "Only open investigations can be edited")
    data = payload.model_dump(exclude_unset=True)
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
    if payload.is_root_cause and payload.investigation_status != "CONFIRMED":
        raise HTTPException(422, "A root cause must have CONFIRMED investigation status")
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
        "measured_value", "expected_value", "verification_method", "verification_result",
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
        UPDATE fta_findings SET investigation_status=:status, observation=:observation,
          measured_value=:measured, expected_value=:expected, verification_method=:method,
          verification_result=:result, is_root_cause=:root, is_occurrence_cause=:occurrence,
          is_escape_cause=:escape, updated_by_id=:user_id, updated_at=:now
        WHERE id=:id
    """), {
        "status": payload.investigation_status, "observation": payload.observation,
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
        FROM fta_evidence WHERE investigation_id=:id AND sha256=:sha
    """), {"id": investigation_id, "sha": sha}).mappings().first()
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
        SELECT DISTINCT p.plant FROM action_contexts ac
        JOIN products p ON p.id=ac.product_id
        WHERE ac.action_id=:action_id AND p.plant IS NOT NULL
    """), {"action_id": payload.action_id}).all())
    if action_plants and investigation["plant"] and investigation["plant"] not in action_plants:
        raise HTTPException(422, "The action belongs to a different plant than this FTA investigation")
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


@router.post("/investigations/{investigation_id}/verify")
def verify_investigation(investigation_id: int, payload: VerifyRequest,
                         db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _role(user, {"ADMIN", "QUALITY"})
    row = db.execute(text("SELECT status FROM fta_investigations WHERE id=:id"),
                     {"id": investigation_id}).mappings().first()
    if not row:
        raise HTTPException(404, "FTA investigation not found")
    if row["status"] != "IN_PROGRESS":
        raise HTTPException(409, "Only an in-progress investigation can be submitted for verification")
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
        UPDATE fta_investigations SET status='PENDING_VERIFICATION', verified_by_id=:user_id,
          verified_at=:now, updated_at=:now WHERE id=:id
    """), {"user_id": user.id, "now": now, "id": investigation_id})
    db.execute(text("""
        INSERT INTO fta_status_history (investigation_id, old_status, new_status, remarks, changed_by_id)
        VALUES (:id, :old, 'PENDING_VERIFICATION', :remarks, :user_id)
    """), {"id": investigation_id, "old": row["status"], "remarks": payload.remarks, "user_id": user.id})
    db.commit()
    return {"success": True, "status": "PENDING_VERIFICATION"}


@router.post("/investigations/{investigation_id}/close")
def close_investigation(investigation_id: int, payload: CloseRequest,
                        db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _role(user, {"ADMIN", "QUALITY"})
    row = db.execute(text("SELECT status FROM fta_investigations WHERE id=:id"),
                     {"id": investigation_id}).mappings().first()
    if not row:
        raise HTTPException(404, "FTA investigation not found")
    if row["status"] != "PENDING_VERIFICATION":
        raise HTTPException(409, "Investigation must be verified before closure")
    linked_total = db.execute(text("""
        SELECT COUNT(*) FROM fta_action_links WHERE investigation_id=:id
    """), {"id": investigation_id}).scalar_one()
    if not linked_total:
        raise HTTPException(422, "Link at least one corrective or preventive action before closing the investigation")
    linked_open = db.execute(text("""
        SELECT COUNT(*) FROM fta_action_links l JOIN actions a ON a.id=l.action_id
        WHERE l.investigation_id=:id AND a.status <> 'CLOSED'
    """), {"id": investigation_id}).scalar_one()
    if linked_open:
        raise HTTPException(422, "Complete linked corrective actions before closing the investigation")
    now = datetime.utcnow()
    db.execute(text("""
        UPDATE fta_investigations SET status='CLOSED', closure_remarks=:remarks,
          closed_by_id=:user_id, closed_at=:now, updated_at=:now WHERE id=:id
    """), {"remarks": payload.remarks, "user_id": user.id, "now": now, "id": investigation_id})
    db.execute(text("""
        INSERT INTO fta_status_history (investigation_id, old_status, new_status, remarks, changed_by_id)
        VALUES (:id, :old, 'CLOSED', :remarks, :user_id)
    """), {"id": investigation_id, "old": row["status"], "remarks": payload.remarks, "user_id": user.id})
    db.commit()
    return {"success": True, "status": "CLOSED"}


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _role(user, READ_ROLES)
    counts = db.execute(text("""
        SELECT COUNT(*) AS total,
          SUM(CASE WHEN status IN ('OPEN','IN_PROGRESS') THEN 1 ELSE 0 END) AS open,
          SUM(CASE WHEN status='PENDING_VERIFICATION' THEN 1 ELSE 0 END) AS pending_verification,
          SUM(CASE WHEN status='CLOSED' THEN 1 ELSE 0 END) AS closed
        FROM fta_investigations
    """)).mappings().one()
    defects = db.execute(text("""
        SELECT d.name AS defect, COUNT(*) AS investigations
        FROM fta_investigations i JOIN fta_templates t ON t.id=i.template_id
        JOIN fta_defect_library d ON d.code=t.defect_code
        GROUP BY d.name ORDER BY investigations DESC, d.name LIMIT 5
    """)).mappings().all()
    causes = db.execute(text("""
        SELECT f.node_label AS cause, COUNT(*) AS occurrences
        FROM fta_findings f JOIN fta_investigations i ON i.id=f.investigation_id
        WHERE f.is_root_cause=true AND f.investigation_status='CONFIRMED'
        GROUP BY f.node_label ORDER BY occurrences DESC, f.node_label LIMIT 5
    """)).mappings().all()
    return {"counts": dict(counts), "top_defects": [dict(x) for x in defects],
            "top_verified_causes": [dict(x) for x in causes]}
