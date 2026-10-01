from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from ..enums import ActionStatus
from ..models import (
    Action, ActionContext, DailyMIS, DailyRequirement, Product,
    ProcessDailySummary, RouteOperation, Operation,
)
from .planning import recovery_required_per_day


def _d(v) -> Decimal:
    return Decimal(str(v or 0))


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
            "exceptions": [],
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
        "exceptions": products[:15],
    }


def process_monitor(db: Session, product_id: int, d: date) -> dict:
    from .planning import get_active_route
    route = get_active_route(db, product_id, d)
    if not route:
        return {"product_id": product_id, "date": d.isoformat(), "route": None, "operations": []}
    ops = db.execute(
        select(RouteOperation, Operation)
        .join(Operation, Operation.id == RouteOperation.operation_id)
        .where(RouteOperation.route_version_id == route.id, RouteOperation.is_enabled.is_(True))
        .order_by(RouteOperation.sequence_no)
    ).all()
    from ..models import ProcessFlowVersion
    explicit_flow = db.scalar(select(ProcessFlowVersion.id).where(ProcessFlowVersion.route_version_id == route.id))
    out = []
    prior_actual = None
    for ro, op in ops:
        summary = db.scalar(select(ProcessDailySummary).where(
            ProcessDailySummary.summary_date == d,
            ProcessDailySummary.product_id == product_id,
            ProcessDailySummary.route_operation_id == ro.id,
        ))
        req = db.scalar(select(DailyRequirement).where(
            DailyRequirement.req_date == d,
            DailyRequirement.product_id == product_id,
            DailyRequirement.route_operation_id == ro.id,
        ))
        actual = _d(summary.actual_qty if summary else 0)
        plan = _d(req.revised_plan_qty if req else (summary.plan_qty if summary else 0))
        wip = max(Decimal("0"), prior_actual - actual) if prior_actual is not None else Decimal("0")
        action_count = db.scalar(
            select(func.count(ActionContext.id))
            .join(Action, Action.id == ActionContext.action_id)
            .where(
                ActionContext.context_date == d,
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
        "route_revision": route.revision_no,
        "operations": out,
    }
