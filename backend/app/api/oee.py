from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..models import MachineLossEvent, MachineShiftProduction, User
from ..schemas import LossEventCreate, MachineEntryCreate
from ..services.oee import calculate_oee

router = APIRouter(prefix="/oee", tags=["oee"])


@router.post("/machine-entry")
def save_machine_entry(payload: MachineEntryCreate, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    row = MachineShiftProduction(**payload.model_dump())
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id, "oee": calculate_oee(
        row.shift_duration_min, row.planned_break_min, row.downtime_min,
        row.total_count, row.good_count, row.ideal_cycle_time_sec,
    )}


@router.post("/loss-events")
def save_loss(payload: LossEventCreate, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    row = MachineLossEvent(**payload.model_dump())
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id}


@router.get("/machine-summary")
def machine_summary(machine_id: int, summary_date: date, shift: str | None = None,
                    db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    q = select(MachineShiftProduction).where(
        MachineShiftProduction.machine_id == machine_id,
        MachineShiftProduction.production_date == summary_date,
    )
    if shift:
        q = q.where(MachineShiftProduction.shift == shift)
    rows = db.scalars(q).all()
    if not rows:
        return {"machine_id": machine_id, "date": summary_date, "entries": [], "summary": None}

    totals = {
        "shift_duration": sum(float(x.shift_duration_min) for x in rows),
        "planned_break": sum(float(x.planned_break_min) for x in rows),
        "downtime": sum(float(x.downtime_min) for x in rows),
        "total_count": sum(float(x.total_count) for x in rows),
        "good_count": sum(float(x.good_count) for x in rows),
        "ideal_weighted": 0.0,
    }
    denom = totals["total_count"] or 1
    totals["ideal_weighted"] = sum(float(x.ideal_cycle_time_sec) * float(x.total_count) for x in rows) / denom
    oee = calculate_oee(totals["shift_duration"], totals["planned_break"], totals["downtime"],
                        totals["total_count"], totals["good_count"], totals["ideal_weighted"])

    loss_q = select(MachineLossEvent).where(
        MachineLossEvent.machine_id == machine_id,
        MachineLossEvent.loss_date == summary_date,
    )
    if shift:
        loss_q = loss_q.where(MachineLossEvent.shift == shift)
    losses = db.scalars(loss_q).all()
    captured = sum(float(x.duration_min) for x in losses)
    oee["captured_loss_min"] = captured
    oee["unclassified_loss_min"] = max(0.0, totals["downtime"] - captured)
    return {
        "machine_id": machine_id,
        "date": summary_date,
        "shift": shift,
        "entries": [{"id": x.id, "shift": x.shift, "product_id": x.product_id,
                     "route_operation_id": x.route_operation_id, "total_count": float(x.total_count),
                     "good_count": float(x.good_count), "downtime_min": float(x.downtime_min)} for x in rows],
        "summary": oee,
        "losses": [{"id": x.id, "loss_category_id": x.loss_category_id, "duration_min": float(x.duration_min),
                    "remark": x.remark} for x in losses],
    }
