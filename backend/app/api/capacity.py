from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..models import (
    Machine, MachineCapacitySetting, MachineMonthlyAllocation, Operation,
    OperatorRequirementHistory, Product, RouteOperation, RouteVersion, User,
)
from ..schemas import MachineAllocationCreate, MachineCapacitySettingCreate, OperatorRequirementCreate
from ..services.capacity import capacity_plan, close_previous_revision, machine_loading_summary, save_allocation

router = APIRouter(prefix="/capacity", tags=["capacity"])


@router.get("/plan")
def plan(product_id: int, month: date, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return capacity_plan(db, product_id, month)


@router.get("/machine-loading")
def machine_loading(month: date, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return machine_loading_summary(db, month)


@router.post("/allocations")
def create_allocation(payload: MachineAllocationCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    db.info["reason"] = payload.reason
    result = save_allocation(db, payload, user.id)
    db.commit()
    return result


@router.get("/allocations/history")
def allocation_history(product_id: int, route_operation_id: int, month: date,
                       db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rows = db.execute(select(MachineMonthlyAllocation, Machine, User).join(Machine).outerjoin(
        User, User.id == MachineMonthlyAllocation.entered_by_id
    ).where(
        MachineMonthlyAllocation.product_id == product_id,
        MachineMonthlyAllocation.route_operation_id == route_operation_id,
        MachineMonthlyAllocation.month == month.replace(day=1),
    ).order_by(MachineMonthlyAllocation.revision_no.desc(), Machine.code)).all()
    return [{
        "id": row.id, "revision_no": row.revision_no, "effective_from": row.effective_from,
        "machine_id": machine.id, "machine": machine.code, "allocated_qty": float(row.allocated_qty),
        "schedule_qty": float(row.schedule_qty_snapshot), "capacity_qty": float(row.capacity_qty_snapshot),
        "cycle_time_sec": float(row.planning_cycle_time_sec),
        "operators_per_machine": float(row.operators_per_machine_snapshot),
        "estimated_hourly_cost": float(row.estimated_hourly_cost_snapshot) if row.estimated_hourly_cost_snapshot is not None else None,
        "estimated_cost_per_piece": float(row.estimated_cost_per_piece_snapshot) if row.estimated_cost_per_piece_snapshot is not None else None,
        "reason": row.reason, "entered_by_id": row.entered_by_id,
        "entered_by": user.full_name if user else None, "created_at": row.created_at,
    } for row, machine, user in rows]


@router.post("/operator-requirements")
def create_operator_requirement(payload: OperatorRequirementCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not db.get(RouteOperation, payload.route_operation_id):
        raise HTTPException(404, "Product operation not found")
    if payload.machine_id is not None and not db.get(Machine, payload.machine_id):
        raise HTTPException(404, "Machine not found")
    filters = [OperatorRequirementHistory.route_operation_id == payload.route_operation_id]
    filters.append(OperatorRequirementHistory.machine_id == payload.machine_id if payload.machine_id is not None else OperatorRequirementHistory.machine_id.is_(None))
    close_previous_revision(db, OperatorRequirementHistory, payload.effective_from, *filters)
    db.info["reason"] = payload.reason
    row = OperatorRequirementHistory(**payload.model_dump(), entered_by_id=user.id)
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id, "effective_from": row.effective_from, "operators_per_machine": float(row.operators_per_machine)}


@router.post("/machine-settings")
def create_machine_setting(payload: MachineCapacitySettingCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not db.get(Machine, payload.machine_id):
        raise HTTPException(404, "Machine not found")
    close_previous_revision(db, MachineCapacitySetting, payload.effective_from,
                            MachineCapacitySetting.machine_id == payload.machine_id)
    db.info["reason"] = payload.reason
    row = MachineCapacitySetting(**payload.model_dump(), entered_by_id=user.id)
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id, "effective_from": row.effective_from}


@router.get("/master-history")
def master_history(route_operation_id: int | None = None, machine_id: int | None = None,
                   db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    from ..models import OperationMachineMap, StandardCycleTime
    maps_q = select(OperationMachineMap, Machine, User).join(Machine).outerjoin(User, User.id == OperationMachineMap.entered_by_id)
    cycles_q = select(StandardCycleTime, Machine, User).outerjoin(Machine, Machine.id == StandardCycleTime.machine_id).outerjoin(User, User.id == StandardCycleTime.entered_by_id)
    operators_q = select(OperatorRequirementHistory, Machine, User).outerjoin(Machine, Machine.id == OperatorRequirementHistory.machine_id).outerjoin(User, User.id == OperatorRequirementHistory.entered_by_id)
    settings_q = select(MachineCapacitySetting, Machine, User).join(Machine).outerjoin(User, User.id == MachineCapacitySetting.entered_by_id)
    if route_operation_id is not None:
        maps_q = maps_q.where(OperationMachineMap.route_operation_id == route_operation_id)
        cycles_q = cycles_q.where(StandardCycleTime.route_operation_id == route_operation_id)
        operators_q = operators_q.where(OperatorRequirementHistory.route_operation_id == route_operation_id)
    if machine_id is not None:
        maps_q = maps_q.where(OperationMachineMap.machine_id == machine_id)
        cycles_q = cycles_q.where(or_(StandardCycleTime.machine_id == machine_id, StandardCycleTime.machine_id.is_(None)))
        operators_q = operators_q.where(or_(OperatorRequirementHistory.machine_id == machine_id, OperatorRequirementHistory.machine_id.is_(None)))
        settings_q = settings_q.where(MachineCapacitySetting.machine_id == machine_id)
    maps = db.execute(maps_q.order_by(OperationMachineMap.effective_from.desc(), OperationMachineMap.id.desc()).limit(200)).all()
    cycles = db.execute(cycles_q.order_by(StandardCycleTime.effective_from.desc(), StandardCycleTime.id.desc()).limit(200)).all()
    operators = db.execute(operators_q.order_by(OperatorRequirementHistory.effective_from.desc(), OperatorRequirementHistory.id.desc()).limit(200)).all()
    settings = db.execute(settings_q.order_by(MachineCapacitySetting.effective_from.desc(), MachineCapacitySetting.id.desc()).limit(200)).all()
    return {
        "machine_maps": [{"id": x.id, "machine": m.code, "machine_id": m.id, "effective_from": x.effective_from, "effective_to": x.effective_to, "priority": x.priority, "reason": x.reason, "entered_by_id": x.entered_by_id, "entered_by": u.full_name if u else None} for x, m, u in maps],
        "cycle_times": [{"id": x.id, "machine": m.code if m else "All mapped machines", "machine_id": x.machine_id, "effective_from": x.effective_from, "effective_to": x.effective_to, "ideal_cycle_time_sec": float(x.ideal_cycle_time_sec), "standard_cycle_time_sec": float(x.standard_cycle_time_sec) if x.standard_cycle_time_sec is not None else None, "pieces_per_cycle": x.pieces_per_cycle, "reason": x.reason or x.remark, "entered_by_id": x.entered_by_id, "entered_by": u.full_name if u else None} for x, m, u in cycles],
        "operator_requirements": [{"id": x.id, "machine": m.code if m else "All mapped machines", "machine_id": x.machine_id, "effective_from": x.effective_from, "effective_to": x.effective_to, "operators_per_machine": float(x.operators_per_machine), "reason": x.reason, "entered_by_id": x.entered_by_id, "entered_by": u.full_name if u else None} for x, m, u in operators],
        "machine_settings": [{"id": x.id, "machine": m.code, "machine_id": m.id, "effective_from": x.effective_from, "effective_to": x.effective_to, "shifts_per_day": x.shifts_per_day, "shift_minutes": float(x.shift_minutes), "planned_break_minutes": float(x.planned_break_minutes), "planning_efficiency": float(x.planning_efficiency), "reason": x.reason, "entered_by_id": x.entered_by_id, "entered_by": u.full_name if u else None} for x, m, u in settings],
    }
