from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..models import (
    Action, ActionContext, Customer, DailyMIS, DailyRequirement, LossCategory,
    Machine, MachineLossEvent, MachineShiftProduction, Operation, ProcessDailySummary,
    Product, RouteOperation, RouteVersion, SalesPriceHistory, ScheduleRevision,
    User, Vendor, VendorMovement,
)
from ..enums import ActionStatus
from ..services.oee import calculate_oee
from ..services.filtering import csv_ints, csv_strings
from ..services.planning import active_schedule_revision, actual_before, working_days, product_plant

router = APIRouter(prefix="/reports", tags=["reports"])
ZERO = Decimal("0")


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _value(v) -> Decimal:
    return Decimal(str(v or 0))


def _period_row(label: str, start: date, end: date, plan: Decimal, actual: Decimal) -> dict:
    compliance = (actual / plan) if plan > 0 else None
    return {
        "label": label,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "plan": float(plan),
        "actual": float(actual),
        "gap": float(actual - plan),
        "compliance": float(compliance) if compliance is not None else None,
    }


def _aggregate(rows: list[dict], key_fn, label_fn, bounds_fn) -> list[dict]:
    buckets: dict[date, dict[str, Decimal]] = defaultdict(lambda: {"plan": ZERO, "actual": ZERO})
    for r in rows:
        key = key_fn(r["date"])
        buckets[key]["plan"] += r["plan"]
        buckets[key]["actual"] += r["actual"]
    out: list[dict] = []
    for key in sorted(buckets):
        start, end = bounds_fn(key)
        vals = buckets[key]
        out.append(_period_row(label_fn(key, start, end), start, end, vals["plan"], vals["actual"]))
    return out


def _comparison(rows: list[dict], key_name: str, label_name: str) -> list[dict]:
    buckets: dict[str, dict[str, Decimal]] = defaultdict(lambda: {"plan": ZERO, "actual": ZERO})
    for r in rows:
        label = str(r.get(key_name) or "Unassigned")
        buckets[label]["plan"] += r["plan"]
        buckets[label]["actual"] += r["actual"]
    out = []
    for label, vals in buckets.items():
        comp = vals["actual"] / vals["plan"] if vals["plan"] > 0 else None
        out.append({
            label_name: label,
            "plan": float(vals["plan"]),
            "actual": float(vals["actual"]),
            "gap": float(vals["actual"] - vals["plan"]),
            "compliance": float(comp) if comp is not None else None,
        })
    out.sort(key=lambda x: (x["compliance"] if x["compliance"] is not None else -1, x[label_name]))
    return out


@router.get("/compliance")
def compliance_report(
    as_of: date,
    product_id: str | None = None,
    plant: str | None = None,
    product_group: str | None = None,
    customer_id: str | None = None,
    metric: str = Query("qty", pattern="^(qty|sales|tonnage)$"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Daily/weekly/monthly compliance with Plant/Group/Customer filters.

    metric=tonnage uses Finish Weight (Kg/pc) from PBI_Products and returns MT.
    Schedule-revised dispatch requirements remain the plan source from the
    revision effective date onward.
    """
    current_month = _month_start(as_of)
    current_week = _monday(as_of)
    daily_start = current_month
    weekly_start = current_week - timedelta(weeks=7)
    monthly_start = current_month - relativedelta(months=11)
    query_start = min(daily_start, weekly_start, monthly_start)

    product_ids_filter = csv_ints(product_id)
    plants_filter = csv_strings(plant)
    groups_filter = csv_strings(product_group)
    customers_filter = csv_ints(customer_id)
    product_q = select(Product, Customer).outerjoin(Customer, Customer.id == Product.customer_id)
    if product_ids_filter:
        product_q = product_q.where(Product.id.in_(product_ids_filter))
    if plants_filter:
        product_q = product_q.where(Product.plant.in_(plants_filter))
    if groups_filter:
        product_q = product_q.where(Product.product_group.in_(groups_filter))
    if customers_filter:
        product_q = product_q.where(Product.customer_id.in_(customers_filter))
    product_rows = db.execute(product_q).all()
    products = {p.id: (p, c) for p, c in product_rows}
    product_ids = list(products)

    if not product_ids:
        return {
            "as_of": as_of.isoformat(), "metric": metric, "product_id": product_id,
            "filters": {"plant": plant, "product_group": product_group, "customer_id": customer_id},
            "scope": "filtered", "summary": {"period": f"{current_month.strftime('%d %b %Y')} – {as_of.strftime('%d %b %Y')}", "plan": 0, "actual": 0, "gap": 0, "compliance": None, "actions_raised": 0},
            "daily": [], "weekly": [], "monthly": [], "parts": [], "plants": [], "product_groups": [],
            "missing_weight_products": [],
        }

    mis_q = select(DailyMIS).where(
        DailyMIS.mis_date >= query_start,
        DailyMIS.mis_date <= as_of,
        DailyMIS.product_id.in_(product_ids),
    )
    mis_rows = db.scalars(mis_q.order_by(DailyMIS.mis_date, DailyMIS.product_id)).all()

    req_q = select(DailyRequirement).where(
        DailyRequirement.req_date >= query_start,
        DailyRequirement.req_date <= as_of,
        DailyRequirement.route_operation_id.is_(None),
        DailyRequirement.product_id.in_(product_ids),
    )
    req_rows = db.scalars(req_q.order_by(DailyRequirement.updated_at, DailyRequirement.id)).all()
    revised: dict[tuple[date, int], Decimal] = {(r.req_date, r.product_id): _value(r.revised_plan_qty) for r in req_rows}

    missing_weight = set()
    normalized: list[dict] = []
    for r in mis_rows:
        p, c = products[r.product_id]
        plan_qty = revised.get((r.mis_date, r.product_id), _value(r.plan_qty))
        actual_qty = _value(r.actual_qty)
        price = _value(r.sales_price)
        weight = _value(p.finish_weight_kg)
        if metric == "sales":
            plan, actual = plan_qty * price, actual_qty * price
        elif metric == "tonnage":
            if weight <= 0:
                missing_weight.add(p.name)
            plan, actual = plan_qty * weight / Decimal("1000"), actual_qty * weight / Decimal("1000")
        else:
            plan, actual = plan_qty, actual_qty
        normalized.append({
            "date": r.mis_date, "product_id": r.product_id, "plan": plan, "actual": actual,
            "product": p.name, "plant": p.plant or "Unassigned", "product_group": p.product_group or "Unassigned",
            "customer": c.name if c else "Unassigned", "customer_id": p.customer_id,
        })

    daily_source = [r for r in normalized if r["date"] >= daily_start]
    weekly_source = [r for r in normalized if r["date"] >= weekly_start]
    monthly_source = [r for r in normalized if r["date"] >= monthly_start]

    daily = _aggregate(daily_source, lambda d: d, lambda key, start, end: key.strftime("%d %b"), lambda key: (key, key))

    # Day-wise action visibility for the Daily Compliance review. Count each
    # action once by its business/reference date, limited to actions linked to
    # products inside the currently selected compliance scope. Multiple action
    # contexts for the same action must not inflate the count.
    action_counts = dict(db.execute(
        select(Action.reference_date, func.count(func.distinct(Action.id)))
        .join(ActionContext, ActionContext.action_id == Action.id)
        .where(
            Action.reference_date >= daily_start,
            Action.reference_date <= as_of,
            ActionContext.product_id.in_(product_ids),
        )
        .group_by(Action.reference_date)
    ).all())
    for row in daily:
        day = date.fromisoformat(row["start"])
        row["action_count"] = int(action_counts.get(day, 0) or 0)

    weekly = _aggregate(
        weekly_source, _monday,
        lambda key, start, end: f"W{key.isocalendar().week:02d}",
        lambda key: (key, min(key + timedelta(days=6), as_of)),
    )
    monthly = _aggregate(
        monthly_source, _month_start,
        lambda key, start, end: key.strftime("%b %Y"),
        lambda key: (key, min(key + relativedelta(months=1) - timedelta(days=1), as_of)),
    )

    part_bucket: dict[int, dict[str, Decimal]] = defaultdict(lambda: {"plan": ZERO, "actual": ZERO})
    for r in daily_source:
        part_bucket[r["product_id"]]["plan"] += r["plan"]
        part_bucket[r["product_id"]]["actual"] += r["actual"]
    parts = []
    for pid, vals in part_bucket.items():
        p, c = products[pid]
        comp = vals["actual"] / vals["plan"] if vals["plan"] > 0 else None
        parts.append({
            "product_id": pid, "product": p.name,
            "plant": p.plant, "product_group": p.product_group, "customer": c.name if c else None,
            "finish_weight_kg": float(p.finish_weight_kg) if p.finish_weight_kg is not None else None,
            "plan": float(vals["plan"]), "actual": float(vals["actual"]), "gap": float(vals["actual"] - vals["plan"]),
            "compliance": float(comp) if comp is not None else None,
        })
    parts.sort(key=lambda x: (x["compliance"] if x["compliance"] is not None else -1, x["product"]))

    summary_plan = sum((r["plan"] for r in daily_source), ZERO)
    summary_actual = sum((r["actual"] for r in daily_source), ZERO)
    summary_comp = summary_actual / summary_plan if summary_plan > 0 else None

    return {
        "as_of": as_of.isoformat(), "metric": metric, "product_id": product_id,
        "filters": {"plant": plant, "product_group": product_group, "customer_id": customer_id},
        "scope": "single_part" if len(product_ids_filter) == 1 else "filtered_all_parts",
        "summary": {
            "period": f"{current_month.strftime('%d %b %Y')} – {as_of.strftime('%d %b %Y')}",
            "plan": float(summary_plan), "actual": float(summary_actual), "gap": float(summary_actual - summary_plan),
            "compliance": float(summary_comp) if summary_comp is not None else None,
            "actions_raised": int(sum(action_counts.values())),
        },
        "daily": daily, "weekly": weekly, "monthly": monthly, "parts": parts,
        "plants": _comparison(daily_source, "plant", "name"),
        "product_groups": _comparison(daily_source, "product_group", "name"),
        "customers": _comparison(daily_source, "customer", "name"),
        "missing_weight_products": sorted(missing_weight),
    }


def _scoped_products(
    db: Session,
    product_id: str | int | None = None,
    plant: str | None = None,
    product_group: str | None = None,
    customer_id: str | int | None = None,
) -> dict[int, tuple[Product, Customer | None]]:
    product_ids = csv_ints(product_id)
    plants = csv_strings(plant)
    groups = csv_strings(product_group)
    customer_ids = csv_ints(customer_id)
    q = select(Product, Customer).outerjoin(Customer, Customer.id == Product.customer_id)
    if product_ids:
        q = q.where(Product.id.in_(product_ids))
    if plants:
        q = q.where(Product.plant.in_(plants))
    if groups:
        q = q.where(Product.product_group.in_(groups))
    if customer_ids:
        q = q.where(Product.customer_id.in_(customer_ids))
    return {p.id: (p, c) for p, c in db.execute(q).all()}


def _date_bounds(as_of: date, months: int = 12) -> tuple[date, date]:
    start = _month_start(as_of) - relativedelta(months=max(0, months - 1))
    return start, as_of


def _periodize(rows: list[dict], field_plan: str = "plan", field_actual: str = "actual") -> dict:
    daily = _aggregate(
        rows,
        lambda d: d,
        lambda key, start, end: key.strftime("%d %b"),
        lambda key: (key, key),
    )
    weekly = _aggregate(
        rows,
        _monday,
        lambda key, start, end: f"W{key.isocalendar().week:02d}",
        lambda key: (key, key + timedelta(days=6)),
    )
    monthly = _aggregate(
        rows,
        _month_start,
        lambda key, start, end: key.strftime("%b %Y"),
        lambda key: (key, key + relativedelta(months=1) - timedelta(days=1)),
    )
    return {"daily": daily, "weekly": weekly, "monthly": monthly}


@router.get("/process-compliance")
def process_compliance_report(
    as_of: date,
    product_id: str | None = None,
    operation_id: int | None = None,
    plant: str | None = None,
    product_group: str | None = None,
    customer_id: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Operation-level Plan vs Actual for daily, weekly and monthly review.

    Revised process requirements are preferred over imported process plan values.
    Missing actual records remain visible as zero when a requirement exists.
    """
    products = _scoped_products(db, product_id, plant, product_group, customer_id)
    product_ids = list(products)
    if not product_ids:
        return {"as_of": as_of.isoformat(), "daily": [], "weekly": [], "monthly": [], "operations": [], "details": []}

    start, _ = _date_bounds(as_of, 12)
    req_q = (
        select(DailyRequirement, RouteOperation, Operation)
        .join(RouteOperation, RouteOperation.id == DailyRequirement.route_operation_id)
        .join(Operation, Operation.id == RouteOperation.operation_id)
        .where(
            DailyRequirement.req_date >= start,
            DailyRequirement.req_date <= as_of,
            DailyRequirement.product_id.in_(product_ids),
            DailyRequirement.route_operation_id.is_not(None),
        )
    )
    if operation_id is not None:
        req_q = req_q.where(Operation.id == operation_id)
    req_rows = db.execute(req_q).all()

    sum_q = (
        select(ProcessDailySummary, RouteOperation, Operation)
        .join(RouteOperation, RouteOperation.id == ProcessDailySummary.route_operation_id)
        .join(Operation, Operation.id == RouteOperation.operation_id)
        .where(
            ProcessDailySummary.summary_date >= start,
            ProcessDailySummary.summary_date <= as_of,
            ProcessDailySummary.product_id.in_(product_ids),
        )
    )
    if operation_id is not None:
        sum_q = sum_q.where(Operation.id == operation_id)
    sum_rows = db.execute(sum_q).all()

    req_map: dict[tuple[date, int, int], tuple[DailyRequirement, RouteOperation, Operation]] = {}
    for req, ro, op in req_rows:
        req_map[(req.req_date, req.product_id, ro.id)] = (req, ro, op)
    sum_map: dict[tuple[date, int, int], tuple[ProcessDailySummary, RouteOperation, Operation]] = {}
    for row, ro, op in sum_rows:
        sum_map[(row.summary_date, row.product_id, ro.id)] = (row, ro, op)

    keys = sorted(set(req_map) | set(sum_map))
    normalized: list[dict] = []
    details: list[dict] = []
    for key in keys:
        d, pid, roid = key
        req_t = req_map.get(key)
        sum_t = sum_map.get(key)
        req = req_t[0] if req_t else None
        summary = sum_t[0] if sum_t else None
        ro = (req_t or sum_t)[1]
        op = (req_t or sum_t)[2]
        p, c = products[pid]
        plan = _value(req.revised_plan_qty if req else (summary.plan_qty if summary else 0))
        actual = _value(summary.actual_qty if summary else 0)
        normalized.append({"date": d, "plan": plan, "actual": actual})
        details.append({
            "date": d.isoformat(), "product_id": pid, "product": p.name,
            "plant": p.plant, "product_group": p.product_group,
            "customer": c.name if c else None,
            "route_operation_id": ro.id, "operation_id": op.id, "operation": op.name,
            "sequence_no": ro.sequence_no,
            "plan": float(plan), "actual": float(actual), "gap": float(actual - plan),
            "compliance": float(actual / plan) if plan > 0 else None,
            "good_qty": float(_value(summary.good_qty if summary else 0)),
            "reject_qty": float(_value(summary.reject_qty if summary else 0)),
            "closing_wip": float(_value(summary.closing_wip if summary else 0)),
        })

    # Aggregate operation names for the current month so management can compare bottlenecks.
    month_start = _month_start(as_of)
    op_bucket: dict[str, dict[str, Decimal]] = defaultdict(lambda: {"plan": ZERO, "actual": ZERO})
    for r in details:
        if date.fromisoformat(r["date"]) < month_start:
            continue
        b = op_bucket[r["operation"]]
        b["plan"] += _value(r["plan"])
        b["actual"] += _value(r["actual"])
    operations = []
    for name, vals in op_bucket.items():
        comp = vals["actual"] / vals["plan"] if vals["plan"] > 0 else None
        operations.append({
            "name": name, "plan": float(vals["plan"]), "actual": float(vals["actual"]),
            "gap": float(vals["actual"] - vals["plan"]),
            "compliance": float(comp) if comp is not None else None,
        })
    operations.sort(key=lambda x: (x["compliance"] if x["compliance"] is not None else -1, x["name"]))
    daily_rows = [r for r in normalized if r["date"] >= _month_start(as_of)]
    weekly_start = _monday(as_of) - timedelta(weeks=7)
    weekly_rows = [r for r in normalized if r["date"] >= weekly_start]
    daily = _aggregate(daily_rows, lambda d: d, lambda key, start, end: key.strftime("%d %b"), lambda key: (key, key))
    weekly = _aggregate(weekly_rows, _monday, lambda key, start, end: f"W{key.isocalendar().week:02d}", lambda key: (key, min(key + timedelta(days=6), as_of)))
    monthly = _aggregate(normalized, _month_start, lambda key, start, end: key.strftime("%b %Y"), lambda key: (key, min(key + relativedelta(months=1) - timedelta(days=1), as_of)))
    return {
        "as_of": as_of.isoformat(), "daily": daily, "weekly": weekly, "monthly": monthly, "operations": operations,
        "details": details[-750:],
    }


@router.get("/process-funnel")
def process_funnel_report(
    report_date: date,
    product_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    route = db.scalar(
        select(RouteVersion)
        .where(
            RouteVersion.product_id == product_id,
            RouteVersion.effective_from <= report_date,
            or_(RouteVersion.effective_to.is_(None), RouteVersion.effective_to >= report_date),
            RouteVersion.is_active.is_(True),
        )
        .order_by(RouteVersion.revision_no.desc())
        .limit(1)
    )
    product = db.get(Product, product_id)
    if not route or not product:
        return {"date": report_date.isoformat(), "product_id": product_id, "product": product.name if product else None, "operations": []}
    ops = db.execute(
        select(RouteOperation, Operation, Vendor)
        .join(Operation, Operation.id == RouteOperation.operation_id)
        .outerjoin(Vendor, Vendor.id == RouteOperation.vendor_id)
        .where(RouteOperation.route_version_id == route.id, RouteOperation.is_enabled.is_(True))
        .order_by(RouteOperation.sequence_no)
    ).all()
    rows = []
    for ro, op, vendor in ops:
        req = db.scalar(select(DailyRequirement).where(
            DailyRequirement.req_date == report_date,
            DailyRequirement.product_id == product_id,
            DailyRequirement.route_operation_id == ro.id,
        ))
        summary = db.scalar(select(ProcessDailySummary).where(
            ProcessDailySummary.summary_date == report_date,
            ProcessDailySummary.product_id == product_id,
            ProcessDailySummary.route_operation_id == ro.id,
        ))
        plan = _value(req.revised_plan_qty if req else (summary.plan_qty if summary else 0))
        actual = _value(summary.actual_qty if summary else 0)
        rows.append({
            "route_operation_id": ro.id, "operation": op.name, "type": op.operation_type.value,
            "sequence_no": ro.sequence_no, "vendor": vendor.name if vendor else None,
            "plan": float(plan), "actual": float(actual),
            "good": float(_value(summary.good_qty if summary else 0)),
            "reject": float(_value(summary.reject_qty if summary else 0)),
            "closing_wip": float(_value(summary.closing_wip if summary else 0)),
            "gap": float(actual - plan), "compliance": float(actual / plan) if plan > 0 else None,
        })
    for i, row in enumerate(rows):
        next_actual = _value(rows[i + 1]["actual"]) if i + 1 < len(rows) else ZERO
        inferred = max(ZERO, _value(row["actual"]) - next_actual)
        row["inferred_between_process_wip"] = float(inferred)
        row["display_wip"] = row["closing_wip"] if row["closing_wip"] > 0 else float(inferred)
    return {
        "date": report_date.isoformat(), "product_id": product_id, "product": product.name,
        "route_revision": route.revision_no, "operations": rows,
    }


@router.get("/vendor-performance")
def vendor_performance_report(
    as_of: date,
    months: int = Query(12, ge=1, le=36),
    vendor_id: str | None = None,
    product_id: str | None = None,
    plant: str | None = None,
    product_group: str | None = None,
    customer_id: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    products = _scoped_products(db, product_id, plant, product_group, customer_id)
    pids = list(products)
    start, _ = _date_bounds(as_of, months)
    q = (
        select(VendorMovement, Vendor, Product, RouteOperation, Operation)
        .join(Vendor, Vendor.id == VendorMovement.vendor_id)
        .join(Product, Product.id == VendorMovement.product_id)
        .join(RouteOperation, RouteOperation.id == VendorMovement.route_operation_id)
        .join(Operation, Operation.id == RouteOperation.operation_id)
        .where(VendorMovement.outward_date >= start, VendorMovement.outward_date <= as_of)
    )
    if pids:
        q = q.where(VendorMovement.product_id.in_(pids))
    elif any([product_id is not None, plant, product_group, customer_id is not None]):
        return {"as_of": as_of.isoformat(), "vendors": [], "monthly": [], "movements": [], "summary": {}}
    vendor_ids = csv_ints(vendor_id)
    if vendor_ids:
        q = q.where(VendorMovement.vendor_id.in_(vendor_ids))
    rows = db.execute(q.order_by(VendorMovement.outward_date)).all()

    vendor_bucket: dict[int, dict] = {}
    month_bucket: dict[date, dict[str, Decimal | int]] = defaultdict(lambda: {
        "sent": ZERO, "received": ZERO, "reject": ZERO, "completed": 0, "on_time": 0,
    })
    movements = []
    for vm, vendor, product, ro, op in rows:
        sent = _value(vm.outward_qty)
        received = _value(vm.receipt_qty)
        reject = _value(vm.reject_qty)
        pending = max(ZERO, sent - received)
        overdue = bool(pending > 0 and vm.expected_return_date and vm.expected_return_date < as_of)
        completed = bool(received >= sent and sent > 0)
        on_time = bool(completed and vm.expected_return_date and vm.receipt_date and vm.receipt_date <= vm.expected_return_date)
        age_end = vm.receipt_date or as_of
        age_days = max(0, (age_end - vm.outward_date).days)
        b = vendor_bucket.setdefault(vendor.id, {
            "vendor_id": vendor.id, "vendor": vendor.name, "sent": ZERO, "received": ZERO,
            "reject": ZERO, "pending": ZERO, "overdue_count": 0, "movement_count": 0,
            "completed": 0, "on_time": 0, "age_sum": 0,
        })
        b["sent"] += sent; b["received"] += received; b["reject"] += reject; b["pending"] += pending
        b["overdue_count"] += int(overdue); b["movement_count"] += 1; b["completed"] += int(completed); b["on_time"] += int(on_time); b["age_sum"] += age_days
        mb = month_bucket[_month_start(vm.outward_date)]
        mb["sent"] += sent; mb["received"] += received; mb["reject"] += reject; mb["completed"] += int(completed); mb["on_time"] += int(on_time)
        movements.append({
            "id": vm.id, "vendor": vendor.name, "product": product.name, "operation": op.name,
            "outward_date": vm.outward_date.isoformat(), "expected_return_date": vm.expected_return_date.isoformat() if vm.expected_return_date else None,
            "receipt_date": vm.receipt_date.isoformat() if vm.receipt_date else None,
            "sent": float(sent), "received": float(received), "reject": float(reject), "pending": float(pending),
            "age_days": age_days, "overdue": overdue, "challan_no": vm.challan_no,
        })
    vendors = []
    for b in vendor_bucket.values():
        compliance = b["received"] / b["sent"] if b["sent"] > 0 else None
        on_time_ratio = Decimal(b["on_time"]) / Decimal(b["completed"]) if b["completed"] > 0 else None
        vendors.append({
            "name": b["vendor"], "vendor_id": b["vendor_id"], "plan": float(b["sent"]), "actual": float(b["received"]),
            "gap": float(b["received"] - b["sent"]), "compliance": float(compliance) if compliance is not None else None,
            "pending": float(b["pending"]), "reject": float(b["reject"]), "overdue_count": b["overdue_count"],
            "movement_count": b["movement_count"], "on_time_ratio": float(on_time_ratio) if on_time_ratio is not None else None,
            "average_age_days": round(b["age_sum"] / b["movement_count"], 1) if b["movement_count"] else 0,
        })
    vendors.sort(key=lambda x: (-x["pending"], x["name"]))
    monthly = []
    for key in sorted(month_bucket):
        b = month_bucket[key]
        comp = b["received"] / b["sent"] if b["sent"] > 0 else None
        otr = Decimal(b["on_time"]) / Decimal(b["completed"]) if b["completed"] else None
        monthly.append({
            "label": key.strftime("%b %Y"), "start": key.isoformat(), "sent": float(b["sent"]), "received": float(b["received"]),
            "pending": float(b["sent"] - b["received"]), "reject": float(b["reject"]),
            "compliance": float(comp) if comp is not None else None,
            "on_time_ratio": float(otr) if otr is not None else None,
        })
    total_sent = sum((b["sent"] for b in vendor_bucket.values()), ZERO)
    total_received = sum((b["received"] for b in vendor_bucket.values()), ZERO)
    return {
        "as_of": as_of.isoformat(), "vendors": vendors, "monthly": monthly, "movements": movements[-500:],
        "summary": {
            "sent": float(total_sent), "received": float(total_received), "pending": float(total_sent-total_received),
            "receipt_compliance": float(total_received/total_sent) if total_sent > 0 else None,
            "overdue_movements": sum(b["overdue_count"] for b in vendor_bucket.values()),
        },
    }


def _aggregate_oee_rows(rows: list[MachineShiftProduction]) -> dict:
    planned = run = theoretical = total = good = downtime = 0.0
    for r in rows:
        shift = float(r.shift_duration_min or 0); brk = float(r.planned_break_min or 0); dt = float(r.downtime_min or 0)
        p = max(0.0, shift - brk); rt = max(0.0, p - dt)
        planned += p; run += rt; downtime += dt
        total += float(r.total_count or 0); good += float(r.good_count or 0)
        theoretical += float(r.ideal_cycle_time_sec or 0) * float(r.total_count or 0) / 60.0
    availability = run / planned if planned > 0 else 0.0
    performance_raw = theoretical / run if run > 0 else 0.0
    performance_capped = min(1.0, max(0.0, performance_raw))
    quality = good / total if total > 0 else 0.0
    return {
        "planned_min": planned, "run_min": run, "downtime_min": downtime, "total_count": total, "good_count": good,
        "availability": availability, "performance_raw": performance_raw, "performance": performance_capped,
        "quality": quality, "oee": availability * performance_capped * quality,
        "performance_master_warning": performance_raw > 1.10,
    }


@router.get("/oee-trends")
def oee_trends_report(
    as_of: date,
    months: int = Query(6, ge=1, le=24),
    machine_id: str | None = None,
    product_id: str | None = None,
    route_operation_id: int | None = None,
    plant: str | None = None,
    product_group: str | None = None,
    customer_id: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    products = _scoped_products(db, product_id, plant, product_group, customer_id)
    pids = list(products)
    start, _ = _date_bounds(as_of, months)
    q = select(MachineShiftProduction).where(MachineShiftProduction.production_date >= start, MachineShiftProduction.production_date <= as_of)
    machine_ids = csv_ints(machine_id)
    if machine_ids:
        q = q.where(MachineShiftProduction.machine_id.in_(machine_ids))
    if route_operation_id is not None:
        q = q.where(MachineShiftProduction.route_operation_id == route_operation_id)
    if pids:
        q = q.where(MachineShiftProduction.product_id.in_(pids))
    elif any([product_id is not None, plant, product_group, customer_id is not None]):
        return {"summary": {}, "daily": [], "monthly": [], "machines": []}
    rows = db.scalars(q.order_by(MachineShiftProduction.production_date)).all()

    by_day: dict[date, list[MachineShiftProduction]] = defaultdict(list)
    by_month: dict[date, list[MachineShiftProduction]] = defaultdict(list)
    by_machine: dict[int, list[MachineShiftProduction]] = defaultdict(list)
    for r in rows:
        by_day[r.production_date].append(r); by_month[_month_start(r.production_date)].append(r); by_machine[r.machine_id].append(r)
    daily = []
    for d in sorted(by_day):
        a = _aggregate_oee_rows(by_day[d]); daily.append({"label": d.strftime("%d %b"), "date": d.isoformat(), **a})
    monthly = []
    for m in sorted(by_month):
        a = _aggregate_oee_rows(by_month[m]); monthly.append({"label": m.strftime("%b %Y"), "date": m.isoformat(), **a})
    machines = []
    action_by_machine: dict[int, set[int]] = defaultdict(set)
    overdue_by_machine: dict[int, set[int]] = defaultdict(set)
    action_rows = db.execute(
        select(ActionContext.machine_id, Action).join(Action, Action.id == ActionContext.action_id).where(
            ActionContext.context_date >= start, ActionContext.context_date <= as_of,
            ActionContext.machine_id.in_(list(by_machine) or [-1]),
            Action.status != ActionStatus.CLOSED,
        )
    ).all()
    for mid, action in action_rows:
        action_by_machine[mid].add(action.id)
        if action.due_at and action.due_at.date() < as_of:
            overdue_by_machine[mid].add(action.id)
    for mid, rs in by_machine.items():
        machine = db.get(Machine, mid); a = _aggregate_oee_rows(rs)
        machines.append({"machine_id": mid, "name": machine.code if machine else f"Machine {mid}",
                         "open_actions": len(action_by_machine[mid]), "overdue_actions": len(overdue_by_machine[mid]), **a})
    machines.sort(key=lambda x: x["oee"])
    summary = _aggregate_oee_rows(rows)
    product_map = {x.id: x.name for x in db.scalars(select(Product).where(Product.id.in_({r.product_id for r in rows} or {-1}))).all()}
    machine_map = {x.id: x.code for x in db.scalars(select(Machine).where(Machine.id.in_({r.machine_id for r in rows} or {-1}))).all()}
    route_rows = db.execute(
        select(RouteOperation.id, Operation.name).join(Operation, Operation.id == RouteOperation.operation_id)
        .where(RouteOperation.id.in_({r.route_operation_id for r in rows} or {-1}))
    ).all()
    operation_map = dict(route_rows)
    entries = []
    for r in sorted(rows, key=lambda x: (x.production_date, x.shift, x.machine_id), reverse=True):
        calc = calculate_oee(r.shift_duration_min, r.planned_break_min, r.downtime_min,
                             r.total_count, r.good_count, r.ideal_cycle_time_sec)
        entries.append({
            "id": r.id, "date": r.production_date.isoformat(), "shift": r.shift,
            "product": product_map.get(r.product_id, f"Product {r.product_id}"),
            "operation": operation_map.get(r.route_operation_id, f"Operation {r.route_operation_id}"),
            "machine": machine_map.get(r.machine_id, f"Machine {r.machine_id}"),
            "planned_min": calc["planned_production_min"], "run_min": calc["run_time_min"],
            "downtime_min": float(r.downtime_min), "total_count": float(r.total_count),
            "good_count": float(r.good_count), "reject_count": float(r.reject_count),
            "ideal_cycle_time_sec": float(r.ideal_cycle_time_sec),
            "availability": calc["availability"], "performance": calc["performance_capped"],
            "performance_raw": calc["performance_raw"], "quality": calc["quality"],
            "oee": calc["oee_reported"], "performance_master_warning": calc["performance_master_warning"],
            "remarks": r.remarks,
        })
    return {"as_of": as_of.isoformat(), "summary": summary, "daily": daily, "monthly": monthly,
            "machines": machines, "entries": entries}


@router.get("/loss-pareto")
def loss_pareto_report(
    as_of: date,
    months: int = Query(6, ge=1, le=24),
    machine_id: str | None = None,
    product_id: str | None = None,
    route_operation_id: int | None = None,
    plant: str | None = None,
    product_group: str | None = None,
    customer_id: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    products = _scoped_products(db, product_id, plant, product_group, customer_id)
    pids = list(products)
    start, _ = _date_bounds(as_of, months)
    q = (
        select(MachineLossEvent, LossCategory, Machine)
        .join(LossCategory, LossCategory.id == MachineLossEvent.loss_category_id)
        .join(Machine, Machine.id == MachineLossEvent.machine_id)
        .where(MachineLossEvent.loss_date >= start, MachineLossEvent.loss_date <= as_of)
    )
    machine_ids = csv_ints(machine_id)
    if machine_ids:
        q = q.where(MachineLossEvent.machine_id.in_(machine_ids))
    if route_operation_id is not None:
        q = q.where(MachineLossEvent.route_operation_id == route_operation_id)
    if pids:
        q = q.where(or_(MachineLossEvent.product_id.in_(pids), MachineLossEvent.product_id.is_(None)))
    elif any([product_id is not None, plant, product_group, customer_id is not None]):
        return {"pareto": [], "monthly": [], "machines": [], "summary": {}}
    rows = db.execute(q).all()
    event_ids = [event.id for event, _, _ in rows]
    action_map: dict[int, Action] = {}
    for loss_event_id, action in db.execute(
        select(ActionContext.loss_event_id, Action).join(Action, Action.id == ActionContext.action_id)
        .where(ActionContext.loss_event_id.in_(event_ids or [-1])).order_by(Action.id.desc())
    ).all():
        action_map.setdefault(loss_event_id, action)
    product_ids = {event.product_id for event, _, _ in rows if event.product_id}
    product_map = {x.id: x.name for x in db.scalars(select(Product).where(Product.id.in_(product_ids or {-1}))).all()}
    route_ids = {event.route_operation_id for event, _, _ in rows if event.route_operation_id}
    operation_map = dict(db.execute(
        select(RouteOperation.id, Operation.name).join(Operation, Operation.id == RouteOperation.operation_id)
        .where(RouteOperation.id.in_(route_ids or {-1}))
    ).all())
    cat: dict[int, dict] = {}
    monthly_b: dict[date, Decimal] = defaultdict(lambda: ZERO)
    machine_b: dict[int, Decimal] = defaultdict(lambda: ZERO)
    total = ZERO
    for event, loss, machine in rows:
        mins = _value(event.duration_min); total += mins
        b = cat.setdefault(loss.id, {"loss_category_id": loss.id, "name": loss.name, "component": loss.oee_component.value, "minutes": ZERO, "qty_loss": ZERO, "occurrences": 0})
        b["minutes"] += mins; b["qty_loss"] += _value(event.qty_loss); b["occurrences"] += 1
        monthly_b[_month_start(event.loss_date)] += mins; machine_b[machine.id] += mins
    pareto = []
    running = ZERO
    for b in sorted(cat.values(), key=lambda x: x["minutes"], reverse=True):
        running += b["minutes"]
        pareto.append({
            "loss_category_id": b["loss_category_id"], "name": b["name"], "component": b["component"],
            "minutes": float(b["minutes"]), "hours": float(b["minutes"] / Decimal("60")),
            "qty_loss": float(b["qty_loss"]), "occurrences": b["occurrences"],
            "share": float(b["minutes"] / total) if total > 0 else None,
            "cumulative_share": float(running / total) if total > 0 else None,
        })
    monthly = [{"label": m.strftime("%b %Y"), "date": m.isoformat(), "minutes": float(v), "hours": float(v/Decimal("60"))} for m, v in sorted(monthly_b.items())]
    machines = []
    for mid, mins in sorted(machine_b.items(), key=lambda x: x[1], reverse=True):
        machine = db.get(Machine, mid)
        machines.append({"machine_id": mid, "name": machine.code if machine else f"Machine {mid}", "minutes": float(mins), "hours": float(mins/Decimal("60"))})
    events = []
    for event, loss, machine in sorted(rows, key=lambda x: (x[0].loss_date, x[0].id), reverse=True):
        action = action_map.get(event.id)
        events.append({
            "id": event.id, "date": event.loss_date.isoformat(), "shift": event.shift,
            "product": product_map.get(event.product_id) if event.product_id else None,
            "operation": operation_map.get(event.route_operation_id) if event.route_operation_id else None,
            "machine": machine.code, "category": loss.name, "component": loss.oee_component.value,
            "duration_min": float(event.duration_min), "qty_loss": float(event.qty_loss), "remark": event.remark,
            "action_id": action.id if action else None, "action_no": action.action_no if action else None,
            "action_status": action.status.value if action else None,
        })
    return {"pareto": pareto, "monthly": monthly, "machines": machines, "events": events,
            "summary": {"loss_minutes": float(total), "loss_hours": float(total/Decimal("60")), "events": len(rows)}}


@router.get("/action-performance")
def action_performance_report(
    as_of: date,
    months: int = Query(12, ge=1, le=36),
    product_id: str | None = None,
    plant: str | None = None,
    product_group: str | None = None,
    customer_id: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    start, _ = _date_bounds(as_of, months)
    product_scope = _scoped_products(db, product_id, plant, product_group, customer_id)
    scope_used = any([product_id is not None, plant, product_group, customer_id is not None])
    action_ids: set[int] | None = None
    if scope_used:
        if not product_scope:
            action_ids = set()
        else:
            action_ids = set(db.scalars(select(ActionContext.action_id).where(ActionContext.product_id.in_(list(product_scope))).distinct()).all())
    q = select(Action).where(Action.reference_date >= start, Action.reference_date <= as_of)
    actions = db.scalars(q).all()
    if action_ids is not None:
        actions = [a for a in actions if a.id in action_ids]

    users = {u.id: u for u in db.scalars(select(User)).all()}
    monthly_b: dict[date, dict[str, int]] = defaultdict(lambda: {"raised": 0, "closed": 0, "on_time": 0, "overdue": 0})
    owner_b: dict[str, dict] = defaultdict(lambda: {"open": 0, "closed": 0, "overdue": 0, "age_sum": 0, "max_age": 0})
    category_b: dict[str, dict] = defaultdict(lambda: {"count": 0, "open": 0, "closed": 0, "gap": ZERO})
    closed = overdue = on_time = open_count = 0
    for a in actions:
        month = _month_start(a.reference_date); mb = monthly_b[month]; mb["raised"] += 1
        is_closed = a.status == ActionStatus.CLOSED
        is_overdue = bool(a.due_at and not is_closed and a.due_at.date() < as_of)
        closed += int(is_closed); open_count += int(not is_closed); overdue += int(is_overdue)
        if is_closed:
            mb["closed"] += 1
            if a.due_at and a.closed_at and a.closed_at <= a.due_at:
                mb["on_time"] += 1; on_time += 1
        elif is_overdue:
            mb["overdue"] += 1
        owner = users.get(a.owner_id).full_name if a.owner_id in users else "Unassigned"
        ob = owner_b[owner]
        age = max(0, ((a.closed_at.date() if a.closed_at else as_of) - a.reference_date).days)
        ob["age_sum"] += age; ob["max_age"] = max(ob["max_age"], age)
        if is_closed: ob["closed"] += 1
        else: ob["open"] += 1
        if is_overdue: ob["overdue"] += 1
        category = a.problem_category or "Unclassified"
        cb = category_b[category]; cb["count"] += 1; cb["open"] += int(not is_closed); cb["closed"] += int(is_closed); cb["gap"] += abs(_value(a.gap_when_raised))

    monthly = []
    for m in sorted(monthly_b):
        b = monthly_b[m]
        monthly.append({"label": m.strftime("%b %Y"), "date": m.isoformat(), **b, "closure_compliance": b["closed"] / b["raised"] if b["raised"] else None})
    owners = []
    for name, b in owner_b.items():
        n = b["open"] + b["closed"]
        owners.append({"name": name, **b, "average_age_days": round(b["age_sum"] / n, 1) if n else 0})
    owners.sort(key=lambda x: (-x["overdue"], -x["open"], x["name"]))
    categories = [{"name": name, **{k: (float(v) if isinstance(v, Decimal) else v) for k, v in b.items()}} for name, b in category_b.items()]
    categories.sort(key=lambda x: (-x["count"], x["name"]))
    return {
        "as_of": as_of.isoformat(),
        "summary": {"raised": len(actions), "closed": closed, "open": open_count, "overdue": overdue, "on_time_closed": on_time, "closure_compliance": closed / len(actions) if actions else None},
        "monthly": monthly, "owners": owners, "categories": categories,
    }


def _price_for_date(db: Session, product_id: int, d: date) -> Decimal:
    row = db.scalar(
        select(SalesPriceHistory)
        .where(SalesPriceHistory.product_id == product_id, SalesPriceHistory.effective_from <= d)
        .where(or_(SalesPriceHistory.effective_to.is_(None), SalesPriceHistory.effective_to >= d))
        .order_by(SalesPriceHistory.effective_from.desc())
        .limit(1)
    )
    if row:
        return _value(row.price)
    mis = db.scalar(select(DailyMIS).where(DailyMIS.product_id == product_id, DailyMIS.mis_date <= d).order_by(DailyMIS.mis_date.desc()).limit(1))
    return _value(mis.sales_price if mis else 0)


@router.get("/schedule-impact")
def schedule_impact_report(
    as_of: date,
    months: int = Query(12, ge=1, le=36),
    product_id: str | None = None,
    plant: str | None = None,
    product_group: str | None = None,
    customer_id: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    products = _scoped_products(db, product_id, plant, product_group, customer_id)
    pids = list(products)
    start, _ = _date_bounds(as_of, months)
    if not pids:
        return {"revisions": [], "monthly": [], "summary": {}}
    rows = db.scalars(
        select(ScheduleRevision)
        .where(ScheduleRevision.product_id.in_(pids), ScheduleRevision.effective_from >= start, ScheduleRevision.effective_from <= as_of)
        .order_by(ScheduleRevision.effective_from, ScheduleRevision.product_id, ScheduleRevision.revision_no)
    ).all()
    previous: dict[tuple[int, date], Decimal] = {}
    revisions = []
    monthly_b: dict[date, dict[str, Decimal | int]] = defaultdict(lambda: {"qty_delta": ZERO, "sales_delta": ZERO, "count": 0})
    for r in rows:
        key = (r.product_id, r.month)
        prev = previous.get(key)
        if prev is None:
            prior = db.scalar(select(ScheduleRevision).where(
                ScheduleRevision.product_id == r.product_id, ScheduleRevision.month == r.month, ScheduleRevision.revision_no < r.revision_no
            ).order_by(ScheduleRevision.revision_no.desc()).limit(1))
            prev = _value(prior.monthly_target_qty) if prior else _value(r.monthly_target_qty)
        new = _value(r.monthly_target_qty); delta = new - prev
        price = _price_for_date(db, r.product_id, r.effective_from)
        sales_delta = delta * price
        p, c = products[r.product_id]
        completed = actual_before(db, r.product_id, r.effective_from)
        _, month_end = (r.month.replace(day=1), r.month.replace(day=28) + timedelta(days=4))
        month_end = month_end.replace(day=1) - timedelta(days=1)
        rem_days = working_days(db, r.effective_from, month_end, product_plant(db, r.product_id))
        revisions.append({
            "product_id": r.product_id, "product": p.name, "plant": p.plant, "customer": c.name if c else None,
            "revision_no": r.revision_no, "month": r.month.isoformat(), "effective_from": r.effective_from.isoformat(),
            "previous_target": float(prev), "new_target": float(new), "qty_delta": float(delta), "sales_delta": float(sales_delta),
            "actual_before_effective_date": float(completed), "remaining_working_days": len(rem_days),
            "new_avg_required_per_day": float(max(ZERO, new-completed)/len(rem_days)) if rem_days else 0,
            "reason": r.reason,
        })
        mb = monthly_b[_month_start(r.effective_from)]; mb["qty_delta"] += delta; mb["sales_delta"] += sales_delta; mb["count"] += 1
        previous[key] = new
    monthly = [{"label": m.strftime("%b %Y"), "date": m.isoformat(), "qty_delta": float(b["qty_delta"]), "sales_delta": float(b["sales_delta"]), "revisions": b["count"]} for m, b in sorted(monthly_b.items())]
    return {
        "revisions": revisions, "monthly": monthly,
        "summary": {"revisions": len(revisions), "qty_delta": sum((x["qty_delta"] for x in revisions), 0.0), "sales_delta": sum((x["sales_delta"] for x in revisions), 0.0)},
    }


@router.get("/month-end-forecast")
def month_end_forecast_report(
    as_of: date,
    product_id: str | None = None,
    plant: str | None = None,
    product_group: str | None = None,
    customer_id: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    products = _scoped_products(db, product_id, plant, product_group, customer_id)
    rows = []
    month_start = _month_start(as_of)
    next_month = month_start + relativedelta(months=1)
    month_end = next_month - timedelta(days=1)
    for pid, (p, c) in products.items():
        revision = active_schedule_revision(db, pid, as_of)
        if revision:
            target = _value(revision.monthly_target_qty)
        else:
            # Before a formal schedule revision exists, use the imported full-month
            # plan as a safe fallback so forecast reporting remains useful.
            target = _value(db.scalar(select(func.coalesce(func.sum(DailyMIS.plan_qty), 0)).where(
                DailyMIS.product_id == pid, DailyMIS.mis_date >= month_start, DailyMIS.mis_date <= month_end,
            )))
        actual = _value(db.scalar(select(func.coalesce(func.sum(DailyMIS.actual_qty), 0)).where(
            DailyMIS.product_id == pid, DailyMIS.mis_date >= month_start, DailyMIS.mis_date <= as_of,
        )))
        elapsed_days = working_days(db, month_start, as_of, product_plant(db, pid))
        future_days = working_days(db, as_of + timedelta(days=1), month_end, product_plant(db, pid))
        run_rate = actual / len(elapsed_days) if elapsed_days else ZERO
        projected = actual + run_rate * len(future_days)
        recovery = max(ZERO, target - actual) / len(future_days) if future_days else ZERO
        projected_comp = projected / target if target > 0 else None
        price = _price_for_date(db, pid, as_of)
        risk = "NO_TARGET"
        if target > 0:
            risk = "ON_TRACK" if projected >= target else "WATCH" if projected >= target * Decimal("0.90") else "CRITICAL"
        rows.append({
            "product_id": pid, "product": p.name, "plant": p.plant, "product_group": p.product_group, "customer": c.name if c else None,
            "target_qty": float(target), "actual_qty": float(actual), "run_rate_per_working_day": float(run_rate),
            "remaining_working_days": len(future_days), "recovery_required_per_day": float(recovery),
            "projected_qty": float(projected), "projected_gap_qty": float(projected-target),
            "projected_compliance": float(projected_comp) if projected_comp is not None else None,
            "target_sales": float(target*price), "actual_sales": float(actual*price), "projected_sales": float(projected*price),
            "projected_gap_sales": float((projected-target)*price), "risk": risk,
        })
    rows.sort(key=lambda x: ({"CRITICAL": 0, "WATCH": 1, "ON_TRACK": 2, "NO_TARGET": 3}.get(x["risk"], 9), x["projected_compliance"] or 0, x["product"]))
    return {
        "as_of": as_of.isoformat(), "month": month_start.isoformat(), "products": rows,
        "summary": {
            "target_qty": sum(x["target_qty"] for x in rows), "actual_qty": sum(x["actual_qty"] for x in rows), "projected_qty": sum(x["projected_qty"] for x in rows),
            "target_sales": sum(x["target_sales"] for x in rows), "actual_sales": sum(x["actual_sales"] for x in rows), "projected_sales": sum(x["projected_sales"] for x in rows),
            "critical": sum(1 for x in rows if x["risk"] == "CRITICAL"), "watch": sum(1 for x in rows if x["risk"] == "WATCH"), "on_track": sum(1 for x in rows if x["risk"] == "ON_TRACK"),
        },
    }
