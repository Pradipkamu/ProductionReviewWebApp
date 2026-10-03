from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from ..enums import ActionStatus
from ..models import (
    Action, ActionContext, DailyMIS, DailyRequirement, Product,
    ProcessDailySummary, RouteOperation, Operation, ProcessFlowVersion,
    QualityRejectionDaily, VendorMovement,
)
from .planning import recovery_required_per_day


def _d(v) -> Decimal:
    return Decimal(str(v or 0))


def daily_control_summary(
    db: Session,
    as_of: date,
    plants: list[str] | None = None,
    product_groups: list[str] | None = None,
    customer_ids: list[int] | None = None,
    product_ids: list[int] | None = None,
    compliance_target: Decimal = Decimal("0.90"),
    critical_target: Decimal = Decimal("0.80"),
    blocker_threshold_pct: float = 80.0,
) -> dict:
    """One daily readiness/upload/exception view.

    Missing required rows remain blockers. A stored zero actual is intentionally
    ignored for output/compliance alerts. Average compliance is calculated over
    month-to-date rows that have both a positive plan and a positive actual; if
    that average falls below the configurable blocker threshold, a blocker is
    raised for the product or stage.
    """
    q = select(Product).where(Product.is_active.is_(True))
    if plants:
        q = q.where(Product.plant.in_(plants))
    if product_groups:
        q = q.where(Product.product_group.in_(product_groups))
    if customer_ids:
        q = q.where(Product.customer_id.in_(customer_ids))
    if product_ids:
        q = q.where(Product.id.in_(product_ids))
    products = list(db.scalars(q.order_by(Product.sort_order, Product.name)).all())
    ids = [p.id for p in products]
    names = {p.id: p.name for p in products}
    if not ids:
        return {
            "as_of": as_of.isoformat(), "workflow": {}, "counts": {},
            "alerts": [], "upcoming": {"through": (as_of + timedelta(days=7)).isoformat(), "planned_days": 0, "planned_products": 0},
        }

    requirements = list(db.scalars(select(DailyRequirement).where(
        DailyRequirement.req_date == as_of,
        DailyRequirement.product_id.in_(ids),
        DailyRequirement.revised_plan_qty > 0,
    )).all())
    customer_plan: dict[int, Decimal] = {}
    stage_plan: dict[tuple[int, int], Decimal] = {}
    for row in requirements:
        if row.route_operation_id is None:
            customer_plan[row.product_id] = max(customer_plan.get(row.product_id, Decimal("0")), _d(row.revised_plan_qty))
        else:
            key = (row.product_id, row.route_operation_id)
            stage_plan[key] = max(stage_plan.get(key, Decimal("0")), _d(row.revised_plan_qty))

    mis_rows = list(db.scalars(select(DailyMIS).where(DailyMIS.mis_date == as_of, DailyMIS.product_id.in_(ids))).all())
    mis = {r.product_id: r for r in mis_rows}
    stage_rows = list(db.scalars(select(ProcessDailySummary).where(
        ProcessDailySummary.summary_date == as_of,
        ProcessDailySummary.product_id.in_(ids),
    )).all())
    stage_actual = {(r.product_id, r.route_operation_id): r for r in stage_rows}
    operations = {
        ro.id: op.name for ro, op in db.execute(
            select(RouteOperation, Operation)
            .join(Operation, Operation.id == RouteOperation.operation_id)
            .where(RouteOperation.id.in_([key[1] for key in stage_plan] or [-1]))
        ).all()
    }

    blocker_threshold = Decimal(str(blocker_threshold_pct)) / Decimal("100")
    month_start = as_of.replace(day=1)

    # Month-to-date average compliance. Reported zero actuals are deliberately
    # excluded from the average, per review rule; missing rows remain blockers.
    dispatch_plan_by_day: dict[tuple[date, int], Decimal] = {}
    for req in db.scalars(select(DailyRequirement).where(
        DailyRequirement.req_date >= month_start,
        DailyRequirement.req_date <= as_of,
        DailyRequirement.product_id.in_(ids),
        DailyRequirement.route_operation_id.is_(None),
        DailyRequirement.revised_plan_qty > 0,
    )).all():
        dispatch_plan_by_day[(req.req_date, req.product_id)] = _d(req.revised_plan_qty)

    dispatch_totals: dict[int, dict[str, Decimal]] = defaultdict(lambda: {"plan": Decimal("0"), "actual": Decimal("0")})
    for row in db.scalars(select(DailyMIS).where(
        DailyMIS.mis_date >= month_start,
        DailyMIS.mis_date <= as_of,
        DailyMIS.product_id.in_(ids),
    )).all():
        actual_qty = _d(row.actual_qty)
        plan_qty = dispatch_plan_by_day.get((row.mis_date, row.product_id), _d(row.plan_qty))
        if actual_qty <= 0 or plan_qty <= 0:
            continue
        dispatch_totals[row.product_id]["plan"] += plan_qty
        dispatch_totals[row.product_id]["actual"] += actual_qty

    dispatch_average = {
        pid: vals["actual"] / vals["plan"]
        for pid, vals in dispatch_totals.items()
        if vals["plan"] > 0
    }

    stage_req_by_day: dict[tuple[date, int, int], Decimal] = {}
    stage_route_ids = list({key[1] for key in stage_plan})
    if stage_route_ids:
        for req in db.scalars(select(DailyRequirement).where(
            DailyRequirement.req_date >= month_start,
            DailyRequirement.req_date <= as_of,
            DailyRequirement.product_id.in_(ids),
            DailyRequirement.route_operation_id.in_(stage_route_ids),
            DailyRequirement.revised_plan_qty > 0,
        )).all():
            stage_req_by_day[(req.req_date, req.product_id, req.route_operation_id)] = _d(req.revised_plan_qty)

    stage_totals: dict[tuple[int, int], dict[str, Decimal]] = defaultdict(lambda: {"plan": Decimal("0"), "actual": Decimal("0")})
    if stage_route_ids:
        for row in db.scalars(select(ProcessDailySummary).where(
            ProcessDailySummary.summary_date >= month_start,
            ProcessDailySummary.summary_date <= as_of,
            ProcessDailySummary.product_id.in_(ids),
            ProcessDailySummary.route_operation_id.in_(stage_route_ids),
        )).all():
            actual_qty = _d(row.actual_qty)
            plan_qty = stage_req_by_day.get((row.summary_date, row.product_id, row.route_operation_id), _d(row.plan_qty))
            if actual_qty <= 0 or plan_qty <= 0:
                continue
            key = (row.product_id, row.route_operation_id)
            stage_totals[key]["plan"] += plan_qty
            stage_totals[key]["actual"] += actual_qty

    stage_average = {
        key: vals["actual"] / vals["plan"]
        for key, vals in stage_totals.items()
        if vals["plan"] > 0
    }

    alerts: list[dict] = []
    rank = {"BLOCKER": 0, "CRITICAL": 1, "WARNING": 2, "WATCH": 3}

    def add(severity, kind, detail, product_id=None, value=None, plan=None, actual=None, action="review"):
        alerts.append({
            "severity": severity, "kind": kind, "detail": detail,
            "product_id": product_id, "product": names.get(product_id, ""),
            "value": float(value) if value is not None else None,
            "plan_qty": float(plan) if plan is not None else None,
            "actual_qty": float(actual) if actual is not None else None,
            "action": action,
        })

    for pid, plan in customer_plan.items():
        row = mis.get(pid)
        if row is None:
            add("BLOCKER", "missing_dispatch_actual", "Daily MIS / dispatch actual has not been uploaded", pid, plan=plan, action="upload")
            continue
        actual = _d(row.actual_qty)
        avg_ratio = dispatch_average.get(pid)
        if avg_ratio is not None and avg_ratio < blocker_threshold:
            add(
                "BLOCKER", "low_average_dispatch_compliance",
                f"Month-to-date average dispatch is {avg_ratio * 100:.1f}% below the {blocker_threshold_pct:g}% blocker threshold",
                pid, avg_ratio, plan, actual, "action",
            )
        if _d(row.sales_price) <= 0:
            add("WARNING", "price_missing", "Effective sales price is missing; sales risk cannot be valued", pid, action="data-quality")

    for (pid, operation_id), plan in stage_plan.items():
        row = stage_actual.get((pid, operation_id))
        stage_name = operations.get(operation_id, f"Stage #{operation_id}")
        if row is None:
            add("BLOCKER", "missing_stage_actual", f"{stage_name}: actual has not been uploaded", pid, plan=plan, action="upload")
            continue
        actual = _d(row.actual_qty)
        avg_ratio = stage_average.get((pid, operation_id))
        if avg_ratio is not None and avg_ratio < blocker_threshold:
            add(
                "BLOCKER", "low_average_stage_compliance",
                f"{stage_name}: month-to-date average is {avg_ratio * 100:.1f}% below the {blocker_threshold_pct:g}% blocker threshold",
                pid, avg_ratio, plan, actual, "process",
            )

    quality_rows = list(db.scalars(select(QualityRejectionDaily).where(
        QualityRejectionDaily.rejection_date == as_of,
        QualityRejectionDaily.product_id.in_(ids),
    )).all())
    quality_by_product: dict[int, list[QualityRejectionDaily]] = {}
    for row in quality_rows:
        quality_by_product.setdefault(row.product_id, []).append(row)
    for pid, rows in quality_by_product.items():
        reject = sum((_d(x.reject_qty) for x in rows), Decimal("0"))
        if reject <= 0:
            continue
        denoms: dict[tuple, Decimal] = {}
        pending = False
        for row in rows:
            key = (row.shift, row.detection_route_operation_id, row.machine_id, row.denominator_source)
            qty = _d(row.denominator_qty)
            if qty > 0:
                denoms[key] = max(denoms.get(key, Decimal("0")), qty)
            elif _d(row.reject_qty) > 0:
                pending = True
        denominator = sum(denoms.values(), Decimal("0"))
        if pending or denominator <= 0:
            add("BLOCKER", "ppm_denominator_pending", f"{reject:g} rejection(s) reported but the PPM denominator is missing", pid, reject, action="data-quality")
        else:
            ppm = reject / denominator * Decimal("1000000")
            if ppm >= Decimal("5000"):
                add("CRITICAL", "high_daily_ppm", f"Daily rejection is {ppm:,.0f} PPM", pid, ppm, action="action")
            elif ppm >= Decimal("1000"):
                add("WARNING", "high_daily_ppm", f"Daily rejection is {ppm:,.0f} PPM", pid, ppm, action="action")

    active_flow_products = set(db.scalars(select(ProcessFlowVersion.product_id).where(
        ProcessFlowVersion.product_id.in_(list(customer_plan) or [-1]),
        ProcessFlowVersion.effective_from <= as_of,
    )).all())
    planned_stage_products = {key[0] for key in stage_plan}
    for pid in sorted(active_flow_products - planned_stage_products):
        add("BLOCKER", "missing_stage_plan", "Customer plan exists but no stage plan is available for this date", pid, plan=customer_plan.get(pid), action="schedule")
    for pid in sorted(set(customer_plan) - active_flow_products):
        add("BLOCKER", "process_flow_missing", "Customer plan exists but the effective process flow is not configured", pid, plan=customer_plan.get(pid), action="data-quality")

    overdue_actions = list(db.scalars(select(Action).where(
        Action.status != ActionStatus.CLOSED,
        Action.due_at.is_not(None),
        Action.due_at < datetime.combine(as_of, time.min),
    )).all())
    for action_row in overdue_actions:
        context_ids = set(db.scalars(select(ActionContext.product_id).where(
            ActionContext.action_id == action_row.id,
            ActionContext.product_id.in_(ids),
        )).all())
        if context_ids:
            days = (as_of - action_row.due_at.date()).days
            add("WARNING", "overdue_action", f"{action_row.action_no} is overdue by {days} day(s)", next(iter(context_ids)), days, action="actions")

    vendor_rows = list(db.scalars(select(VendorMovement).where(
        VendorMovement.product_id.in_(ids),
        VendorMovement.expected_return_date.is_not(None),
        VendorMovement.expected_return_date < as_of,
        VendorMovement.outward_qty > VendorMovement.receipt_qty,
    )).all())
    for movement in vendor_rows:
        pending = _d(movement.outward_qty) - _d(movement.receipt_qty)
        add("WARNING", "overdue_vendor_wip", f"Vendor receipt was expected {movement.expected_return_date}", movement.product_id, pending, action="vendor")

    future = list(db.scalars(select(DailyRequirement).where(
        DailyRequirement.req_date > as_of,
        DailyRequirement.req_date <= as_of + timedelta(days=7),
        DailyRequirement.product_id.in_(ids),
        DailyRequirement.route_operation_id.is_(None),
        DailyRequirement.revised_plan_qty > 0,
    )).all())
    future_keys = {(r.req_date, r.product_id) for r in future}
    missing_customer = len(set(customer_plan) - set(mis))
    missing_stage = len(set(stage_plan) - set(stage_actual))
    blockers = sum(1 for x in alerts if x["severity"] == "BLOCKER")
    critical = sum(1 for x in alerts if x["severity"] == "CRITICAL")
    warnings = sum(1 for x in alerts if x["severity"] == "WARNING")
    alerts.sort(key=lambda x: (rank.get(x["severity"], 9), x["product"], x["detail"]))
    has_plan = bool(customer_plan or stage_plan)
    schedule_status = "NO PLAN" if not has_plan else "ATTENTION" if any(x["kind"] in {"missing_stage_plan", "process_flow_missing"} for x in alerts) else "READY"
    expected = len(customer_plan) + len(stage_plan)
    reported = len(set(customer_plan) & set(mis)) + len(set(stage_plan) & set(stage_actual))
    upload_status = "NO PLAN" if expected == 0 else "COMPLETE" if reported == expected else "NOT STARTED" if reported == 0 else "PARTIAL"
    review_status = "BLOCKED" if blockers else "CRITICAL" if critical else "ATTENTION" if warnings else "CLEAR"
    return {
        "as_of": as_of.isoformat(),
        "workflow": {
            "schedule": {"status": schedule_status, "planned_products": len(customer_plan), "planned_stages": len(stage_plan)},
            "upload": {"status": upload_status, "expected_rows": expected, "reported_rows": reported, "missing_customer_rows": missing_customer, "missing_stage_rows": missing_stage},
            "review": {"status": review_status, "blockers": blockers, "critical": critical, "warnings": warnings, "blocker_threshold_pct": float(blocker_threshold_pct)},
        },
        "counts": {
            "planned_products": len(customer_plan), "reported_products": len(set(customer_plan) & set(mis)),
            "planned_stages": len(stage_plan), "reported_stages": len(set(stage_plan) & set(stage_actual)),
            "blockers": blockers, "critical": critical, "warnings": warnings,
        },
        "alerts": alerts[:100],
        "upcoming": {
            "through": (as_of + timedelta(days=7)).isoformat(),
            "planned_days": len({x[0] for x in future_keys}),
            "planned_products": len({x[1] for x in future_keys}),
        },
    }


def daily_review_summary(
    db: Session,
    as_of: date,
    plants: list[str] | None = None,
    product_groups: list[str] | None = None,
    customer_ids: list[int] | None = None,
    product_ids: list[int] | None = None,
) -> dict:
    month_start = as_of.replace(day=1)

    product_scope_q = select(Product.id)
    plants = plants or []
    product_groups = product_groups or []
    customer_ids = customer_ids or []
    product_ids = product_ids or []
    if plants:
        product_scope_q = product_scope_q.where(Product.plant.in_(plants))
    if product_groups:
        product_scope_q = product_scope_q.where(Product.product_group.in_(product_groups))
    if customer_ids:
        product_scope_q = product_scope_q.where(Product.customer_id.in_(customer_ids))
    if product_ids:
        product_scope_q = product_scope_q.where(Product.id.in_(product_ids))
    scoped_ids = list(db.scalars(product_scope_q).all())

    if not scoped_ids:
        return {
            "as_of": as_of.isoformat(),
            "filters": {"plant": plants, "product_group": product_groups, "customer_id": customer_ids, "product_id": product_ids},
            "kpis": {
                "plan_qty": 0, "actual_qty": 0, "qty_gap": 0,
                "plan_sales": 0, "actual_sales": 0, "sales_gap": 0,
                "plan_tonnage_mt": 0, "actual_tonnage_mt": 0, "tonnage_gap_mt": 0,
                "achievement": 0, "critical_products": 0, "watch_products": 0,
                "open_actions": 0, "overdue_actions": 0, "closed_today": 0,
            },
            "exceptions": [], "ok_products": [], "products": [],
        }

    rows = db.execute(
        select(DailyMIS, Product, DailyRequirement)
        .join(Product, Product.id == DailyMIS.product_id)
        .outerjoin(
            DailyRequirement,
            and_(
                DailyRequirement.req_date == DailyMIS.mis_date,
                DailyRequirement.product_id == DailyMIS.product_id,
                DailyRequirement.route_operation_id.is_(None),
            ),
        )
        .where(
            DailyMIS.mis_date >= month_start,
            DailyMIS.mis_date <= as_of,
            DailyMIS.product_id.in_(scoped_ids),
        )
        .order_by(Product.sort_order, DailyMIS.mis_date)
    ).all()

    agg: dict[int, dict] = defaultdict(lambda: {
        "plan_qty": Decimal("0"), "actual_qty": Decimal("0"),
        "plan_sales": Decimal("0"), "actual_sales": Decimal("0"),
        "plan_tonnage": Decimal("0"), "actual_tonnage": Decimal("0"),
    })
    product_names: dict[int, dict] = {}
    for mis, product, req in rows:
        plan_qty = _d(req.revised_plan_qty if req else mis.plan_qty)
        actual_qty = _d(mis.actual_qty)
        price = _d(mis.sales_price)
        weight = _d(product.finish_weight_kg)
        a = agg[product.id]
        a["plan_qty"] += plan_qty
        a["actual_qty"] += actual_qty
        a["plan_sales"] += plan_qty * price
        a["actual_sales"] += actual_qty * price
        a["plan_tonnage"] += plan_qty * weight / Decimal("1000")
        a["actual_tonnage"] += actual_qty * weight / Decimal("1000")
        product_names[product.id] = {
            "name": product.name,
            "customer_id": product.customer_id,
            "plant": product.plant,
            "product_group": product.product_group,
            "finish_weight_kg": product.finish_weight_kg,
        }

    products = []
    total_plan_qty = total_actual_qty = Decimal("0")
    total_plan_sales = total_actual_sales = Decimal("0")
    total_plan_tonnage = total_actual_tonnage = Decimal("0")
    critical = 0
    watch = 0
    for pid, a in agg.items():
        meta = product_names[pid]
        pqty, aqty = a["plan_qty"], a["actual_qty"]
        psales, asales = a["plan_sales"], a["actual_sales"]
        pton, aton = a["plan_tonnage"], a["actual_tonnage"]
        ach = float(aqty / pqty) if pqty > 0 else None
        gap_qty = aqty - pqty
        gap_sales = asales - psales
        if pqty <= 0:
            status = "NO PLAN"
        elif ach is not None and ach < 0.80:
            status = "CRITICAL"; critical += 1
        elif ach is not None and ach < 0.90:
            status = "WATCH"; watch += 1
        elif ach is not None and ach < 1.0:
            status = "GOOD"
        else:
            status = "DONE"
        recovery = recovery_required_per_day(db, pid, as_of)
        products.append({
            "product_id": pid,
            "product": meta["name"],
            "customer_id": meta["customer_id"],
            "plant": meta["plant"],
            "product_group": meta["product_group"],
            "finish_weight_kg": float(meta["finish_weight_kg"]) if meta["finish_weight_kg"] is not None else None,
            "plan_qty": float(pqty), "actual_qty": float(aqty), "gap_qty": float(gap_qty),
            "plan_sales": float(psales), "actual_sales": float(asales), "gap_sales": float(gap_sales),
            "plan_tonnage_mt": float(pton), "actual_tonnage_mt": float(aton), "tonnage_gap_mt": float(aton - pton),
            "achievement": ach, "status": status, "recovery_qty_per_day": float(recovery),
        })
        total_plan_qty += pqty
        total_actual_qty += aqty
        total_plan_sales += psales
        total_actual_sales += asales
        total_plan_tonnage += pton
        total_actual_tonnage += aton

    products.sort(key=lambda x: x["gap_sales"])
    priority_products = [x for x in products if x["status"] in {"CRITICAL", "WATCH", "NO PLAN"}]
    ok_products = [x for x in products if x["status"] in {"GOOD", "DONE"}]

    # Action KPIs follow the same product scope as the dashboard filters.
    now = datetime.utcnow()
    action_base = (
        select(func.count(func.distinct(Action.id)))
        .select_from(Action)
        .outerjoin(ActionContext, ActionContext.action_id == Action.id)
        .where(ActionContext.product_id.in_(scoped_ids))
    )
    open_actions = db.scalar(action_base.where(Action.status != ActionStatus.CLOSED)) or 0
    overdue_actions = db.scalar(action_base.where(
        Action.status != ActionStatus.CLOSED,
        Action.due_at.is_not(None),
        Action.due_at < now,
    )) or 0
    day_start = datetime.combine(as_of, time.min)
    day_end = day_start + timedelta(days=1)
    closed_today = db.scalar(action_base.where(
        Action.status == ActionStatus.CLOSED,
        Action.closed_at.is_not(None),
        Action.closed_at >= day_start,
        Action.closed_at < day_end,
    )) or 0

    return {
        "as_of": as_of.isoformat(),
        "filters": {"plant": plants, "product_group": product_groups, "customer_id": customer_ids, "product_id": product_ids},
        "kpis": {
            "plan_qty": float(total_plan_qty),
            "actual_qty": float(total_actual_qty),
            "qty_gap": float(total_actual_qty - total_plan_qty),
            "plan_sales": float(total_plan_sales),
            "actual_sales": float(total_actual_sales),
            "sales_gap": float(total_actual_sales - total_plan_sales),
            "plan_tonnage_mt": float(total_plan_tonnage),
            "actual_tonnage_mt": float(total_actual_tonnage),
            "tonnage_gap_mt": float(total_actual_tonnage - total_plan_tonnage),
            "achievement": float(total_actual_sales / total_plan_sales) if total_plan_sales > 0 else 0,
            "critical_products": critical,
            "watch_products": watch,
            "open_actions": int(open_actions),
            "overdue_actions": int(overdue_actions),
            "closed_today": int(closed_today),
        },
        "exceptions": priority_products,
        "ok_products": ok_products,
        "products": products,
    }


def process_monitor(db: Session, product_id: int, d: date, start_date: date | None = None) -> dict:
    from .planning import get_active_route, working_days, product_plant
    period_start = start_date or d
    if period_start > d:
        raise ValueError("start_date must be on or before monitor date")
    route = get_active_route(db, product_id, d)
    if not route:
        return {"product_id": product_id, "date": d.isoformat(), "route": None, "operations": []}
    effective_start = max(period_start, route.effective_from)
    work_dates = working_days(db, effective_start, d, product_plant(db, product_id))
    work_set = set(work_dates)
    ops = db.execute(
        select(RouteOperation, Operation)
        .join(Operation, Operation.id == RouteOperation.operation_id)
        .where(RouteOperation.route_version_id == route.id, RouteOperation.is_enabled.is_(True))
        .order_by(RouteOperation.sequence_no)
    ).all()
    route_ids = [ro.id for ro, _ in ops]
    summaries_by_route: dict[int, list[ProcessDailySummary]] = defaultdict(list)
    reqs_by_route: dict[int, list[DailyRequirement]] = defaultdict(list)
    if route_ids and work_dates:
        for row in db.scalars(select(ProcessDailySummary).where(
            ProcessDailySummary.product_id == product_id,
            ProcessDailySummary.route_operation_id.in_(route_ids),
            ProcessDailySummary.summary_date >= effective_start,
            ProcessDailySummary.summary_date <= d,
        )):
            if row.summary_date in work_set:
                summaries_by_route[row.route_operation_id].append(row)
        for row in db.scalars(select(DailyRequirement).where(
            DailyRequirement.product_id == product_id,
            DailyRequirement.route_operation_id.in_(route_ids),
            DailyRequirement.req_date >= effective_start,
            DailyRequirement.req_date <= d,
        )):
            if row.req_date in work_set:
                reqs_by_route[row.route_operation_id].append(row)
    from ..models import ProcessFlowVersion
    explicit_flow = db.scalar(select(ProcessFlowVersion.id).where(ProcessFlowVersion.route_version_id == route.id))
    out = []
    prior_actual = None
    for ro, op in ops:
        summary_rows = summaries_by_route.get(ro.id, [])
        req_rows = reqs_by_route.get(ro.id, [])
        data_days = len({r.summary_date for r in summary_rows})
        plan_days = len({r.req_date for r in req_rows})
        actual = (sum((_d(r.actual_qty) for r in summary_rows), Decimal("0")) / data_days) if data_days else Decimal("0")
        reject = (sum((_d(r.reject_qty) for r in summary_rows), Decimal("0")) / data_days) if data_days else Decimal("0")
        if plan_days:
            plan = sum((_d(r.revised_plan_qty) for r in req_rows), Decimal("0")) / plan_days
        elif data_days:
            plan = sum((_d(r.plan_qty) for r in summary_rows), Decimal("0")) / data_days
        else:
            plan = Decimal("0")
        wip = max(Decimal("0"), prior_actual - actual) if prior_actual is not None else Decimal("0")
        action_count = db.scalar(
            select(func.count(ActionContext.id))
            .join(Action, Action.id == ActionContext.action_id)
            .where(
                ActionContext.context_date >= effective_start,
                ActionContext.context_date <= d,
                ActionContext.product_id == product_id,
                ActionContext.route_operation_id == ro.id,
                Action.status != ActionStatus.CLOSED,
            )
        ) or 0
        out.append({
            "route_operation_id": ro.id,
            "sequence_no": ro.sequence_no,
            "operation": op.name,
            "operation_type": op.operation_type.value,
            "vendor_id": ro.vendor_id,
            "plan_qty": float(plan),
            "actual_qty": float(actual),
            "reject_qty": float(reject),
            "days_with_plan": plan_days,
            "days_with_data": data_days,
            "gap_qty": float(actual - plan),
            "achievement": float(actual / plan) if plan > 0 else None,
            "calculated_wip_from_previous": None if explicit_flow else float(wip),
            "open_actions": int(action_count),
            "is_dispatch": ro.is_dispatch,
        })
        prior_actual = actual
    return {
        "product_id": product_id,
        "date": d.isoformat(),
        "period": {
            "requested_start": period_start.isoformat(),
            "start": effective_start.isoformat(),
            "end": d.isoformat(),
            "working_days": len(work_dates),
            "off_days": (d - effective_start).days + 1 - len(work_dates),
            "is_range": period_start != d,
            "truncated_to_route": effective_start != period_start,
        },
        "route_revision": route.revision_no,
        "operations": out,
    }
