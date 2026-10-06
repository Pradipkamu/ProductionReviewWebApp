from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..enums import ActionStatus, OEEComponent, Priority
from ..models import (
    Action, ActionContext, ActionHistory, ActionWhyWhy, LossCategory, Machine,
    MachineLossEvent, MachineShiftProduction, Operation, OperationMachineMap,
    Product, ReviewActionLink, ReviewSession, RouteOperation, RouteVersion,
    StandardCycleTime, User,
)
from ..schemas import LossEventCreate, MachineEntryCreate
from ..services.oee import calculate_oee

router = APIRouter(prefix="/oee", tags=["oee"])


class OEEActionCreate(BaseModel):
    owner_id: int | None = None
    due_at: datetime | None = None
    priority: Priority = Priority.HIGH
    action_description: str = "Contain the loss, complete standard Why-Why analysis and implement corrective action"
    target_oee: Decimal = Field(default=Decimal("0.85"), ge=0, le=1)


class OEESummaryActionCreate(OEEActionCreate):
    production_date: date
    shift: str
    product_id: int
    route_operation_id: int
    machine_id: int


def _context(db: Session, product_id: int, route_operation_id: int, machine_id: int, on_date: date) -> dict:
    product = db.get(Product, product_id)
    machine = db.get(Machine, machine_id)
    if not product:
        raise HTTPException(404, "Product not found")
    if not machine or not machine.is_active:
        raise HTTPException(422, "Select an active machine")
    route_row = db.execute(
        select(RouteOperation, RouteVersion, Operation)
        .join(RouteVersion, RouteVersion.id == RouteOperation.route_version_id)
        .join(Operation, Operation.id == RouteOperation.operation_id)
        .where(RouteOperation.id == route_operation_id, RouteVersion.product_id == product_id)
    ).first()
    if not route_row:
        raise HTTPException(422, "Selected operation does not belong to the selected product")
    route_operation, route_version, operation = route_row
    if not route_operation.is_enabled or not route_version.is_active:
        raise HTTPException(422, "Selected product operation is inactive")
    if route_version.effective_from > on_date or (route_version.effective_to and route_version.effective_to < on_date):
        raise HTTPException(422, "Selected operation is not effective on the production date")

    maps = db.scalars(
        select(OperationMachineMap).where(
            OperationMachineMap.route_operation_id == route_operation_id,
            OperationMachineMap.is_active.is_(True),
            OperationMachineMap.effective_from <= on_date,
            or_(OperationMachineMap.effective_to.is_(None), OperationMachineMap.effective_to >= on_date),
        ).order_by(OperationMachineMap.priority, OperationMachineMap.machine_id)
    ).all()
    allowed_machine_ids = [x.machine_id for x in maps]
    warnings: list[str] = []
    if allowed_machine_ids and machine_id not in allowed_machine_ids:
        raise HTTPException(422, "Machine is not mapped to this product operation for the selected date")
    if not allowed_machine_ids:
        warnings.append("Machine mapping is missing for this product operation")

    cycle = db.scalar(
        select(StandardCycleTime).where(
            StandardCycleTime.route_operation_id == route_operation_id,
            or_(StandardCycleTime.machine_id == machine_id, StandardCycleTime.machine_id.is_(None)),
            StandardCycleTime.effective_from <= on_date,
            or_(StandardCycleTime.effective_to.is_(None), StandardCycleTime.effective_to >= on_date),
        ).order_by(StandardCycleTime.machine_id.is_(None), StandardCycleTime.effective_from.desc(), StandardCycleTime.id.desc())
    )
    if not cycle:
        warnings.append("Effective ideal cycle time is missing")
    return {
        "product": product, "machine": machine, "route_operation": route_operation,
        "operation": operation, "cycle": cycle, "warnings": warnings,
        "allowed_machine_ids": allowed_machine_ids,
    }


def _prepare_entry(db: Session, payload: MachineEntryCreate) -> tuple[dict, dict]:
    context = _context(db, payload.product_id, payload.route_operation_id, payload.machine_id, payload.production_date)
    data = payload.model_dump()
    cycle = context["cycle"]
    if cycle:
        master_cycle = Decimal(cycle.ideal_cycle_time_sec)
        if payload.ideal_cycle_time_sec > 0 and payload.ideal_cycle_time_sec != master_cycle:
            context["warnings"].append("Entered cycle time was replaced by the effective master cycle time")
        data["ideal_cycle_time_sec"] = master_cycle
    elif payload.ideal_cycle_time_sec <= 0:
        raise HTTPException(422, "Effective ideal cycle time is missing; add it in Masters before calculating OEE")
    if payload.total_count > payload.good_count + payload.reject_count:
        context["warnings"].append("Total count is not fully classified as good or reject")
    return data, context


def _entry_json(row: MachineShiftProduction, context: dict | None = None) -> dict:
    result = {
        "id": row.id, "production_date": row.production_date, "shift": row.shift,
        "product_id": row.product_id, "route_operation_id": row.route_operation_id,
        "machine_id": row.machine_id, "shift_duration_min": float(row.shift_duration_min),
        "planned_break_min": float(row.planned_break_min), "downtime_min": float(row.downtime_min),
        "total_count": float(row.total_count), "good_count": float(row.good_count),
        "reject_count": float(row.reject_count), "ideal_cycle_time_sec": float(row.ideal_cycle_time_sec),
        "remarks": row.remarks,
        **calculate_oee(row.shift_duration_min, row.planned_break_min, row.downtime_min,
                        row.total_count, row.good_count, row.ideal_cycle_time_sec),
    }
    if context:
        result.update({
            "product": context["product"].name, "machine": context["machine"].code,
            "operation": context["operation"].name, "data_quality_warnings": context["warnings"],
        })
    return result


@router.get("/available-machines")
def available_machines(route_operation_id: int, production_date: date,
                       db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    route = db.get(RouteOperation, route_operation_id)
    if not route:
        raise HTTPException(404, "Product operation not found")
    rows = db.execute(
        select(OperationMachineMap, Machine).join(Machine, Machine.id == OperationMachineMap.machine_id).where(
            OperationMachineMap.route_operation_id == route_operation_id,
            OperationMachineMap.is_active.is_(True), Machine.is_active.is_(True),
            OperationMachineMap.effective_from <= production_date,
            or_(OperationMachineMap.effective_to.is_(None), OperationMachineMap.effective_to >= production_date),
        ).order_by(OperationMachineMap.priority, Machine.code)
    ).all()
    if rows:
        return {"mapped": True, "machines": [{"id": m.id, "code": m.code, "name": m.name} for _, m in rows]}
    machines = db.scalars(select(Machine).where(Machine.is_active.is_(True)).order_by(Machine.code)).all()
    return {"mapped": False, "warning": "No machine mapping exists; showing all active machines",
            "machines": [{"id": m.id, "code": m.code, "name": m.name} for m in machines]}


@router.get("/entry-context")
def entry_context(product_id: int, route_operation_id: int, machine_id: int, production_date: date,
                  shift: str = "A", db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    context = _context(db, product_id, route_operation_id, machine_id, production_date)
    existing = db.scalar(select(MachineShiftProduction).where(
        MachineShiftProduction.production_date == production_date,
        MachineShiftProduction.shift == shift.strip().upper(),
        MachineShiftProduction.product_id == product_id,
        MachineShiftProduction.route_operation_id == route_operation_id,
        MachineShiftProduction.machine_id == machine_id,
    ).order_by(MachineShiftProduction.id.desc()).limit(1))
    return {
        "product": context["product"].name, "operation": context["operation"].name,
        "machine": context["machine"].code, "allowed_machine_ids": context["allowed_machine_ids"],
        "ideal_cycle_time_sec": float(context["cycle"].ideal_cycle_time_sec) if context["cycle"] else None,
        "warnings": context["warnings"], "existing_entry": _entry_json(existing, context) if existing else None,
    }


@router.post("/machine-entry")
def save_machine_entry(payload: MachineEntryCreate, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    duplicate = db.scalar(select(MachineShiftProduction.id).where(
        MachineShiftProduction.production_date == payload.production_date,
        MachineShiftProduction.shift == payload.shift,
        MachineShiftProduction.product_id == payload.product_id,
        MachineShiftProduction.route_operation_id == payload.route_operation_id,
        MachineShiftProduction.machine_id == payload.machine_id,
    ).limit(1))
    if duplicate:
        raise HTTPException(409, f"This machine shift entry already exists as #{duplicate}; load and correct it instead of duplicating it")
    data, context = _prepare_entry(db, payload)
    row = MachineShiftProduction(**data)
    db.add(row); db.commit(); db.refresh(row)
    return {"entry": _entry_json(row, context), "warnings": context["warnings"]}


@router.put("/machine-entry/{entry_id}")
def update_machine_entry(entry_id: int, payload: MachineEntryCreate, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    row = db.get(MachineShiftProduction, entry_id)
    if not row:
        raise HTTPException(404, "Machine shift entry not found")
    if not db.info.get("reason"):
        raise HTTPException(422, "Enter a correction reason before updating an OEE entry")
    duplicate = db.scalar(select(MachineShiftProduction.id).where(
        MachineShiftProduction.production_date == payload.production_date,
        MachineShiftProduction.shift == payload.shift,
        MachineShiftProduction.product_id == payload.product_id,
        MachineShiftProduction.route_operation_id == payload.route_operation_id,
        MachineShiftProduction.machine_id == payload.machine_id,
        MachineShiftProduction.id != entry_id,
    ).limit(1))
    if duplicate:
        raise HTTPException(409, f"Another matching machine shift entry already exists as #{duplicate}")
    data, context = _prepare_entry(db, payload)
    for key, value in data.items():
        setattr(row, key, value)
    db.commit(); db.refresh(row)
    return {"entry": _entry_json(row, context), "warnings": context["warnings"]}


def _validate_loss(db: Session, payload: LossEventCreate) -> tuple[dict, LossCategory]:
    if payload.product_id is not None and payload.route_operation_id is not None:
        _context(db, payload.product_id, payload.route_operation_id, payload.machine_id, payload.loss_date)
    elif not db.get(Machine, payload.machine_id):
        raise HTTPException(404, "Machine not found")
    category = db.get(LossCategory, payload.loss_category_id)
    if not category or not category.is_active:
        raise HTTPException(422, "Select an active loss category")
    return payload.model_dump(), category


@router.post("/loss-events")
def save_loss(payload: LossEventCreate, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    data, category = _validate_loss(db, payload)
    row = MachineLossEvent(**data)
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id, "category": category.name, "component": category.oee_component.value}


@router.put("/loss-events/{loss_id}")
def update_loss(loss_id: int, payload: LossEventCreate, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    row = db.get(MachineLossEvent, loss_id)
    if not row:
        raise HTTPException(404, "Loss event not found")
    if not db.info.get("reason"):
        raise HTTPException(422, "Enter a correction reason before updating a loss event")
    data, category = _validate_loss(db, payload)
    for key, value in data.items():
        setattr(row, key, value)
    db.commit(); db.refresh(row)
    return {"id": row.id, "category": category.name, "component": category.oee_component.value}


def _summary(db: Session, machine_id: int, summary_date: date, shift: str | None,
             product_id: int | None, route_operation_id: int | None) -> dict:
    q = select(MachineShiftProduction).where(
        MachineShiftProduction.machine_id == machine_id,
        MachineShiftProduction.production_date == summary_date,
    )
    loss_q = select(MachineLossEvent).where(
        MachineLossEvent.machine_id == machine_id,
        MachineLossEvent.loss_date == summary_date,
    )
    if shift:
        q = q.where(MachineShiftProduction.shift == shift)
        loss_q = loss_q.where(MachineLossEvent.shift == shift)
    if product_id is not None:
        q = q.where(MachineShiftProduction.product_id == product_id)
        loss_q = loss_q.where(MachineLossEvent.product_id == product_id)
    if route_operation_id is not None:
        q = q.where(MachineShiftProduction.route_operation_id == route_operation_id)
        loss_q = loss_q.where(MachineLossEvent.route_operation_id == route_operation_id)
    rows = db.scalars(q.order_by(MachineShiftProduction.id)).all()
    losses = db.scalars(loss_q.order_by(MachineLossEvent.id)).all()

    categories = {x.id: x for x in db.scalars(select(LossCategory)).all()}
    action_rows = db.execute(
        select(ActionContext.loss_event_id, Action).join(Action, Action.id == ActionContext.action_id)
        .where(ActionContext.loss_event_id.in_([x.id for x in losses] or [-1]))
        .order_by(Action.id.desc())
    ).all()
    loss_actions: dict[int, Action] = {}
    for loss_event_id, action in action_rows:
        loss_actions.setdefault(loss_event_id, action)

    summary = None
    if rows:
        shift_duration = sum(float(x.shift_duration_min) for x in rows)
        planned_break = sum(float(x.planned_break_min) for x in rows)
        downtime = sum(float(x.downtime_min) for x in rows)
        total_count = sum(float(x.total_count) for x in rows)
        good_count = sum(float(x.good_count) for x in rows)
        denom = total_count or 1
        ideal_weighted = sum(float(x.ideal_cycle_time_sec) * float(x.total_count) for x in rows) / denom
        summary = calculate_oee(shift_duration, planned_break, downtime, total_count, good_count, ideal_weighted)
        availability_loss = sum(float(x.duration_min) for x in losses
                                if categories.get(x.loss_category_id) and categories[x.loss_category_id].oee_component == OEEComponent.AVAILABILITY)
        summary["captured_loss_min"] = availability_loss
        summary["unclassified_loss_min"] = max(0.0, downtime - availability_loss)
        summary["overclassified_loss_min"] = max(0.0, availability_loss - downtime)
        summary["reject_or_unaccounted_count"] = max(0.0, total_count - good_count)

    entry_data = []
    for row in rows:
        try:
            ctx = _context(db, row.product_id, row.route_operation_id, row.machine_id, row.production_date)
        except HTTPException:
            ctx = None
        entry_data.append(_entry_json(row, ctx))
    loss_data = []
    for row in losses:
        category = categories.get(row.loss_category_id)
        action = loss_actions.get(row.id)
        loss_data.append({
            "id": row.id, "loss_category_id": row.loss_category_id,
            "category": category.name if category else f"Loss #{row.loss_category_id}",
            "component": category.oee_component.value if category else None,
            "duration_min": float(row.duration_min), "qty_loss": float(row.qty_loss),
            "start_time": row.start_time, "end_time": row.end_time, "remark": row.remark,
            "action_id": action.id if action else None, "action_no": action.action_no if action else None,
            "action_status": action.status.value if action else None,
        })
    return {
        "machine_id": machine_id, "date": summary_date, "shift": shift,
        "product_id": product_id, "route_operation_id": route_operation_id,
        "entries": entry_data, "summary": summary, "losses": loss_data,
    }


@router.get("/management-summary")
def management_summary(from_date: date, to_date: date, machine_id: int | None = None,
                       product_id: int | None = None, target_oee: float = 0.85,
                       recurring_event_threshold: int = 3, db: Session = Depends(get_db),
                       _: User = Depends(get_current_user)):
    if to_date < from_date:
        raise HTTPException(422, "to_date must be on or after from_date")
    q = select(MachineShiftProduction).where(
        MachineShiftProduction.production_date >= from_date,
        MachineShiftProduction.production_date <= to_date,
    )
    lq = select(MachineLossEvent).where(
        MachineLossEvent.loss_date >= from_date, MachineLossEvent.loss_date <= to_date,
    )
    if machine_id is not None:
        q = q.where(MachineShiftProduction.machine_id == machine_id)
        lq = lq.where(MachineLossEvent.machine_id == machine_id)
    if product_id is not None:
        q = q.where(MachineShiftProduction.product_id == product_id)
        lq = lq.where(MachineLossEvent.product_id == product_id)
    rows = db.scalars(q.order_by(MachineShiftProduction.production_date, MachineShiftProduction.id)).all()
    losses = db.scalars(lq.order_by(MachineLossEvent.loss_date, MachineLossEvent.id)).all()
    machines = {x.id: x for x in db.scalars(select(Machine)).all()}
    categories = {x.id: x for x in db.scalars(select(LossCategory)).all()}

    def aggregate(items):
        if not items:
            return calculate_oee(0, 0, 0, 0, 0, 0)
        shift_duration = sum(float(x.shift_duration_min) for x in items)
        planned_break = sum(float(x.planned_break_min) for x in items)
        downtime = sum(float(x.downtime_min) for x in items)
        total = sum(float(x.total_count) for x in items)
        good = sum(float(x.good_count) for x in items)
        weighted_cycle = sum(float(x.ideal_cycle_time_sec) * float(x.total_count) for x in items) / (total or 1)
        return calculate_oee(shift_duration, planned_break, downtime, total, good, weighted_cycle)

    by_day = {}
    by_machine = {}
    for row in rows:
        by_day.setdefault(row.production_date, []).append(row)
        by_machine.setdefault(row.machine_id, []).append(row)
    trend = [{"date": day, **aggregate(items)} for day, items in sorted(by_day.items())]
    machine_summary = []
    for mid, items in by_machine.items():
        metric = aggregate(items)
        status = "ON TARGET" if metric["oee_reported"] >= target_oee else "BELOW TARGET"
        machine_summary.append({"machine_id": mid, "machine": machines[mid].code if mid in machines else str(mid),
                                "entry_count": len(items), "status": status,
                                "gap_to_target": max(0.0, target_oee - metric["oee_reported"]), **metric})
    machine_summary.sort(key=lambda x: x["oee_reported"])

    pareto = {}
    for loss in losses:
        category = categories.get(loss.loss_category_id)
        name = category.name if category else f"Loss #{loss.loss_category_id}"
        item = pareto.setdefault(name, {"category": name, "component": category.oee_component.value if category else None,
                                       "minutes": 0.0, "qty_loss": 0.0, "events": 0})
        item["minutes"] += float(loss.duration_min)
        item["qty_loss"] += float(loss.qty_loss)
        item["events"] += 1
    loss_pareto = sorted(pareto.values(), key=lambda x: (x["minutes"], x["events"]), reverse=True)
    recurring_losses = [x for x in loss_pareto if x["events"] >= recurring_event_threshold]
    overall = aggregate(rows)
    below_target = [x for x in machine_summary if x["status"] == "BELOW TARGET"]
    return {"from_date": from_date, "to_date": to_date, "target_oee": target_oee,
            "entry_count": len(rows), "loss_event_count": len(losses),
            "below_target_machine_count": len(below_target), "recurring_loss_count": len(recurring_losses),
            "overall": overall, "trend": trend, "machines": machine_summary,
            "loss_pareto": loss_pareto, "recurring_losses": recurring_losses}


@router.get("/machine-summary")
def machine_summary(machine_id: int, summary_date: date, shift: str | None = None,
                    product_id: int | None = None, route_operation_id: int | None = None,
                    db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return _summary(db, machine_id, summary_date, shift, product_id, route_operation_id)


def _add_review_link(db: Session, action: Action) -> None:
    active = db.scalar(select(ReviewSession).where(
        ReviewSession.review_date == action.reference_date, ReviewSession.ended_at.is_(None),
    ).order_by(ReviewSession.id.desc()).limit(1))
    if active:
        db.add(ReviewActionLink(review_session_id=active.id, action_id=action.id))


def _new_action(db: Session, user: User, *, reference_date: date, product_id: int | None,
                route_operation_id: int | None, machine_id: int, loss_event_id: int | None,
                payload: OEEActionCreate, problem_category: str, problem_description: str,
                kpi_type: str, kpi_value: Decimal, gap: Decimal) -> Action:
    action = Action(
        action_no=f"ACT-{reference_date.year}-{db.query(Action).count() + 1:05d}",
        reference_date=reference_date, problem_category=problem_category,
        problem_description=problem_description, action_description=payload.action_description,
        owner_id=payload.owner_id, due_at=payload.due_at, priority=payload.priority,
        kpi_type=kpi_type, kpi_value_when_raised=kpi_value, gap_when_raised=gap,
    )
    db.add(action); db.flush()
    db.add(ActionContext(action_id=action.id, context_date=reference_date, product_id=product_id,
                         route_operation_id=route_operation_id, machine_id=machine_id,
                         loss_event_id=loss_event_id))
    db.add(ActionWhyWhy(action_id=action.id, containment_action=payload.action_description, updated_by_id=user.id))
    db.add(ActionHistory(action_id=action.id, changed_by_id=user.id, new_status=action.status,
                         comment="Action raised from Machine / OEE; standard Why-Why plan opened"))
    _add_review_link(db, action)
    db.commit(); db.refresh(action)
    return action


@router.post("/loss-events/{loss_id}/raise-action")
def raise_loss_action(loss_id: int, payload: OEEActionCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    loss = db.get(MachineLossEvent, loss_id)
    if not loss:
        raise HTTPException(404, "Loss event not found")
    existing = db.execute(
        select(Action).join(ActionContext, ActionContext.action_id == Action.id)
        .where(ActionContext.loss_event_id == loss_id).order_by(Action.id.desc()).limit(1)
    ).scalar_one_or_none()
    if existing:
        return {"status": "already_linked", "action_id": existing.id, "action_no": existing.action_no}
    category = db.get(LossCategory, loss.loss_category_id)
    machine = db.get(Machine, loss.machine_id)
    description = f"{category.name if category else 'Machine loss'} on {machine.code if machine else 'machine'}: {float(loss.duration_min):g} min"
    if loss.remark:
        description += f" — {loss.remark}"
    action = _new_action(
        db, user, reference_date=loss.loss_date, product_id=loss.product_id,
        route_operation_id=loss.route_operation_id, machine_id=loss.machine_id,
        loss_event_id=loss.id, payload=payload, problem_category="OEE / Machine Loss",
        problem_description=description, kpi_type="OEE_LOSS_MIN",
        kpi_value=Decimal(loss.duration_min), gap=Decimal(loss.duration_min),
    )
    return {"status": "created", "action_id": action.id, "action_no": action.action_no}


@router.post("/raise-action")
def raise_oee_action(payload: OEESummaryActionCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    summary_data = _summary(db, payload.machine_id, payload.production_date, payload.shift.strip().upper(),
                            payload.product_id, payload.route_operation_id)
    summary = summary_data["summary"]
    if not summary:
        raise HTTPException(422, "Save the machine shift entry before raising an OEE action")
    existing = db.execute(
        select(Action).join(ActionContext, ActionContext.action_id == Action.id).where(
            Action.reference_date == payload.production_date, Action.kpi_type == "OEE",
            Action.status != ActionStatus.CLOSED, ActionContext.machine_id == payload.machine_id,
            ActionContext.product_id == payload.product_id,
            ActionContext.route_operation_id == payload.route_operation_id,
            ActionContext.loss_event_id.is_(None),
        ).order_by(Action.id.desc()).limit(1)
    ).scalar_one_or_none()
    if existing:
        return {"status": "already_linked", "action_id": existing.id, "action_no": existing.action_no}
    machine = db.get(Machine, payload.machine_id)
    oee_value = Decimal(str(summary["oee_reported"]))
    gap = max(Decimal("0"), payload.target_oee - oee_value)
    description = (
        f"{machine.code if machine else 'Machine'} shift {payload.shift.upper()} OEE "
        f"{float(oee_value) * 100:.1f}% against {float(payload.target_oee) * 100:.1f}% target"
    )
    if summary.get("unclassified_loss_min", 0) > 0:
        description += f"; {summary['unclassified_loss_min']:.1f} downtime minutes are not classified"
    action = _new_action(
        db, user, reference_date=payload.production_date, product_id=payload.product_id,
        route_operation_id=payload.route_operation_id, machine_id=payload.machine_id,
        loss_event_id=None, payload=payload, problem_category="OEE / Low OEE",
        problem_description=description, kpi_type="OEE", kpi_value=oee_value, gap=gap,
    )
    return {"status": "created", "action_id": action.id, "action_no": action.action_no}
