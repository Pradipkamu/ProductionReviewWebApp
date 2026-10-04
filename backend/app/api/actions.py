from datetime import date, datetime
from pathlib import Path
import hashlib
import re
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user, record_security_event
from ..config import get_settings
from ..db import get_db
from ..enums import ActionStatus
from ..models import (
    Action, ActionAttachment, ActionContext, ActionHistory, ActionWhyWhy,
    Product, RouteOperation, Operation, Machine, ReviewActionLink, ReviewSession, User,
)
from ..services.filtering import csv_enums, csv_ints, csv_strings
from ..schemas import ActionCreate, ActionUpdate, ActionWhyWhyUpdate
from ..services.action_pdf import build_action_plan_pdf
from ..services.file_security import (
    UploadSecurityError, safe_original_name, safe_path, save_limited_stream, validate_attachment_file,
)

router = APIRouter(prefix="/actions", tags=["actions"])
settings = get_settings()

PLAN_FIELDS = [
    "containment_action", "why1", "why2", "why3", "why4", "why5",
    "root_cause", "corrective_action", "preventive_action",
    "verification_method", "verification_result", "effectiveness_result",
    "lessons_learned",
]
CLOSE_REQUIRED = ["why1", "why2", "root_cause", "corrective_action", "verification_method", "verification_result", "effectiveness_result"]


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _serialize_plan(plan: ActionWhyWhy | None) -> dict:
    if not plan:
        data = {k: None for k in PLAN_FIELDS}
        data.update({"id": None, "effectiveness_check_date": None, "completion_percent": 0, "missing_for_close": CLOSE_REQUIRED, "can_close": False})
        return data
    values = {k: getattr(plan, k) for k in PLAN_FIELDS}
    completed = sum(1 for k in CLOSE_REQUIRED if _clean_text(values.get(k)))
    missing = [k for k in CLOSE_REQUIRED if not _clean_text(values.get(k))]
    return {
        "id": plan.id,
        **values,
        "effectiveness_check_date": plan.effectiveness_check_date,
        "completion_percent": round(completed / len(CLOSE_REQUIRED) * 100),
        "missing_for_close": missing,
        "can_close": not missing,
    }


def _attachments(db: Session, action_id: int) -> list[dict]:
    rows = db.scalars(
        select(ActionAttachment).where(ActionAttachment.action_id == action_id).order_by(ActionAttachment.created_at.desc())
    ).all()
    return [{
        "id": x.id,
        "file_name": x.file_name,
        "mime_type": x.mime_type,
        "size_bytes": x.size_bytes,
        "sha256": x.sha256,
        "caption": x.caption,
        "uploaded_by_id": x.uploaded_by_id,
        "created_at": x.created_at,
    } for x in rows]


def serialize_action(db: Session, a: Action) -> dict:
    contexts = db.execute(
        select(ActionContext, Product, RouteOperation, Operation, Machine)
        .outerjoin(Product, Product.id == ActionContext.product_id)
        .outerjoin(RouteOperation, RouteOperation.id == ActionContext.route_operation_id)
        .outerjoin(Operation, Operation.id == RouteOperation.operation_id)
        .outerjoin(Machine, Machine.id == ActionContext.machine_id)
        .where(ActionContext.action_id == a.id)
    ).all()
    plan = db.scalar(select(ActionWhyWhy).where(ActionWhyWhy.action_id == a.id))
    return {
        "id": a.id,
        "action_no": a.action_no,
        "reference_date": a.reference_date,
        "problem_category": a.problem_category,
        "problem_description": a.problem_description,
        "action_description": a.action_description,
        "owner_id": a.owner_id,
        "due_at": a.due_at,
        "priority": a.priority.value,
        "status": a.status.value,
        "kpi_type": a.kpi_type,
        "gap_when_raised": float(a.gap_when_raised) if a.gap_when_raised is not None else None,
        "closed_at": a.closed_at,
        "closure_remark": a.closure_remark,
        "effectiveness_status": a.effectiveness_status,
        "age_days": max(0, (date.today() - a.reference_date).days),
        "overdue": bool(a.due_at and a.status != ActionStatus.CLOSED and a.due_at < datetime.utcnow()),
        "whywhy_completion_percent": _serialize_plan(plan)["completion_percent"],
        "whywhy_can_close": _serialize_plan(plan)["can_close"],
        "review_session_ids": list(db.scalars(
            select(ReviewActionLink.review_session_id).where(ReviewActionLink.action_id == a.id)
        ).all()),
        "contexts": [{
            "date": ctx.context_date,
            "product_id": ctx.product_id,
            "product": p.name if p else None,
            "plant": p.plant if p else None,
            "product_group": p.product_group if p else None,
            "customer_id": p.customer_id if p else None,
            "route_operation_id": ctx.route_operation_id,
            "operation": op.name if op else None,
            "machine_id": ctx.machine_id,
            "machine": (f"{machine.code} - {machine.name}" if machine else None),
            "loss_event_id": ctx.loss_event_id,
        } for ctx, p, ro, op, machine in contexts],
    }


@router.get("")
def list_actions(
    status: str | None = None,
    product_id: str | None = None,
    plant: str | None = None,
    product_group: str | None = None,
    customer_id: str | None = None,
    reference_date: date | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = select(Action).order_by(Action.status, Action.priority.desc(), Action.due_at, Action.reference_date.desc())
    statuses = csv_enums(status, ActionStatus)
    if statuses:
        q = q.where(Action.status.in_(statuses))
    if reference_date:
        q = q.where(Action.reference_date == reference_date)
    actions = db.scalars(q).all()

    product_ids = csv_ints(product_id)
    plants = csv_strings(plant)
    groups = csv_strings(product_group)
    customer_ids = csv_ints(customer_id)
    if any([product_ids, plants, groups, customer_ids]):
        ctx_q = select(ActionContext.action_id).join(Product, Product.id == ActionContext.product_id)
        if product_ids:
            ctx_q = ctx_q.where(ActionContext.product_id.in_(product_ids))
        if plants:
            ctx_q = ctx_q.where(Product.plant.in_(plants))
        if groups:
            ctx_q = ctx_q.where(Product.product_group.in_(groups))
        if customer_ids:
            ctx_q = ctx_q.where(Product.customer_id.in_(customer_ids))
        ids = set(db.scalars(ctx_q.distinct()).all())
        actions = [a for a in actions if a.id in ids]
    return [serialize_action(db, a) for a in actions]


@router.post("")
def create_action(payload: ActionCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    count = db.query(Action).count() + 1
    action_no = f"ACT-{payload.reference_date.year}-{count:05d}"
    a = Action(
        action_no=action_no,
        reference_date=payload.reference_date,
        problem_category=payload.problem_category,
        problem_description=payload.problem_description,
        action_description=payload.action_description,
        owner_id=payload.owner_id,
        due_at=payload.due_at,
        priority=payload.priority,
        kpi_type=payload.kpi_type,
        kpi_value_when_raised=payload.kpi_value_when_raised,
        gap_when_raised=payload.gap_when_raised,
    )
    db.add(a); db.flush()
    for c in payload.contexts:
        db.add(ActionContext(action_id=a.id, **c.model_dump()))
    # Every new action gets one standard Why-Why plan record. It can be completed
    # progressively after the quick action is raised from any module.
    db.add(ActionWhyWhy(action_id=a.id, containment_action=payload.action_description, updated_by_id=user.id))
    db.add(ActionHistory(action_id=a.id, changed_by_id=user.id, new_status=a.status, comment="Action created; standard Why-Why plan opened"))

    active_review = db.scalar(
        select(ReviewSession)
        .where(ReviewSession.review_date == payload.reference_date, ReviewSession.ended_at.is_(None))
        .order_by(ReviewSession.started_at.desc(), ReviewSession.id.desc())
        .limit(1)
    )
    if active_review:
        db.add(ReviewActionLink(review_session_id=active_review.id, action_id=a.id))

    db.commit(); db.refresh(a)
    return serialize_action(db, a)


@router.get("/{action_id}/plan")
def get_action_plan(action_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    a = db.get(Action, action_id)
    if not a:
        raise HTTPException(404, "Action not found")
    plan = db.scalar(select(ActionWhyWhy).where(ActionWhyWhy.action_id == action_id))
    return {"action": serialize_action(db, a), "plan": _serialize_plan(plan), "attachments": _attachments(db, action_id)}


@router.get("/{action_id}/pdf")
def download_action_plan_pdf(action_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    a = db.get(Action, action_id)
    if not a:
        raise HTTPException(404, "Action not found")
    plan = db.scalar(select(ActionWhyWhy).where(ActionWhyWhy.action_id == action_id))
    action_data = serialize_action(db, a)
    owner = db.get(User, a.owner_id) if a.owner_id else None
    updated_by = db.get(User, plan.updated_by_id) if plan and plan.updated_by_id else None
    pdf = build_action_plan_pdf(
        action=action_data,
        plan=_serialize_plan(plan),
        contexts=action_data["contexts"],
        owner_name=owner.full_name if owner else None,
        updated_by_name=updated_by.full_name if updated_by else None,
        attachments=_attachments(db, action_id),
    )
    safe_action_no = re.sub(r"[^A-Za-z0-9._-]+", "_", a.action_no).strip("._") or f"action_{a.id}"
    filename = f"{safe_action_no}_WhyWhy_ActionPlan.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.put("/{action_id}/plan")
def update_action_plan(action_id: int, payload: ActionWhyWhyUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    a = db.get(Action, action_id)
    if not a:
        raise HTTPException(404, "Action not found")
    plan = db.scalar(select(ActionWhyWhy).where(ActionWhyWhy.action_id == action_id))
    if not plan:
        plan = ActionWhyWhy(action_id=action_id)
        db.add(plan)
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        if isinstance(value, str):
            value = _clean_text(value)
        setattr(plan, field, value)
    plan.updated_by_id = user.id
    if plan.corrective_action:
        a.action_description = plan.corrective_action
    if plan.effectiveness_result:
        a.effectiveness_status = plan.effectiveness_result
    db.add(ActionHistory(action_id=a.id, changed_by_id=user.id, old_status=a.status, new_status=a.status, comment="Standard Why-Why action plan updated"))
    db.commit(); db.refresh(plan)
    return {"plan": _serialize_plan(plan), "action": serialize_action(db, a), "attachments": _attachments(db, action_id)}


@router.post("/{action_id}/attachments")
async def upload_action_attachment(
    action_id: int,
    request: Request,
    file: UploadFile = File(...),
    caption: str | None = Form(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    a = db.get(Action, action_id)
    if not a:
        raise HTTPException(404, "Action not found")
    original = safe_original_name(file.filename, "attachment")
    ext = Path(original).suffix.lower()
    stored_name = f"{uuid.uuid4().hex}{ext}"
    relative = Path(a.action_no) / stored_name
    target = safe_path(settings.attachments_dir, relative)
    try:
        size, sha = save_limited_stream(file.file, target, settings.attachment_max_mb * 1024 * 1024)
        mime_type = validate_attachment_file(
            target,
            original,
            settings.attachment_extension_set,
            settings.office_max_uncompressed_mb * 1024 * 1024,
        )
    except UploadSecurityError as exc:
        target.unlink(missing_ok=True)
        record_security_event(db, request, "UPLOAD_REJECTED", success=False, user=user, detail=f"Action attachment: {exc.detail}")
        db.commit()
        raise HTTPException(exc.status_code, exc.detail) from exc
    att = ActionAttachment(
        action_id=a.id,
        file_name=original,
        stored_name=stored_name,
        relative_path=str(relative).replace("\\", "/"),
        mime_type=mime_type,
        size_bytes=size,
        sha256=sha,
        caption=_clean_text(caption),
        uploaded_by_id=user.id,
    )
    db.add(att)
    db.add(ActionHistory(action_id=a.id, changed_by_id=user.id, old_status=a.status, new_status=a.status, comment=f"Attachment added: {original}"))
    record_security_event(db, request, "UPLOAD_ACCEPTED", success=True, user=user, detail=f"Action attachment: {original}")
    db.commit(); db.refresh(att)
    return {"id": att.id, "file_name": att.file_name, "mime_type": att.mime_type, "size_bytes": att.size_bytes, "sha256": att.sha256, "caption": att.caption, "created_at": att.created_at}


@router.get("/{action_id}/attachments/{attachment_id}")
def download_action_attachment(action_id: int, attachment_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    att = db.scalar(select(ActionAttachment).where(ActionAttachment.id == attachment_id, ActionAttachment.action_id == action_id))
    if not att:
        raise HTTPException(404, "Attachment not found")
    try:
        path = safe_path(settings.attachments_dir, att.relative_path)
    except UploadSecurityError as exc:
        raise HTTPException(400, exc.detail) from exc
    if not path.is_file():
        raise HTTPException(404, "Attachment file is missing from storage")
    return FileResponse(
        path,
        media_type=att.mime_type or "application/octet-stream",
        filename=att.file_name,
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
    )


@router.patch("/{action_id}")
def update_action(action_id: int, payload: ActionUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    a = db.get(Action, action_id)
    if not a:
        raise HTTPException(404, "Action not found")
    old_status = a.status
    data = payload.model_dump(exclude_unset=True)
    for field in ["action_description", "owner_id", "due_at", "priority", "effectiveness_status"]:
        if field in data:
            setattr(a, field, data[field])
    if payload.status is not None:
        if payload.status == ActionStatus.CLOSED:
            plan = db.scalar(select(ActionWhyWhy).where(ActionWhyWhy.action_id == action_id))
            pdata = _serialize_plan(plan)
            if not pdata["can_close"]:
                labels = {
                    "why1": "Why 1", "why2": "Why 2", "root_cause": "Root Cause",
                    "corrective_action": "Corrective Action", "verification_method": "Verification Method",
                    "verification_result": "Verification Result", "effectiveness_result": "Effectiveness Result",
                }
                missing = ", ".join(labels.get(x, x) for x in pdata["missing_for_close"])
                raise HTTPException(400, f"Complete the standard Why-Why plan before closure. Missing: {missing}")
        a.status = payload.status
        if payload.status == ActionStatus.CLOSED:
            a.closed_at = datetime.utcnow()
            a.closure_remark = payload.closure_remark or a.closure_remark
    if payload.closure_remark is not None:
        a.closure_remark = payload.closure_remark
    db.add(ActionHistory(
        action_id=a.id,
        changed_by_id=user.id,
        old_status=old_status,
        new_status=a.status,
        comment=payload.comment,
        kpi_value_at_followup=payload.kpi_value_at_followup,
        gap_at_followup=payload.gap_at_followup,
    ))
    db.commit(); db.refresh(a)
    return serialize_action(db, a)


@router.get("/{action_id}/history")
def action_history(action_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rows = db.scalars(select(ActionHistory).where(ActionHistory.action_id == action_id).order_by(ActionHistory.changed_at.desc())).all()
    return [{
        "id": x.id, "changed_at": x.changed_at,
        "old_status": x.old_status.value if x.old_status else None,
        "new_status": x.new_status.value if x.new_status else None,
        "comment": x.comment,
        "kpi_value_at_followup": float(x.kpi_value_at_followup) if x.kpi_value_at_followup is not None else None,
        "gap_at_followup": float(x.gap_at_followup) if x.gap_at_followup is not None else None,
    } for x in rows]
