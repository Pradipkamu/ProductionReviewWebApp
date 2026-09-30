from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..models import DailyMIS, DailyRequirement, MISChangeLog, Product, User
from ..services.filtering import csv_ints, csv_strings
from ..schemas import MISEdit

router = APIRouter(prefix="/mis", tags=["mis"])


@router.get("")
def list_mis(
    mis_date: date,
    plant: str | None = None,
    product_group: str | None = None,
    customer_id: str | None = None,
    product_id: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = (
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
        .where(DailyMIS.mis_date == mis_date)
    )
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
    rows = db.execute(q.order_by(Product.sort_order, Product.name)).all()
    out=[]
    for mis,p,req in rows:
        current_plan = req.revised_plan_qty if req else mis.plan_qty
        current_plan_sales = current_plan * mis.sales_price
        out.append({
            "id": mis.id,
            "date": mis.mis_date,
            "product_id": p.id,
            "product": p.name,
            "plant": p.plant,
            "product_group": p.product_group,
            "finish_weight_kg": float(p.finish_weight_kg) if p.finish_weight_kg is not None else None,
            "baseline_plan_qty": float(mis.plan_qty),
            "current_plan_qty": float(current_plan),
            "actual_qty": float(mis.actual_qty),
            "gap_qty": float(mis.actual_qty - current_plan),
            "sales_price": float(mis.sales_price),
            "baseline_plan_sales": float(mis.plan_sales),
            "current_plan_sales": float(current_plan_sales),
            "actual_sales": float(mis.actual_sales),
            "gap_sales": float(mis.actual_sales - current_plan_sales),
            "achievement": float(mis.actual_qty / current_plan) if current_plan else None,
            "plan_tonnage_mt": float(current_plan * (p.finish_weight_kg or 0) / Decimal("1000")),
            "actual_tonnage_mt": float(mis.actual_qty * (p.finish_weight_kg or 0) / Decimal("1000")),
            "remark": mis.remark,
            "source": mis.source.value,
        })
    return out


@router.put("/{mis_id}")
def edit_mis(mis_id: int, payload: MISEdit, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = db.get(DailyMIS, mis_id)
    if not row:
        raise HTTPException(404, "MIS record not found")
    db.info["reason"] = payload.reason.strip()
    old = row.actual_qty
    new = Decimal(str(payload.actual_qty))
    if new != old:
        db.add(MISChangeLog(
            mis_id=row.id,
            field_name="actual_qty",
            old_value=str(old),
            new_value=str(new),
            reason=payload.reason,
            changed_by_id=user.id,
        ))
        row.actual_qty = new
        row.actual_sales = new * row.sales_price
    if payload.remark is not None:
        if payload.remark != row.remark:
            db.add(MISChangeLog(
                mis_id=row.id,
                field_name="remark",
                old_value=row.remark,
                new_value=payload.remark,
                reason=payload.reason,
                changed_by_id=user.id,
            ))
        row.remark = payload.remark
    db.commit(); db.refresh(row)
    return {"id": row.id, "actual_qty": float(row.actual_qty), "actual_sales": float(row.actual_sales)}


@router.get("/{mis_id}/history")
def history(mis_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rows = db.scalars(select(MISChangeLog).where(MISChangeLog.mis_id == mis_id).order_by(MISChangeLog.changed_at.desc())).all()
    return [{
        "id": x.id, "field": x.field_name, "old": x.old_value, "new": x.new_value,
        "reason": x.reason, "changed_at": x.changed_at, "changed_by_id": x.changed_by_id,
    } for x in rows]
