from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..models import ProcessDailySummary, User, Product, ProcessFlowStage
from ..schemas import ProcessEntry
from ..services.dashboard import process_monitor

router = APIRouter(prefix="/process", tags=["process"])


@router.get("/monitor")
def monitor(product_id: int, monitor_date: date, from_date: date | None = None, to_date: date | None = None, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    if (from_date is None) != (to_date is None):
        raise HTTPException(422, 'Provide both From and To dates')
    start, end = (from_date, to_date) if from_date is not None else (monitor_date, monitor_date)
    if start > end:
        raise HTTPException(422, 'From date must be on or before To date')
    from ..services.planning import get_active_route
    route = get_active_route(db, product_id, end)
    if route and start < route.effective_from:
        raise HTTPException(422, f'Current route R{route.revision_no} starts {route.effective_from}; choose a range within this revision')
    return process_monitor(db, product_id, end, start)


@router.post("/entry")
def save_entry(payload: ProcessEntry, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    from ..services.process_flows import active_flow, stage_for, apply_actual, check_dispatch_totals
    flow=active_flow(db,payload.product_id,payload.summary_date)
    if flow:
        stage=db.scalar(select(ProcessFlowStage).where(ProcessFlowStage.route_operation_id==payload.route_operation_id))
        if not stage or stage.flow_id!=flow.id or not stage.is_active:
            raise HTTPException(422,'Operation does not belong to the active approved flow')
        stats={'new':0,'updated':0,'unchanged':0,'warnings':[]}
        try:
            apply_actual(db,{'product':db.get(Product,payload.product_id).name,'stage_code':stage.code,'date':payload.summary_date,'actual_qty':payload.actual_qty,'reject_qty':payload.reject_qty,'reason':payload.remarks,'source':payload.source},stats)
            check_dispatch_totals(db,{(payload.product_id,payload.summary_date)})
            db.commit()
        except ValueError as e:
            db.rollback();raise HTTPException(422,str(e)) from e
        return stats
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
