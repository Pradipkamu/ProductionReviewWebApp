from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..enums import SourceType
from ..models import (
    DailyRequirement,
    Operation,
    ProcessActualHistory,
    ProcessDailySummary,
    ProcessFlowStage,
    Product,
    RouteOperation,
    RouteVersion,
    User,
)
from ..schemas import ProcessActualEdit, ProcessEntry
from ..services.dashboard import process_monitor
from ..services.filtering import csv_ints, csv_strings

router = APIRouter(prefix="/process", tags=["process"])


def _source_name(value) -> str:
    if value is None:
        return ""
    return value.value if hasattr(value, "value") else str(value)


def _snapshot(row: ProcessDailySummary | None) -> dict | None:
    if not row:
        return None
    return {
        "actual_qty": row.actual_qty,
        "good_qty": row.good_qty,
        "reject_qty": row.reject_qty,
        "source": _source_name(row.source),
    }


def _record_actual_history(
    db: Session,
    row: ProcessDailySummary,
    before: dict | None,
    user: User,
    reason: str,
) -> None:
    after = _snapshot(row)
    if before == after:
        return
    db.add(ProcessActualHistory(
        process_summary_id=row.id,
        summary_date=row.summary_date,
        product_id=row.product_id,
        route_operation_id=row.route_operation_id,
        changed_by_id=user.id,
        change_type="CREATED" if before is None else "CORRECTED",
        reason=reason,
        old_actual_qty=before["actual_qty"] if before else None,
        new_actual_qty=row.actual_qty,
        old_good_qty=before["good_qty"] if before else None,
        new_good_qty=row.good_qty,
        old_reject_qty=before["reject_qty"] if before else None,
        new_reject_qty=row.reject_qty,
        old_source=before["source"] if before else None,
        new_source=_source_name(row.source),
    ))


def _row_for(db: Session, summary_date: date, product_id: int, route_operation_id: int) -> ProcessDailySummary | None:
    return db.scalar(select(ProcessDailySummary).where(
        ProcessDailySummary.summary_date == summary_date,
        ProcessDailySummary.product_id == product_id,
        ProcessDailySummary.route_operation_id == route_operation_id,
    ))


def _legacy_route_operation(db: Session, product_id: int, route_operation_id: int, d: date) -> RouteOperation | None:
    route = db.scalar(
        select(RouteVersion)
        .where(
            RouteVersion.product_id == product_id,
            RouteVersion.effective_from <= d,
            RouteVersion.is_active.is_(True),
        )
        .where((RouteVersion.effective_to.is_(None)) | (RouteVersion.effective_to >= d))
        .order_by(RouteVersion.effective_from.desc(), RouteVersion.revision_no.desc())
        .limit(1)
    )
    if not route:
        return None
    return db.scalar(select(RouteOperation).where(
        RouteOperation.id == route_operation_id,
        RouteOperation.route_version_id == route.id,
        RouteOperation.is_enabled.is_(True),
    ))


@router.get("/monitor")
def monitor(
    product_id: int,
    monitor_date: date,
    start_date: date | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    try:
        return process_monitor(db, product_id, monitor_date, start_date=start_date)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/actuals")
def list_process_actuals(
    actual_date: date,
    missing_only: bool = False,
    product_id: str | None = None,
    plant: str | None = None,
    product_group: str | None = None,
    customer_id: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    from ..services.process_flows import active_flow

    q = select(Product).where(Product.is_active.is_(True))
    product_ids = csv_ints(product_id)
    plants = csv_strings(plant)
    groups = csv_strings(product_group)
    customer_ids = csv_ints(customer_id)
    if product_ids:
        q = q.where(Product.id.in_(product_ids))
    if plants:
        q = q.where(Product.plant.in_(plants))
    if groups:
        q = q.where(Product.product_group.in_(groups))
    if customer_ids:
        q = q.where(Product.customer_id.in_(customer_ids))
    products = db.scalars(q.order_by(Product.plant, Product.sort_order, Product.name)).all()

    output = []
    without_route = []
    for product in products:
        flow = active_flow(db, product.id, actual_date)
        stage_rows: list[dict] = []
        if flow:
            stages = db.scalars(
                select(ProcessFlowStage)
                .where(
                    ProcessFlowStage.flow_id == flow.id,
                    ProcessFlowStage.is_active.is_(True),
                    ProcessFlowStage.route_operation_id.is_not(None),
                )
                .order_by(ProcessFlowStage.sequence_no)
            ).all()
            stage_rows = [{
                "route_operation_id": s.route_operation_id,
                "stage_code": s.code,
                "stage_name": s.name,
                "role": s.role,
                "sequence_no": s.sequence_no,
                "flow_revision": flow.revision_no,
            } for s in stages]
        else:
            route = db.scalar(
                select(RouteVersion)
                .where(
                    RouteVersion.product_id == product.id,
                    RouteVersion.effective_from <= actual_date,
                    RouteVersion.is_active.is_(True),
                )
                .where((RouteVersion.effective_to.is_(None)) | (RouteVersion.effective_to >= actual_date))
                .order_by(RouteVersion.effective_from.desc(), RouteVersion.revision_no.desc())
                .limit(1)
            )
            if route:
                ops = db.execute(
                    select(RouteOperation, Operation)
                    .join(Operation, Operation.id == RouteOperation.operation_id)
                    .where(RouteOperation.route_version_id == route.id, RouteOperation.is_enabled.is_(True))
                    .order_by(RouteOperation.sequence_no)
                ).all()
                stage_rows = [{
                    "route_operation_id": ro.id,
                    "stage_code": op.code,
                    "stage_name": ro.source_label or op.name,
                    "role": op.operation_type.value if hasattr(op.operation_type, "value") else str(op.operation_type),
                    "sequence_no": ro.sequence_no,
                    "flow_revision": None,
                } for ro, op in ops]
            else:
                without_route.append(product.name)
                continue

        route_ids = [int(s["route_operation_id"]) for s in stage_rows]
        actuals = {
            r.route_operation_id: r for r in db.scalars(select(ProcessDailySummary).where(
                ProcessDailySummary.summary_date == actual_date,
                ProcessDailySummary.product_id == product.id,
                ProcessDailySummary.route_operation_id.in_(route_ids),
            )).all()
        } if route_ids else {}
        requirements = {
            r.route_operation_id: r for r in db.scalars(select(DailyRequirement).where(
                DailyRequirement.req_date == actual_date,
                DailyRequirement.product_id == product.id,
                DailyRequirement.route_operation_id.in_(route_ids),
            )).all()
        } if route_ids else {}

        for stage in stage_rows:
            rid = int(stage["route_operation_id"])
            row = actuals.get(rid)
            req = requirements.get(rid)
            if missing_only and row is not None:
                continue
            output.append({
                "id": row.id if row else None,
                "date": actual_date,
                "plant": product.plant,
                "product_group": product.product_group,
                "product_id": product.id,
                "product": product.name,
                **stage,
                "plan_qty": float(req.revised_plan_qty) if req else (float(row.plan_qty) if row else None),
                "plan_missing": req is None,
                "actual_qty": float(row.actual_qty) if row else None,
                "good_qty": float(row.good_qty) if row else None,
                "reject_qty": float(row.reject_qty) if row else None,
                "source": _source_name(row.source) if row else None,
                "remarks": row.remarks if row else None,
                "updated_at": row.updated_at if row else None,
                "status": "ENTERED" if row else "MISSING",
            })

    missing = sum(1 for r in output if r["status"] == "MISSING")
    entered = sum(1 for r in output if r["status"] == "ENTERED")
    return {
        "date": actual_date,
        "counts": {"rows": len(output), "missing": missing, "entered": entered},
        "products_without_route": without_route,
        "rows": output,
    }


@router.put("/actuals")
def edit_process_actual(
    payload: ProcessActualEdit,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from ..services.process_flows import active_flow, apply_actual, check_dispatch_totals

    product = db.get(Product, payload.product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    reason = payload.reason.strip()
    before_row = _row_for(db, payload.summary_date, payload.product_id, payload.route_operation_id)
    before = _snapshot(before_row)

    flow = active_flow(db, payload.product_id, payload.summary_date)
    if flow:
        stage = db.scalar(select(ProcessFlowStage).where(
            ProcessFlowStage.flow_id == flow.id,
            ProcessFlowStage.route_operation_id == payload.route_operation_id,
            ProcessFlowStage.is_active.is_(True),
        ))
        if not stage:
            raise HTTPException(422, "Operation does not belong to the active approved flow")
        stats = {"new": 0, "updated": 0, "unchanged": 0, "warnings": []}
        try:
            apply_actual(db, {
                "product": product.name,
                "stage_code": stage.code,
                "date": payload.summary_date,
                "actual_qty": payload.actual_qty,
                "reject_qty": payload.reject_qty,
                "reason": reason,
                "source": SourceType.MANUAL,
            }, stats)
            check_dispatch_totals(db, {(payload.product_id, payload.summary_date)})
            db.flush()
        except ValueError as exc:
            db.rollback()
            raise HTTPException(422, str(exc)) from exc
        row = _row_for(db, payload.summary_date, payload.product_id, payload.route_operation_id)
    else:
        route_op = _legacy_route_operation(db, payload.product_id, payload.route_operation_id, payload.summary_date)
        if not route_op:
            raise HTTPException(422, "Operation does not belong to the effective product route")
        row = before_row
        req = db.scalar(select(DailyRequirement).where(
            DailyRequirement.req_date == payload.summary_date,
            DailyRequirement.product_id == payload.product_id,
            DailyRequirement.route_operation_id == payload.route_operation_id,
        ))
        if not row:
            row = ProcessDailySummary(
                summary_date=payload.summary_date,
                product_id=payload.product_id,
                route_operation_id=payload.route_operation_id,
                plan_qty=req.revised_plan_qty if req else 0,
            )
            db.add(row)
        row.actual_qty = payload.actual_qty
        row.reject_qty = payload.reject_qty
        row.good_qty = payload.actual_qty - payload.reject_qty
        row.remarks = reason
        row.source = SourceType.MANUAL
        original_reason = db.info.get("reason")
        db.info["reason"] = reason
        try:
            db.flush()
        finally:
            if original_reason is None:
                db.info.pop("reason", None)
            else:
                db.info["reason"] = original_reason

    if not row:
        db.rollback()
        raise HTTPException(500, "Process actual could not be saved")
    _record_actual_history(db, row, before, user, reason)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "date": row.summary_date,
        "product_id": row.product_id,
        "route_operation_id": row.route_operation_id,
        "plan_qty": float(row.plan_qty),
        "actual_qty": float(row.actual_qty),
        "good_qty": float(row.good_qty),
        "reject_qty": float(row.reject_qty),
        "source": _source_name(row.source),
        "remarks": row.remarks,
        "updated_at": row.updated_at,
    }


@router.get("/actuals/{summary_id}/history")
def process_actual_history(
    summary_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    row = db.get(ProcessDailySummary, summary_id)
    if not row:
        raise HTTPException(404, "Process actual not found")
    history = db.scalars(
        select(ProcessActualHistory)
        .where(ProcessActualHistory.process_summary_id == summary_id)
        .order_by(ProcessActualHistory.changed_at.desc(), ProcessActualHistory.id.desc())
    ).all()
    result = []
    for h in history:
        who = db.get(User, h.changed_by_id) if h.changed_by_id else None
        result.append({
            "id": h.id,
            "changed_at": h.changed_at,
            "changed_by": who.full_name if who else None,
            "change_type": h.change_type,
            "reason": h.reason,
            "old_actual_qty": float(h.old_actual_qty) if h.old_actual_qty is not None else None,
            "new_actual_qty": float(h.new_actual_qty),
            "old_good_qty": float(h.old_good_qty) if h.old_good_qty is not None else None,
            "new_good_qty": float(h.new_good_qty),
            "old_reject_qty": float(h.old_reject_qty) if h.old_reject_qty is not None else None,
            "new_reject_qty": float(h.new_reject_qty),
            "old_source": h.old_source,
            "new_source": h.new_source,
        })
    return result


@router.post("/entry")
def save_entry(payload: ProcessEntry, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from ..services.process_flows import active_flow, stage_for, apply_actual, check_dispatch_totals

    before_row = _row_for(db, payload.summary_date, payload.product_id, payload.route_operation_id)
    before = _snapshot(before_row)
    flow = active_flow(db, payload.product_id, payload.summary_date)
    reason = (payload.remarks or "").strip()
    if flow:
        stage = db.scalar(select(ProcessFlowStage).where(ProcessFlowStage.route_operation_id == payload.route_operation_id))
        if not stage or stage.flow_id != flow.id or not stage.is_active:
            raise HTTPException(422, "Operation does not belong to the active approved flow")
        stats = {"new": 0, "updated": 0, "unchanged": 0, "warnings": []}
        try:
            apply_actual(db, {
                "product": db.get(Product, payload.product_id).name,
                "stage_code": stage.code,
                "date": payload.summary_date,
                "actual_qty": payload.actual_qty,
                "reject_qty": payload.reject_qty,
                "reason": reason,
                "source": payload.source,
            }, stats)
            check_dispatch_totals(db, {(payload.product_id, payload.summary_date)})
            db.flush()
            row = _row_for(db, payload.summary_date, payload.product_id, payload.route_operation_id)
            if row:
                _record_actual_history(db, row, before, user, reason or "Manual process actual entry")
            db.commit()
        except ValueError as exc:
            db.rollback()
            raise HTTPException(422, str(exc)) from exc
        return stats

    row = before_row
    if row and before and (
        row.actual_qty != payload.actual_qty
        or row.good_qty != payload.good_qty
        or row.reject_qty != payload.reject_qty
    ) and not reason:
        raise HTTPException(422, "Changing an existing actual requires a correction reason")
    if not row:
        row = ProcessDailySummary(
            summary_date=payload.summary_date,
            product_id=payload.product_id,
            route_operation_id=payload.route_operation_id,
        )
        db.add(row)
    for field in ["plan_qty", "actual_qty", "good_qty", "reject_qty", "opening_wip", "closing_wip", "remarks", "source"]:
        setattr(row, field, getattr(payload, field))
    db.flush()
    _record_actual_history(db, row, before, user, reason or "Manual process actual entry")
    db.commit()
    db.refresh(row)
    return {"id": row.id}
