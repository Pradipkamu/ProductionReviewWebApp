from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_FLOOR

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models import (
    DailyRequirement, Machine, MachineCapacitySetting, MachineMonthlyAllocation,
    Operation, OperationMachineMap, OperatorRequirementHistory, Product,
    RouteOperation, RouteVersion, StandardCycleTime,
)
from .planning import month_bounds, product_plant, working_days

ZERO = Decimal("0")


def close_previous_revision(db: Session, model, effective_from: date, *filters) -> None:
    latest = db.scalar(select(model).where(*filters).order_by(model.effective_from.desc(), model.id.desc()).limit(1))
    if latest and latest.effective_from >= effective_from:
        raise HTTPException(409, "Effective date must be later than the latest saved revision")
    if latest and (latest.effective_to is None or latest.effective_to >= effective_from):
        latest.effective_to = effective_from - timedelta(days=1)


def _effective(db: Session, model, on_date: date, *filters):
    return db.scalar(select(model).where(
        *filters,
        model.effective_from <= on_date,
        or_(model.effective_to.is_(None), model.effective_to >= on_date),
    ).order_by(model.effective_from.desc(), model.id.desc()).limit(1))


def effective_cycle(db: Session, route_operation_id: int, machine_id: int, on_date: date):
    return db.scalar(select(StandardCycleTime).where(
        StandardCycleTime.route_operation_id == route_operation_id,
        or_(StandardCycleTime.machine_id == machine_id, StandardCycleTime.machine_id.is_(None)),
        StandardCycleTime.effective_from <= on_date,
        or_(StandardCycleTime.effective_to.is_(None), StandardCycleTime.effective_to >= on_date),
    ).order_by(StandardCycleTime.machine_id.is_(None), StandardCycleTime.effective_from.desc(), StandardCycleTime.id.desc()).limit(1))


def effective_operator(db: Session, route_operation_id: int, machine_id: int, on_date: date):
    return db.scalar(select(OperatorRequirementHistory).where(
        OperatorRequirementHistory.route_operation_id == route_operation_id,
        or_(OperatorRequirementHistory.machine_id == machine_id, OperatorRequirementHistory.machine_id.is_(None)),
        OperatorRequirementHistory.effective_from <= on_date,
        or_(OperatorRequirementHistory.effective_to.is_(None), OperatorRequirementHistory.effective_to >= on_date),
    ).order_by(OperatorRequirementHistory.machine_id.is_(None), OperatorRequirementHistory.effective_from.desc(), OperatorRequirementHistory.id.desc()).limit(1))


def effective_machine_setting(db: Session, machine_id: int, on_date: date):
    return _effective(db, MachineCapacitySetting, on_date, MachineCapacitySetting.machine_id == machine_id)


def machine_month_capacity(db: Session, product: Product, route_operation_id: int, machine: Machine,
                           month: date, mappings: list[OperationMachineMap]) -> dict:
    first, last = month_bounds(month)
    days = working_days(db, first, last, product_plant(db, product.id))
    capacity = ZERO
    gross_hours = ZERO
    operator_capacity_weight = ZERO
    cycle_capacity_weight = ZERO
    covered_days = 0
    mapped_days = 0
    missing: set[str] = set()
    cycle_ids: set[int] = set()
    operator_ids: set[int] = set()
    setting_ids: set[int] = set()

    for day in days:
        mapping = next((item for item in mappings if item.effective_from <= day and
                        (item.effective_to is None or item.effective_to >= day)), None)
        if mapping is None:
            continue
        mapped_days += 1
        cycle = effective_cycle(db, route_operation_id, machine.id, day)
        operator = effective_operator(db, route_operation_id, machine.id, day)
        setting = effective_machine_setting(db, machine.id, day)
        if not cycle:
            missing.add("Cycle time")
        if not operator:
            missing.add("Operator requirement")
        if not setting:
            missing.add("Machine capacity setting")
        if not cycle or not operator or not setting:
            continue
        net_minutes = Decimal(setting.shift_minutes) - Decimal(setting.planned_break_minutes)
        if net_minutes <= 0:
            missing.add("Valid shift minutes")
            continue
        planning_cycle = Decimal(cycle.standard_cycle_time_sec or cycle.ideal_cycle_time_sec)
        if planning_cycle <= 0:
            missing.add("Valid cycle time")
            continue
        pieces = Decimal(max(1, int(cycle.pieces_per_cycle or 1)))
        efficiency = Decimal(setting.planning_efficiency)
        day_gross_hours = net_minutes * Decimal(setting.shifts_per_day) / Decimal(60)
        day_effective_seconds = day_gross_hours * Decimal(3600) * efficiency
        day_capacity = day_effective_seconds / planning_cycle * pieces
        capacity += day_capacity
        gross_hours += day_gross_hours
        operator_capacity_weight += day_capacity * Decimal(operator.operators_per_machine)
        cycle_capacity_weight += day_capacity * planning_cycle / pieces
        covered_days += 1
        cycle_ids.add(cycle.id); operator_ids.add(operator.id); setting_ids.add(setting.id)

    complete = covered_days == mapped_days and not missing and mapped_days > 0
    if not complete:
        capacity = ZERO
    operator_avg = operator_capacity_weight / capacity if capacity > 0 else ZERO
    cycle_avg = cycle_capacity_weight / capacity if capacity > 0 else ZERO
    return {
        "machine_id": machine.id, "machine_code": machine.code, "machine_name": machine.name,
        "priority": mappings[0].priority, "mapping_id": mappings[0].id,
        "working_days": len(days), "mapped_days": mapped_days, "covered_days": covered_days, "complete": complete,
        "missing": sorted(missing), "capacity_qty": float(capacity),
        "gross_available_hours": float(gross_hours),
        "planning_cycle_time_sec": float(cycle_avg),
        "operators_per_machine": float(operator_avg),
        "cycle_revision_ids": sorted(cycle_ids), "operator_revision_ids": sorted(operator_ids),
        "capacity_setting_ids": sorted(setting_ids),
    }


def _operation_schedule(db: Session, product_id: int, month: date) -> dict[int, Decimal]:
    first, last = month_bounds(month)
    rows = db.execute(select(
        DailyRequirement.route_operation_id,
        func.coalesce(func.sum(DailyRequirement.revised_plan_qty), 0),
    ).where(
        DailyRequirement.product_id == product_id,
        DailyRequirement.route_operation_id.is_not(None),
        DailyRequirement.req_date >= first,
        DailyRequirement.req_date <= last,
    ).group_by(DailyRequirement.route_operation_id)).all()
    return {int(op_id): Decimal(str(qty or 0)) for op_id, qty in rows}


def _product_operations(db: Session, product_id: int, month: date, scheduled: dict[int, Decimal]):
    first, last = month_bounds(month)
    ids = set(scheduled)
    route_ids = db.scalars(select(RouteVersion.id).where(
        RouteVersion.product_id == product_id,
        RouteVersion.effective_from <= last,
        or_(RouteVersion.effective_to.is_(None), RouteVersion.effective_to >= first),
        RouteVersion.is_active.is_(True),
    )).all()
    if route_ids:
        ids.update(db.scalars(select(RouteOperation.id).where(
            RouteOperation.route_version_id.in_(route_ids), RouteOperation.is_enabled.is_(True)
        )).all())
    if not ids:
        return []
    return db.execute(select(RouteOperation, Operation).join(Operation).where(
        RouteOperation.id.in_(ids)
    ).order_by(RouteOperation.sequence_no, Operation.name)).all()


def _latest_saved(db: Session, product_id: int, route_operation_id: int, month: date):
    revision = db.scalar(select(func.max(MachineMonthlyAllocation.revision_no)).where(
        MachineMonthlyAllocation.product_id == product_id,
        MachineMonthlyAllocation.route_operation_id == route_operation_id,
        MachineMonthlyAllocation.month == month.replace(day=1),
    ))
    if revision is None:
        return None, {}
    rows = db.scalars(select(MachineMonthlyAllocation).where(
        MachineMonthlyAllocation.product_id == product_id,
        MachineMonthlyAllocation.route_operation_id == route_operation_id,
        MachineMonthlyAllocation.month == month.replace(day=1),
        MachineMonthlyAllocation.revision_no == revision,
    )).all()
    return int(revision), {x.machine_id: Decimal(x.allocated_qty) for x in rows}


def _suggest(schedule_qty: Decimal, machines: list[dict]) -> dict[int, Decimal]:
    remaining = max(ZERO, schedule_qty)
    result: dict[int, Decimal] = {x["machine_id"]: ZERO for x in machines}
    usable = [x for x in machines if x["complete"] and Decimal(str(x["capacity_qty"])) > 0]
    for item in sorted(usable, key=lambda x: (x["priority"], x["machine_code"])):
        qty = min(remaining, Decimal(str(item["capacity_qty"])).quantize(Decimal("1"), rounding=ROUND_FLOOR))
        result[item["machine_id"]] = qty
        remaining -= qty
    if remaining > 0 and usable:
        result[usable[0]["machine_id"]] += remaining
    return result


def capacity_plan(db: Session, product_id: int, month: date) -> dict:
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    first, last = month_bounds(month)
    scheduled = _operation_schedule(db, product_id, first)
    operation_rows = []
    for route_operation, operation in _product_operations(db, product_id, first, scheduled):
        maps = db.execute(select(OperationMachineMap, Machine).join(Machine).where(
            OperationMachineMap.route_operation_id == route_operation.id,
            OperationMachineMap.is_active.is_(True), Machine.is_active.is_(True),
            OperationMachineMap.effective_from <= last,
            or_(OperationMachineMap.effective_to.is_(None), OperationMachineMap.effective_to >= first),
        ).order_by(Machine.code, OperationMachineMap.effective_from.desc(), OperationMachineMap.id.desc())).all()
        mapping_groups: dict[int, tuple[Machine, list[OperationMachineMap]]] = {}
        for mapping, machine in maps:
            mapping_groups.setdefault(machine.id, (machine, []))[1].append(mapping)
        machine_rows = [
            machine_month_capacity(db, product, route_operation.id, machine, first, mappings)
            for machine, mappings in mapping_groups.values()
        ]
        machine_rows.sort(key=lambda item: (item["priority"], item["machine_code"]))
        schedule_qty = scheduled.get(route_operation.id, ZERO)
        revision, saved = _latest_saved(db, product_id, route_operation.id, first)
        allocations = saved if revision is not None else _suggest(schedule_qty, machine_rows)
        for item in machine_rows:
            allocated = allocations.get(item["machine_id"], ZERO)
            capacity = Decimal(str(item["capacity_qty"]))
            load = allocated / capacity if capacity > 0 else ZERO
            gross_hours = Decimal(str(item["gross_available_hours"]))
            op_rate = Decimal(str(item["operators_per_machine"]))
            item.update(
                allocation_qty=float(allocated), load_percent=float(load * 100),
                required_machine_hours=float(gross_hours * load),
                operator_hours=float(gross_hours * load * op_rate),
                average_operators=float(load * op_rate),
                operators_required=math.ceil(float(load * op_rate)) if allocated > 0 else 0,
            )
        allocated_total = sum((Decimal(str(x["allocation_qty"])) for x in machine_rows), ZERO)
        operation_rows.append({
            "route_operation_id": route_operation.id, "operation_id": operation.id,
            "sequence_no": route_operation.sequence_no, "operation": operation.name,
            "schedule_qty": float(schedule_qty), "allocation_revision": revision,
            "allocation_source": "SAVED" if revision is not None else "SUGGESTED",
            "allocated_qty": float(allocated_total), "allocation_gap": float(schedule_qty - allocated_total),
            "total_capacity_qty": sum(x["capacity_qty"] for x in machine_rows),
            "operators_required": math.ceil(sum(x["average_operators"] for x in machine_rows)),
            "machines": machine_rows,
        })
    return {
        "month": first.isoformat(), "product_id": product.id, "product": product.name,
        "plant": product_plant(db, product.id),
        "working_days": len(working_days(db, first, last, product_plant(db, product.id))),
        "operations": operation_rows,
    }


def save_allocation(db: Session, payload, user_id: int) -> dict:
    plan = capacity_plan(db, payload.product_id, payload.month)
    operation = next((x for x in plan["operations"] if x["route_operation_id"] == payload.route_operation_id), None)
    if not operation:
        raise HTTPException(422, "Product operation is not active in this month")
    supplied = {x.machine_id: Decimal(x.allocated_qty) for x in payload.allocations}
    valid = {x["machine_id"]: x for x in operation["machines"]}
    unknown = set(supplied) - set(valid)
    if unknown:
        raise HTTPException(422, f"Machine(s) not mapped for this part operation: {sorted(unknown)}")
    total = sum(supplied.values(), ZERO)
    schedule_qty = Decimal(str(operation["schedule_qty"]))
    if abs(total - schedule_qty) > Decimal("0.001"):
        raise HTTPException(422, f"Allocated quantity {total} must equal monthly operation schedule {schedule_qty}")
    revision = int(db.scalar(select(func.coalesce(func.max(MachineMonthlyAllocation.revision_no), 0)).where(
        MachineMonthlyAllocation.product_id == payload.product_id,
        MachineMonthlyAllocation.route_operation_id == payload.route_operation_id,
        MachineMonthlyAllocation.month == payload.month.replace(day=1),
    )) or 0) + 1
    for machine_id, qty in supplied.items():
        detail = valid[machine_id]
        if qty > 0 and not detail["complete"]:
            raise HTTPException(422, f"{detail['machine_code']} has incomplete capacity/cycle/operator masters")
        db.add(MachineMonthlyAllocation(
            month=payload.month.replace(day=1), effective_from=payload.effective_from,
            revision_no=revision, product_id=payload.product_id,
            route_operation_id=payload.route_operation_id, machine_id=machine_id,
            allocated_qty=qty, schedule_qty_snapshot=schedule_qty,
            capacity_qty_snapshot=Decimal(str(detail["capacity_qty"])),
            planning_cycle_time_sec=Decimal(str(detail["planning_cycle_time_sec"] or 0)),
            operators_per_machine_snapshot=Decimal(str(detail["operators_per_machine"] or 0)),
            reason=payload.reason, entered_by_id=user_id,
        ))
    db.flush()
    return {"revision_no": revision, "allocated_qty": float(total), "schedule_qty": float(schedule_qty)}
