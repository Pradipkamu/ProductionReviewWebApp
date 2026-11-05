from datetime import date
from dateutil.relativedelta import relativedelta

from fastapi import APIRouter, Depends
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..enums import ActionStatus
from ..services.filtering import csv_ints, csv_strings
from ..models import Action, ActionContext, DailyMIS, DailyRequirement, Product, User, WorkingCalendar
from ..services.planning import month_bounds

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _apply_product_filters(q, plant=None, product_group=None, customer_id=None, product_id=None):
    plants = csv_strings(plant)
    groups = csv_strings(product_group)
    customer_ids = csv_ints(customer_id)
    product_ids = csv_ints(product_id)
    if plants:
        q = q.where(Product.plant.in_(plants))
    if groups:
        q = q.where(Product.product_group.in_(groups))
    if customer_ids:
        q = q.where(Product.customer_id.in_(customer_ids))
    if product_ids:
        q = q.where(Product.id.in_(product_ids))
    return q


@router.get("/monthly")
def monthly(
    end_month: date,
    months: int = 12,
    plant: str | None = None,
    product_group: str | None = None,
    customer_id: str | None = None,
    product_id: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    first_end = end_month.replace(day=1)
    start = first_end - relativedelta(months=max(1, months)-1)
    next_after_end = first_end + relativedelta(months=1)
    month_expr = func.strftime('%Y-%m', DailyMIS.mis_date) if db.bind.dialect.name == 'sqlite' else func.to_char(DailyMIS.mis_date, 'YYYY-MM')

    # History must use the current/revised dispatch plan when one exists.
    # Schedule revisions intentionally update DailyRequirement rather than
    # overwriting the historical DailyMIS baseline plan. Aggregate the single
    # dispatch-level requirement per product/date and fall back to DailyMIS only
    # where no revised requirement exists.
    req_plan = (
        select(
            DailyRequirement.req_date.label("req_date"),
            DailyRequirement.product_id.label("product_id"),
            func.max(DailyRequirement.revised_plan_qty).label("revised_plan_qty"),
        )
        .where(
            DailyRequirement.route_operation_id.is_(None),
            DailyRequirement.req_date >= start,
            DailyRequirement.req_date < next_after_end,
        )
        .group_by(DailyRequirement.req_date, DailyRequirement.product_id)
        .subquery()
    )
    plan_qty = func.coalesce(req_plan.c.revised_plan_qty, DailyMIS.plan_qty)
    plan_sales = plan_qty * DailyMIS.sales_price
    q = (
        select(
            month_expr.label("month"),
            func.coalesce(func.sum(plan_qty),0),
            func.coalesce(func.sum(DailyMIS.actual_qty),0),
            func.coalesce(func.sum(plan_sales),0),
            func.coalesce(func.sum(DailyMIS.actual_sales),0),
            func.coalesce(func.sum(plan_qty * func.coalesce(Product.finish_weight_kg, 0) / 1000),0),
            func.coalesce(func.sum(DailyMIS.actual_qty * func.coalesce(Product.finish_weight_kg, 0) / 1000),0),
        )
        .join(Product, Product.id == DailyMIS.product_id)
        .outerjoin(
            req_plan,
            and_(
                req_plan.c.req_date == DailyMIS.mis_date,
                req_plan.c.product_id == DailyMIS.product_id,
            ),
        )
        .where(DailyMIS.mis_date >= start, DailyMIS.mis_date < next_after_end)
    )
    q = _apply_product_filters(q, plant, product_group, customer_id, product_id)
    q = q.group_by(month_expr).order_by(month_expr)
    rows = db.execute(q).all()
    return [{
        "month": m,
        "plan_qty": float(pq), "actual_qty": float(aq),
        "plan_sales": float(ps), "actual_sales": float(as_),
        "plan_tonnage_mt": float(pt), "actual_tonnage_mt": float(at),
        "sales_gap": float(as_ - ps),
        "achievement": float(as_ / ps) if ps else 0,
    } for m,pq,aq,ps,as_,pt,at in rows]


@router.get("/forecast")
def production_forecast(
    as_of: date,
    plant: str | None = None,
    product_group: str | None = None,
    customer_id: str | None = None,
    product_id: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Advisory month-end dispatch projection using recorded working-day actuals.

    A saved zero is a reported day. Missing uploads are not treated as zero:
    the run rate divides by distinct working days with saved DailyMIS rows.
    Each product uses its own plant calendar, falling back to the configured
    plant calendar when Product Master has no plant.
    """
    from ..config import get_settings
    from datetime import timedelta
    from collections import defaultdict

    first, last = month_bounds(as_of)
    products_query = select(Product).where(Product.is_active.is_(True))
    products_query = _apply_product_filters(
        products_query, plant, product_group, customer_id, product_id
    )
    products = db.scalars(products_query.order_by(Product.sort_order, Product.name)).all()
    if not products:
        return {
            "as_of": as_of.isoformat(),
            "month": first.isoformat(),
            "summary": {
                "products": 0, "products_with_actuals": 0, "plan_qty": 0.0,
                "actual_qty": 0.0, "projected_month_end_qty": None,
                "recovery_required_per_working_day": None, "coverage_pct": 0.0,
            },
            "products_detail": [],
            "method": "actual_qty / distinct reported working days × remaining working days; missing uploads are excluded from the rate and disclosed in coverage",
        }

    product_ids = [p.id for p in products]
    plants = {p.plant or get_settings().plant_name for p in products}
    calendar_rows = db.execute(
        select(WorkingCalendar.plant, WorkingCalendar.work_date, WorkingCalendar.is_working_day)
        .where(
            WorkingCalendar.plant.in_(plants),
            WorkingCalendar.work_date >= first,
            WorkingCalendar.work_date <= last,
        )
    ).all()
    calendar_by_plant: dict[str, dict[date, bool]] = defaultdict(dict)
    for row_plant, work_date, is_working_day in calendar_rows:
        calendar_by_plant[row_plant][work_date] = bool(is_working_day)

    actual_rows = db.scalars(
        select(DailyMIS).where(
            DailyMIS.product_id.in_(product_ids),
            DailyMIS.mis_date >= first,
            DailyMIS.mis_date <= as_of,
        )
    ).all()
    requirement_rows = db.scalars(
        select(DailyRequirement).where(
            DailyRequirement.product_id.in_(product_ids),
            DailyRequirement.route_operation_id.is_(None),
            DailyRequirement.req_date >= first,
            DailyRequirement.req_date <= last,
        )
    ).all()
    # Fetch MIS plan values for the full month, including dates still in the
    # future. Revised dispatch requirements take precedence per date, while
    # imported MIS plans remain the fallback for dates without a revision.
    mis_plan_rows = db.scalars(
        select(DailyMIS).where(
            DailyMIS.product_id.in_(product_ids),
            DailyMIS.mis_date >= first,
            DailyMIS.mis_date <= last,
        )
    ).all()
    actual_by_product: dict[int, list[DailyMIS]] = defaultdict(list)
    requirement_by_product: dict[int, dict[date, DailyRequirement]] = defaultdict(dict)
    mis_plan_by_product: dict[int, dict[date, DailyMIS]] = defaultdict(dict)
    for row in actual_rows:
        actual_by_product[row.product_id].append(row)
    for row in requirement_rows:
        requirement_by_product[row.product_id][row.req_date] = row
    for row in mis_plan_rows:
        mis_plan_by_product[row.product_id][row.mis_date] = row

    all_days = []
    day = first
    while day <= last:
        all_days.append(day)
        day += timedelta(days=1)

    details = []
    total_plan = 0.0
    total_actual = 0.0
    total_elapsed = 0
    total_reported = 0
    total_remaining = 0
    projected_values = []
    recovery_values = []
    products_with_actuals = 0

    for product in products:
        product_plant = product.plant or get_settings().plant_name
        overrides = calendar_by_plant.get(product_plant, {})
        working = [d for d in all_days if overrides.get(d, True)]
        elapsed = [d for d in working if d <= as_of]
        remaining = [d for d in working if d > as_of]
        working_set = set(working)
        mis = [row for row in actual_by_product.get(product.id, []) if row.mis_date in working_set]
        reported_dates = {row.mis_date for row in mis}
        actual_qty = sum(float(row.actual_qty or 0) for row in mis)
        revised_by_date = requirement_by_product.get(product.id, {})
        mis_plan_by_date = mis_plan_by_product.get(product.id, {})
        plan_qty = 0.0
        revised_days = 0
        mis_fallback_days = 0
        for work_date in working:
            revised_row = revised_by_date.get(work_date)
            if revised_row is not None:
                plan_qty += float(revised_row.revised_plan_qty or 0)
                revised_days += 1
                continue
            mis_plan_row = mis_plan_by_date.get(work_date)
            if mis_plan_row is not None:
                plan_qty += float(mis_plan_row.plan_qty or 0)
                mis_fallback_days += 1
        if revised_days and mis_fallback_days:
            plan_source = "REVISED_REQUIREMENT_WITH_DAILY_MIS_FALLBACK"
        elif revised_days:
            plan_source = "REVISED_DISPATCH_REQUIREMENT"
        elif mis_fallback_days:
            plan_source = "DAILY_MIS_FALLBACK"
        else:
            plan_source = "NO_PLAN_ROWS"

        reported_days = len(reported_dates)
        run_rate = actual_qty / reported_days if reported_days else None
        projected = (
            actual_qty + run_rate * len(remaining)
            if run_rate is not None else None
        )
        recovery = (
            max(0.0, plan_qty - actual_qty) / len(remaining)
            if remaining else (0.0 if actual_qty >= plan_qty else None)
        )
        if reported_days:
            products_with_actuals += 1
            projected_values.append(projected)
        if recovery is not None:
            recovery_values.append(recovery)

        total_plan += plan_qty
        total_actual += actual_qty
        total_elapsed += len(elapsed)
        total_reported += reported_days
        total_remaining += len(remaining)
        details.append({
            "product_id": product.id,
            "product_code": product.code,
            "product": product.name,
            "plant": product_plant,
            "plan_qty": round(plan_qty, 3),
            "actual_qty": round(actual_qty, 3),
            "projected_month_end_qty": round(projected, 3) if projected is not None else None,
            "run_rate_per_reported_working_day": round(run_rate, 3) if run_rate is not None else None,
            "recovery_required_per_remaining_working_day": round(recovery, 3) if recovery is not None else None,
            "elapsed_working_days": len(elapsed),
            "reported_working_days": reported_days,
            "remaining_working_days": len(remaining),
            "coverage_pct": round(reported_days / len(elapsed) * 100, 1) if elapsed else 0.0,
            "plan_source": plan_source,
            "status": (
                "NO_REPORTED_ACTUALS" if run_rate is None
                else "NO_REMAINING_WORKDAYS" if not remaining
                else "PROJECTED_BELOW_PLAN" if projected < plan_qty
                else "PROJECTED_ON_TRACK"
            ),
        })

    complete_projection = len(projected_values) == len(products)
    coverage = total_reported / total_elapsed * 100 if total_elapsed else 0.0
    return {
        "as_of": as_of.isoformat(),
        "month": first.isoformat(),
        "summary": {
            "products": len(products),
            "products_with_actuals": products_with_actuals,
            "plan_qty": round(total_plan, 3),
            "actual_qty": round(total_actual, 3),
            "projected_month_end_qty": round(sum(projected_values), 3) if complete_projection else None,
            "recovery_required_per_working_day": round(sum(recovery_values), 3) if len(recovery_values) == len(products) else None,
            "elapsed_working_days": total_elapsed,
            "reported_working_days": total_reported,
            "remaining_working_days_across_products": total_remaining,
            "coverage_pct": round(coverage, 1),
            "projection_complete": complete_projection,
        },
        "products_detail": details,
        "method": "per product: actual quantity ÷ distinct reported working days × remaining working days; saved zero-actual rows count as reported; missing days are not treated as zero; plant WorkingCalendar overrides weekdays/default working days",
    }


@router.get("/actions")
def action_analytics(
    plant: str | None = None,
    product_group: str | None = None,
    customer_id: str | None = None,
    product_id: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    base = (
        select(Action.id)
        .select_from(Action)
        .join(ActionContext, ActionContext.action_id == Action.id)
        .join(Product, Product.id == ActionContext.product_id)
    )
    base = _apply_product_filters(base, plant, product_group, customer_id, product_id)
    scoped_action_ids = list(db.scalars(base.distinct()).all())
    if not scoped_action_ids:
        return {"total": 0, "open": 0, "closed": 0, "by_reason": []}
    total = db.scalar(select(func.count(Action.id)).where(Action.id.in_(scoped_action_ids))) or 0
    open_ = db.scalar(select(func.count(Action.id)).where(Action.id.in_(scoped_action_ids), Action.status != ActionStatus.CLOSED)) or 0
    closed = total - open_
    by_reason = db.execute(
        select(Action.problem_category, func.count(Action.id))
        .where(Action.id.in_(scoped_action_ids))
        .group_by(Action.problem_category)
        .order_by(func.count(Action.id).desc())
    ).all()
    return {
        "total": int(total), "open": int(open_), "closed": int(closed),
        "by_reason": [{"reason": r or "Unspecified", "count": int(c)} for r,c in by_reason],
    }
