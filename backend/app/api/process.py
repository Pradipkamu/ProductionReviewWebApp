from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..models import ProcessDailySummary, User
from ..schemas import ProcessEntry
from ..services.dashboard import process_monitor

router = APIRouter(prefix="/process", tags=["process"])


@router.get("/monitor")
def monitor(product_id: int, monitor_date: date, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return process_monitor(db, product_id, monitor_date)


@router.post("/entry")
def save_entry(payload: ProcessEntry, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    row = db.scalar(select(ProcessDailySummary).where(
        ProcessDailySummary.summary_date == payload.summary_date,
        ProcessDailySummary.product_id == payload.product_id,
        ProcessDailySummary.route_operation_id == payload.route_operation_id,
    ))
    if not row:
        row = ProcessDailySummary(
            summary_date=payload.summary_date,
            product_id=payload.product_id,
            route_operation_id=payload.route_operation_id,
        )
        db.add(row)
    for field in ["plan_qty", "actual_qty", "good_qty", "reject_qty", "opening_wip", "closing_wip", "remarks", "source"]:
        setattr(row, field, getattr(payload, field))
    db.commit(); db.refresh(row)
    return {"id": row.id}
