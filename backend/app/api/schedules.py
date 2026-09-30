from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..models import Product, ScheduleRevision, User
from ..schemas import SchedulePreviewRequest, ScheduleRevisionCreate
from ..services.planning import apply_schedule_revision, next_revision_no, preview_revision

router = APIRouter(prefix="/schedules", tags=["schedules"])


@router.get("")
def list_schedules(product_id: int, month: date, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    first = month.replace(day=1)
    rows = db.scalars(select(ScheduleRevision).where(
        ScheduleRevision.product_id == product_id,
        ScheduleRevision.month == first,
    ).order_by(ScheduleRevision.revision_no)).all()
    return [{
        "id": x.id, "revision_no": x.revision_no, "effective_from": x.effective_from,
        "target": float(x.monthly_target_qty), "reason": x.reason, "created_at": x.created_at,
    } for x in rows]


@router.post("/preview")
def preview(payload: SchedulePreviewRequest, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    if not db.get(Product, payload.product_id):
        raise HTTPException(404, "Product not found")
    return preview_revision(db, payload.product_id, payload.effective_from, payload.monthly_target_qty)


@router.post("")
def create_revision(payload: ScheduleRevisionCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    month = payload.month.replace(day=1)
    if payload.effective_from.replace(day=1) != month:
        raise HTTPException(400, "Effective date must be inside the selected month")
    rev = ScheduleRevision(
        product_id=payload.product_id,
        month=month,
        revision_no=next_revision_no(db, payload.product_id, month),
        effective_from=payload.effective_from,
        monthly_target_qty=payload.monthly_target_qty,
        reason=payload.reason,
        entered_by_id=user.id,
    )
    db.add(rev); db.flush()
    apply_schedule_revision(db, rev)
    db.commit(); db.refresh(rev)
    return {"id": rev.id, "revision_no": rev.revision_no}

@router.post("/recalculate-month")
def recalculate_month(month: date, from_date: date, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    first = month.replace(day=1)
    product_ids = db.scalars(select(ScheduleRevision.product_id).where(ScheduleRevision.month == first).distinct()).all()
    count = 0
    for product_id in product_ids:
        rev = db.scalar(select(ScheduleRevision).where(
            ScheduleRevision.product_id == product_id,
            ScheduleRevision.month == first,
            ScheduleRevision.effective_from <= from_date,
        ).order_by(ScheduleRevision.effective_from.desc(), ScheduleRevision.revision_no.desc()).limit(1))
        if rev:
            apply_schedule_revision(db, rev, preserve_before=from_date)
            count += 1
    db.commit()
    return {"products_recalculated": count, "from_date": from_date}
