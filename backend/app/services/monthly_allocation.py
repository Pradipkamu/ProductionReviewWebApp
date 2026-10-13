"""Whole-month machine allocation proposals with constrained-first scheduling.

Preview never writes to the database. Approval rechecks the whole month inside a
transaction; individual saved manual allocations are retained unless overridden.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_FLOOR

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import DailyRequirement, Machine, MachineMonthlyAllocation
from .capacity import capacity_plan, save_allocation

D = lambda value: Decimal(str(value or 0))
ZERO = Decimal("0")


def _candidate_operations(db: Session, month: date):
    first = month.replace(day=1)
    from calendar import monthrange
    last = first.replace(day=monthrange(first.year, first.month)[1])
    return db.execute(
        select(DailyRequirement.product_id)
        .where(DailyRequirement.req_date >= first,
               DailyRequirement.req_date <= last,
               DailyRequirement.route_operation_id.is_not(None))
        .group_by(DailyRequirement.product_id)
        .having(__import__("sqlalchemy").func.sum(DailyRequirement.revised_plan_qty) > 0)
        .order_by(DailyRequirement.product_id)
    ).scalars().all()


def _saved_rows(db: Session, month: date):
    rows = db.scalars(select(MachineMonthlyAllocation).where(
        MachineMonthlyAllocation.month == month
    ).order_by(MachineMonthlyAllocation.revision_no.desc(), MachineMonthlyAllocation.id.desc())).all()
    latest = {}
    for row in rows:
        key = (row.product_id, row.route_operation_id)
        if key not in latest:
            latest[key] = row.revision_no
    result = defaultdict(list)
    for row in rows:
        key = (row.product_id, row.route_operation_id)
        if latest[key] == row.revision_no:
            result[key].append(row)
    return result


def monthly_preview(db: Session, month: date, *, strategy: str = "priority",
                    overrides: dict | None = None) -> dict:
    if strategy not in ("priority", "cost"):
        raise HTTPException(422, "Strategy must be priority or cost")
    month = month.replace(day=1)
    overridden = overrides or {}
    saved = _saved_rows(db, month)
    operations = []
    for product_id in _candidate_operations(db, month):
        product_plan = capacity_plan(db, product_id, month)
        for operation in product_plan["operations"]:
            demand = D(operation["schedule_qty"])
            if demand <= 0:
                continue
            key = (product_id, operation["route_operation_id"])
            mappings = operation["machines"]
            if not mappings:
                eligible_count = 0
            else:
                eligible_count = sum(1 for m in mappings if m["complete"] and D(m["capacity_qty"]) > 0)
            operations.append({
                "product_id": product_id, "product": product_plan["product"],
                "plant": product_plan["plant"], "route_operation_id": operation["route_operation_id"],
                "operation": operation["operation"], "schedule_qty": float(demand),
                "saved_revision": operation["allocation_revision"],
                "saved_schedule_qty": float(saved[key][0].schedule_qty_snapshot) if saved.get(key) else None,
                "stale": bool(saved.get(key) and D(saved[key][0].schedule_qty_snapshot) != demand),
                "machines": mappings, "eligible_count": eligible_count,
                "key": key,
            })

    # Single-machine operations are assigned first, then constrained operations.
    operations.sort(key=lambda o: (o["eligible_count"] or 100000, o["product_id"], o["route_operation_id"]))
    capacity_used = defaultdict(lambda: ZERO)
    result = []
    alerts = []
    for op in operations:
        key = op.pop("key")
        override = overridden.get(f"{key[0]}:{key[1]}")
        manual_saved = saved.get(key)
        source = "MANUAL_OVERRIDE" if override is not None else "SAVED" if manual_saved else "AUTO"
        allocated = defaultdict(lambda: ZERO)
        if override is not None:
            valid_ids = {str(m["machine_id"]) for m in op["machines"]}
            if set(override) - valid_ids:
                raise HTTPException(422, f"Override has unmapped machine for {key}")
            allocated.update({int(i): D(q) for i, q in override.items()})
        elif manual_saved:
            allocated.update({r.machine_id: D(r.allocated_qty) for r in manual_saved})
        else:
            available = [m for m in op["machines"] if m["complete"] and D(m["capacity_qty"]) > 0]
            if strategy == "cost":
                available.sort(key=lambda m: (not bool(m.get("cost_complete")),
                                               D(m.get("estimated_cost_per_piece")) if m.get("cost_complete") else Decimal("1E20"),
                                               m["priority"], m["machine_code"]))
            else:
                available.sort(key=lambda m: (m["priority"], m["machine_code"]))
            remaining = D(op["schedule_qty"])
            for machine in available:
                mid = machine["machine_id"]
                free_fraction = max(ZERO, Decimal(1) - capacity_used[mid])
                free_qty = (D(machine["capacity_qty"]) * free_fraction).to_integral_value(rounding=ROUND_FLOOR)
                take = min(remaining, free_qty)
                if take > 0:
                    allocated[mid] = take
                    remaining -= take
                if remaining <= 0:
                    break
        lines = []
        for machine in op["machines"]:
            mid = machine["machine_id"]
            qty = allocated[mid]
            cap = D(machine["capacity_qty"])
            fraction = qty / cap if cap > 0 else ZERO
            capacity_used[mid] += fraction
            cycle = D(machine.get("planning_cycle_time_sec"))
            operators = D(machine.get("operators_per_machine"))
            machine_hours = qty * cycle / Decimal(3600)
            lines.append({
                "machine_id": mid, "machine_code": machine["machine_code"],
                "allocated_qty": float(qty), "capacity_qty": float(cap),
                "machine_hours": float(machine_hours), "operator_hours": float(machine_hours * operators),
                "operators_per_machine": float(operators),
                "estimated_run_cost": float(qty * D(machine.get("estimated_cost_per_piece"))),
                "shifts_per_day": None,
            })
        total = sum((D(x["allocated_qty"]) for x in lines), ZERO)
        gap = D(op["schedule_qty"]) - total
        if gap > 0:
            alerts.append({"product": op["product"], "operation": op["operation"], "kind": "SHORTAGE" if op["machines"] else "UNMAPPED", "quantity": float(gap)})
        if gap < 0:
            alerts.append({"product": op["product"], "operation": op["operation"], "kind": "OVER_SCHEDULE", "quantity": float(-gap)})
        if op["stale"]:
            alerts.append({"product": op["product"], "operation": op["operation"], "kind": "STALE_SCHEDULE", "quantity": float(D(op["schedule_qty"]) - D(op["saved_schedule_qty"]))})
        op.update(source=source, allocated_qty=float(total), gap=float(gap), allocations=lines)
        op.pop("machines")
        result.append(op)

    machines = []
    for machine in db.scalars(select(Machine).where(Machine.is_active.is_(True)).order_by(Machine.code)).all():
        load = capacity_used[machine.id]
        if load > Decimal("1.000001"):
            alerts.append({"kind": "OVERLOAD", "machine": machine.code, "percent": float(load * 100)})
        lines = [line for op in result for line in op["allocations"] if line["machine_id"] == machine.id and line["allocated_qty"] > 0]
        hours = sum(D(line["machine_hours"]) for line in lines)
        operator_hours = sum(D(line["operator_hours"]) for line in lines)
        # Shift-wise forecast is an even-load planning estimate, not a duty roster.
        shifts = 3
        shift_hours = float(operator_hours / shifts)
        machines.append({
            "machine_id": machine.id, "machine_code": machine.code,
            "load_percent": float(load * 100), "machine_hours": float(hours),
            "operator_hours": float(operator_hours), "estimated_cost": float(sum(D(x["estimated_run_cost"]) for x in lines)),
            "shift_operator_hours_estimate": [shift_hours] * shifts,
        })
    data = {"month": month.isoformat(), "strategy": strategy, "operations": result,
            "machines": machines, "alerts": alerts}
    # Token detects changing schedule, mappings and allocations before bulk approval.
    data["preview_token"] = hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()
    return data


def approve_month(db: Session, month: date, user_id: int, *, strategy: str,
                  preview_token: str, reason: str, overrides: dict | None = None):
    if not reason.strip():
        raise HTTPException(422, "Approval reason is required")
    month = month.replace(day=1)
    # Lock all physical machines, not just one product, before recomputing.
    db.execute(select(Machine.id).where(Machine.is_active.is_(True)).order_by(Machine.id).with_for_update()).all()
    preview = monthly_preview(db, month, strategy=strategy, overrides=overrides)
    if preview["preview_token"] != preview_token:
        raise HTTPException(409, "Monthly plan changed. Refresh the preview before approval")
    if any(x["kind"] in ("OVERLOAD", "OVER_SCHEDULE") for x in preview["alerts"]):
        raise HTTPException(422, "Cannot approve overloaded or over-scheduled machines")
    from ..schemas import MachineAllocationCreate
    results = []
    for op in preview["operations"]:
        # Explicitly saved allocations remain untouched unless the operator supplied an override.
        if op["source"] == "SAVED":
            continue
        if op["allocated_qty"] <= 0:
            continue
        payload = MachineAllocationCreate(
            product_id=op["product_id"], route_operation_id=op["route_operation_id"],
            month=month, effective_from=month, reason=reason,
            allocations=[{"machine_id": line["machine_id"], "allocated_qty": line["allocated_qty"]}
                         for line in op["allocations"]],
        )
        results.append(save_allocation(db, payload, user_id))
    db.commit()
    return {"approved": len(results), "skipped_saved": sum(o["source"] == "SAVED" for o in preview["operations"]),
            "shortages": sum(x["kind"] in ("SHORTAGE", "UNMAPPED") for x in preview["alerts"])}
