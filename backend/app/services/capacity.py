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
from .machine_cost import machine_cost

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
    cost = machine_cost(machine, operator_avg if operator_avg > 0 else None)
    return {
        "machine_id": machine.id, "machine_code": machine.code, "machine_name": machine.name,
        "priority": mappings[0].priority, "mapping_id": mappings[0].id,
        "working_days": len(days), "mapped_days": mapped_days, "covered_days": covered_days, "complete": complete,
        "missing": sorted(missing), "capacity_qty": float(capacity),
        "gross_available_hours": float(gross_hours),
        "planning_cycle_time_sec": float(cycle_avg),
        "operators_per_machine": float(operator_avg),
        "estimated_hourly_cost": cost["estimated_hourly_cost"],
        "cost_complete": cost["cost_complete"], "cost_missing": cost["cost_missing"],
        "cost_components": cost["components"],
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


def _other_saved_machine_loads(
    db: Session,
    month: date,
    product_id: int,
    route_operation_id: int,
) -> dict[int, Decimal]:
    """Return machine load already committed by other latest allocation revisions.

    Load is expressed as a fraction of machine-month capacity, not as pieces.
    This is important because different products can have different cycle times
    on the same physical machine.
    """
    month = month.replace(day=1)
    rows = db.scalars(select(MachineMonthlyAllocation).where(
        MachineMonthlyAllocation.month == month,
    ).order_by(
        MachineMonthlyAllocation.product_id,
        MachineMonthlyAllocation.route_operation_id,
        MachineMonthlyAllocation.revision_no.desc(),
        MachineMonthlyAllocation.id.desc(),
    )).all()

    latest_revision: dict[tuple[int, int], int] = {}
    loads: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for row in rows:
        context = (row.product_id, row.route_operation_id)
        if context == (product_id, route_operation_id):
            continue
        if context not in latest_revision:
            latest_revision[context] = int(row.revision_no)
        if int(row.revision_no) != latest_revision[context]:
            continue
        capacity_snapshot = Decimal(str(row.capacity_qty_snapshot or 0))
        allocated = max(ZERO, Decimal(str(row.allocated_qty or 0)))
        if capacity_snapshot > 0 and allocated > 0:
            loads[row.machine_id] += allocated / capacity_snapshot
    return dict(loads)


def machine_loading_summary(db: Session, month: date) -> dict:
    """Consolidated physical-machine loading from latest saved monthly allocations.

    Quantities are not added across products because different parts can have
    different cycle times. Each saved allocation is converted to its machine-time
    load fraction using allocated_qty / capacity_qty_snapshot, then the fractions
    are summed for the physical machine.
    """
    month = month.replace(day=1)
    rows = db.execute(
        select(MachineMonthlyAllocation, Machine, Product, RouteOperation, Operation)
        .join(Machine, Machine.id == MachineMonthlyAllocation.machine_id)
        .join(Product, Product.id == MachineMonthlyAllocation.product_id)
        .join(RouteOperation, RouteOperation.id == MachineMonthlyAllocation.route_operation_id)
        .join(Operation, Operation.id == RouteOperation.operation_id)
        .where(MachineMonthlyAllocation.month == month)
        .order_by(
            MachineMonthlyAllocation.product_id,
            MachineMonthlyAllocation.route_operation_id,
            MachineMonthlyAllocation.revision_no.desc(),
            MachineMonthlyAllocation.id.desc(),
        )
    ).all()

    latest_revision: dict[tuple[int, int], int] = {}
    by_machine: dict[int, dict] = {}
    for allocation, machine, product, route_operation, operation in rows:
        context = (allocation.product_id, allocation.route_operation_id)
        if context not in latest_revision:
            latest_revision[context] = int(allocation.revision_no)
        if int(allocation.revision_no) != latest_revision[context]:
            continue

        capacity_snapshot = Decimal(str(allocation.capacity_qty_snapshot or 0))
        allocated = max(ZERO, Decimal(str(allocation.allocated_qty or 0)))
        load = allocated / capacity_snapshot if capacity_snapshot > 0 else ZERO

        row = by_machine.setdefault(machine.id, {
            "machine_id": machine.id,
            "machine_code": machine.code,
            "machine_name": machine.name,
            "plant": machine.plant,
            "department": machine.department,
            "is_active": machine.is_active,
            "load_fraction": ZERO,
            "operator_equivalent": ZERO,
            "operator_hours": ZERO,
            "allocations": [],
        })
        row["load_fraction"] += load
        operator_rate = Decimal(str(allocation.operators_per_machine_snapshot or 0))
        cycle_seconds = Decimal(str(allocation.planning_cycle_time_sec or 0))
        runtime_hours = allocated * cycle_seconds / Decimal(3600) if cycle_seconds > 0 else ZERO
        row["operator_equivalent"] += load * operator_rate
        row["operator_hours"] += runtime_hours * operator_rate
        if allocated > 0:
            row["allocations"].append({
                "product_id": product.id,
                "product_code": product.code,
                "product": product.name,
                "route_operation_id": route_operation.id,
                "operation": operation.name,
                "revision_no": int(allocation.revision_no),
                "allocated_qty": float(allocated),
                "capacity_qty_snapshot": float(capacity_snapshot),
                "load_percent": float(load * 100),
                "planning_cycle_time_sec": float(allocation.planning_cycle_time_sec),
                "operators_per_machine": float(allocation.operators_per_machine_snapshot),
            })

    # Show active machines even before their first monthly allocation.
    machines = db.scalars(select(Machine).where(Machine.is_active.is_(True)).order_by(Machine.code)).all()
    for machine in machines:
        by_machine.setdefault(machine.id, {
            "machine_id": machine.id,
            "machine_code": machine.code,
            "machine_name": machine.name,
            "plant": machine.plant,
            "department": machine.department,
            "is_active": machine.is_active,
            "load_fraction": ZERO,
            "operator_equivalent": ZERO,
            "operator_hours": ZERO,
            "allocations": [],
        })

    result = []
    for row in by_machine.values():
        load_percent = row.pop("load_fraction") * Decimal(100)
        available_percent = max(ZERO, Decimal(100) - load_percent)
        overload_percent = max(ZERO, load_percent - Decimal(100))
        row["required_operator_equivalent"] = float(row.pop("operator_equivalent"))
        row["operator_hours"] = float(row["operator_hours"])
        row["allocated_load_percent"] = float(load_percent)
        row["available_load_percent"] = float(available_percent)
        row["overload_percent"] = float(overload_percent)
        row["allocation_count"] = len(row["allocations"])
        row["status"] = (
            "OVERLOADED" if overload_percent > 0 else
            "FULL" if load_percent >= Decimal("99.999") else
            "NEAR CAPACITY" if load_percent >= Decimal("85") else
            "HEALTHY" if load_percent >= Decimal("60") else
            "UNDERLOADED"
        )
        row["allocations"].sort(key=lambda x: (x["product"], x["operation"]))
        result.append(row)

    result.sort(key=lambda x: (x["machine_code"], x["machine_name"]))
    by_area: dict[tuple[str, str], dict] = {}
    for row in result:
        key = (row["plant"] or "Unassigned", row["department"] or "Unassigned")
        area = by_area.setdefault(key, {"plant": key[0], "department": key[1], "machine_count": 0, "allocated_machine_count": 0, "overloaded_machine_count": 0, "required_operator_equivalent": ZERO, "operator_hours": ZERO})
        area["machine_count"] += 1
        area["allocated_machine_count"] += 1 if row["allocation_count"] > 0 else 0
        area["overloaded_machine_count"] += 1 if row["overload_percent"] > 0 else 0
        area["required_operator_equivalent"] += Decimal(str(row["required_operator_equivalent"]))
        area["operator_hours"] += Decimal(str(row["operator_hours"]))
    area_summary = [{**area, "required_operator_equivalent": float(area["required_operator_equivalent"]), "operator_hours": float(area["operator_hours"])} for area in by_area.values()]
    area_summary.sort(key=lambda x: (x["plant"], x["department"]))
    return {
        "month": month.isoformat(),
        "machines": result,
        "machine_count": len(result),
        "allocated_machine_count": sum(1 for x in result if x["allocated_load_percent"] > 0),
        "overloaded_machine_count": sum(1 for x in result if x["overload_percent"] > 0),
        "near_capacity_machine_count": sum(1 for x in result if x["status"] == "NEAR CAPACITY"),
        "underloaded_machine_count": sum(1 for x in result if x["status"] == "UNDERLOADED"),
        "required_operator_equivalent": float(sum((Decimal(str(x["required_operator_equivalent"])) for x in result), ZERO)),
        "operator_hours": float(sum((Decimal(str(x["operator_hours"])) for x in result), ZERO)),
        "readiness": {
            "unallocated_machine_count": sum(1 for x in result if x["allocation_count"] == 0),
            "loaded_machine_count": sum(1 for x in result if x["allocation_count"] > 0),
        },
        "areas": area_summary,
    }


def _suggest(schedule_qty: Decimal, machines: list[dict]) -> dict[int, Decimal]:
    remaining = max(ZERO, schedule_qty)
    result: dict[int, Decimal] = {x["machine_id"]: ZERO for x in machines}
    usable = [
        x for x in machines
        if x["complete"] and Decimal(str(x.get("available_capacity_qty", 0))) > 0
    ]
    for item in sorted(usable, key=lambda x: (x["priority"], x["machine_code"])):
        available = Decimal(str(item["available_capacity_qty"])).quantize(Decimal("1"), rounding=ROUND_FLOOR)
        qty = min(remaining, available)
        result[item["machine_id"]] = qty
        remaining -= qty
        if remaining <= 0:
            break
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
        other_loads = _other_saved_machine_loads(db, first, product_id, route_operation.id)
        for item in machine_rows:
            capacity = Decimal(str(item["capacity_qty"]))
            other_load = max(ZERO, other_loads.get(item["machine_id"], ZERO))
            remaining_fraction = max(ZERO, Decimal("1") - other_load)
            available_capacity = capacity * remaining_fraction
            item.update(
                other_allocated_load_percent=float(other_load * 100),
                available_capacity_qty=float(available_capacity),
            )

        schedule_qty = scheduled.get(route_operation.id, ZERO)
        revision, saved = _latest_saved(db, product_id, route_operation.id, first)
        allocations = saved if revision is not None else _suggest(schedule_qty, machine_rows)
        for item in machine_rows:
            allocated = allocations.get(item["machine_id"], ZERO)
            capacity = Decimal(str(item["capacity_qty"]))
            own_load = allocated / capacity if capacity > 0 else ZERO
            other_load = Decimal(str(item["other_allocated_load_percent"])) / Decimal(100)
            total_machine_load = other_load + own_load
            gross_hours = Decimal(str(item["gross_available_hours"]))
            op_rate = Decimal(str(item["operators_per_machine"]))
            hourly_cost = Decimal(str(item["estimated_hourly_cost"]))
            cycle_per_piece = Decimal(str(item["planning_cycle_time_sec"]))
            cost_per_piece = hourly_cost * cycle_per_piece / Decimal(3600) if cycle_per_piece > 0 else ZERO
            item.update(
                allocation_qty=float(allocated), load_percent=float(own_load * 100),
                total_machine_load_percent=float(total_machine_load * 100),
                over_capacity=bool(total_machine_load > Decimal("1.000001")),
                required_machine_hours=float(gross_hours * own_load),
                operator_hours=float(gross_hours * own_load * op_rate),
                average_operators=float(own_load * op_rate),
                operators_required=math.ceil(float(own_load * op_rate)) if allocated > 0 else 0,
                estimated_cost_per_piece=float(cost_per_piece),
                estimated_run_cost=float(cost_per_piece * allocated),
            )
        allocated_total = sum((Decimal(str(x["allocation_qty"])) for x in machine_rows), ZERO)
        total_capacity = sum((Decimal(str(x["capacity_qty"])) for x in machine_rows), ZERO)
        total_available_capacity = sum((Decimal(str(x["available_capacity_qty"])) for x in machine_rows), ZERO)
        operation_rows.append({
            "route_operation_id": route_operation.id, "operation_id": operation.id,
            "sequence_no": route_operation.sequence_no, "operation": operation.name,
            "schedule_qty": float(schedule_qty), "allocation_revision": revision,
            "allocation_source": "SAVED" if revision is not None else "SUGGESTED",
            "allocated_qty": float(allocated_total), "allocation_gap": float(schedule_qty - allocated_total),
            "total_capacity_qty": float(total_capacity),
            "total_available_capacity_qty": float(total_available_capacity),
            "capacity_shortage": float(max(ZERO, schedule_qty - total_available_capacity)),
            "operators_required": math.ceil(sum(x["average_operators"] for x in machine_rows)),
            "estimated_run_cost": sum(x["estimated_run_cost"] for x in machine_rows),
            "machines": machine_rows,
        })
    return {
        "month": first.isoformat(), "product_id": product.id, "product": product.name,
        "plant": product_plant(db, product.id),
        "working_days": len(working_days(db, first, last, product_plant(db, product.id))),
        "operations": operation_rows,
    }


def save_allocation(db: Session, payload, user_id: int) -> dict:
    # Serialize allocation saves for the physical machines involved so two users
    # cannot commit overlapping capacity at the same time.
    machine_ids = sorted({x.machine_id for x in payload.allocations})
    if machine_ids:
        db.execute(select(Machine.id).where(
            Machine.id.in_(machine_ids)
        ).order_by(Machine.id).with_for_update()).all()

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
    if total > schedule_qty + Decimal("0.001"):
        raise HTTPException(422, f"Allocated quantity {total} cannot exceed monthly operation schedule {schedule_qty}")
    revision = int(db.scalar(select(func.coalesce(func.max(MachineMonthlyAllocation.revision_no), 0)).where(
        MachineMonthlyAllocation.product_id == payload.product_id,
        MachineMonthlyAllocation.route_operation_id == payload.route_operation_id,
        MachineMonthlyAllocation.month == payload.month.replace(day=1),
    )) or 0) + 1
    for machine_id, qty in supplied.items():
        detail = valid[machine_id]
        if qty > 0 and not detail["complete"]:
            raise HTTPException(422, f"{detail['machine_code']} has incomplete capacity/cycle/operator masters")
        available = Decimal(str(detail.get("available_capacity_qty", detail["capacity_qty"])))
        if qty > available + Decimal("0.001"):
            other_load = Decimal(str(detail.get("other_allocated_load_percent", 0)))
            raise HTTPException(
                422,
                f"{detail['machine_code']} allocation {qty} exceeds available capacity "
                f"{available.quantize(Decimal('0.001'))}. Other monthly allocations already use "
                f"{other_load.quantize(Decimal('0.1'))}% of this machine."
            )
        db.add(MachineMonthlyAllocation(
            month=payload.month.replace(day=1), effective_from=payload.effective_from,
            revision_no=revision, product_id=payload.product_id,
            route_operation_id=payload.route_operation_id, machine_id=machine_id,
            allocated_qty=qty, schedule_qty_snapshot=schedule_qty,
            capacity_qty_snapshot=Decimal(str(detail["capacity_qty"])),
            planning_cycle_time_sec=Decimal(str(detail["planning_cycle_time_sec"] or 0)),
            operators_per_machine_snapshot=Decimal(str(detail["operators_per_machine"] or 0)),
            estimated_hourly_cost_snapshot=Decimal(str(detail["estimated_hourly_cost"])),
            estimated_cost_per_piece_snapshot=Decimal(str(detail["estimated_cost_per_piece"])),
            reason=payload.reason, entered_by_id=user_id,
        ))
    db.flush()
    return {
        "revision_no": revision,
        "allocated_qty": float(total),
        "schedule_qty": float(schedule_qty),
        "allocation_gap": float(schedule_qty - total),
    }
