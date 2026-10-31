from datetime import date
from dateutil.relativedelta import relativedelta

from fastapi import APIRouter, Depends
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..enums import ActionStatus
from ..services.filtering import csv_ints, csv_strings
from ..models import (
    Action, ActionContext, DailyMIS, DailyRequirement, Product, User,
    ProcessFlowStage, ProcessFlowVersion,
)

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

    # Schedule precedence:
    # 1) DailyRequirement attached to the effective parent-dispatch stage
    #    (the explicit Disp_Done stage for the active process-flow revision);
    # 2) legacy dispatch-level DailyRequirement (route_operation_id IS NULL);
    # 3) imported DailyMIS plan as the final compatibility fallback.
    # Upstream stage requirements must never be added to the customer dispatch plan.
    active_dispatch_route_id = (
        select(ProcessFlowStage.route_operation_id)
        .join(ProcessFlowVersion, ProcessFlowVersion.id == ProcessFlowStage.flow_id)
        .where(
            ProcessFlowVersion.product_id == DailyRequirement.product_id,
            ProcessFlowVersion.effective_from <= DailyRequirement.req_date,
            ProcessFlowStage.parent_dispatch.is_(True),
            ProcessFlowStage.is_active.is_(True),
            ProcessFlowStage.route_operation_id.is_not(None),
        )
        .order_by(ProcessFlowVersion.effective_from.desc(), ProcessFlowVersion.revision_no.desc())
        .limit(1)
        .correlate(DailyRequirement)
        .scalar_subquery()
    )
    stage_dispatch_plan = (
        select(
            DailyRequirement.req_date.label("req_date"),
            DailyRequirement.product_id.label("product_id"),
            func.max(DailyRequirement.revised_plan_qty).label("revised_plan_qty"),
        )
        .where(
            DailyRequirement.route_operation_id == active_dispatch_route_id,
            DailyRequirement.req_date >= start,
            DailyRequirement.req_date < next_after_end,
        )
        .group_by(DailyRequirement.req_date, DailyRequirement.product_id)
        .subquery()
    )
    legacy_dispatch_plan = (
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
    plan_qty = func.coalesce(
        stage_dispatch_plan.c.revised_plan_qty,
        legacy_dispatch_plan.c.revised_plan_qty,
        DailyMIS.plan_qty,
    )
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
            stage_dispatch_plan,
            and_(
                stage_dispatch_plan.c.req_date == DailyMIS.mis_date,
                stage_dispatch_plan.c.product_id == DailyMIS.product_id,
            ),
        )
        .outerjoin(
            legacy_dispatch_plan,
            and_(
                legacy_dispatch_plan.c.req_date == DailyMIS.mis_date,
                legacy_dispatch_plan.c.product_id == DailyMIS.product_id,
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
