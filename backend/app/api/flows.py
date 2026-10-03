import json
from datetime import date
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..auth import get_current_user
from ..db import get_db
from ..models import User, Product, ProcessFlowStage, ProcessDailySummary, DailyRequirement, StageScheduleAllocation
from ..services.process_flows import active_flow, approved_design
from ..services.planning import working_days, product_plant
router=APIRouter(prefix='/flows',tags=['process flows'])

@router.get('/approved-design')
def approved(user:User=Depends(get_current_user)):
    return approved_design()

@router.get('/template')
def template(user:User=Depends(get_current_user)):
    path=Path(__file__).resolve().parents[2]/'templates'/'Production_Process_Upload_v0.4.0.xlsx'
    if not path.is_file():raise HTTPException(404,'Process upload template is unavailable')
    return FileResponse(path,filename=path.name)

@router.get('/monitor')
def monitor(
    product_id:int,
    monitor_date:date|None=None,
    start_date:date|None=None,
    end_date:date|None=None,
    db:Session=Depends(get_db),
    user:User=Depends(get_current_user),
):
    product=db.get(Product,product_id)
    if not product:raise HTTPException(404,'Product not found')
    period_end=end_date or monitor_date
    if period_end is None:raise HTTPException(422,'monitor_date or end_date is required')
    period_start=start_date or period_end
    if period_start>period_end:raise HTTPException(422,'start_date must be on or before end_date')
    flow=active_flow(db,product_id,period_end)
    if not flow:return {'flow':None,'stages':[]}
    effective_start=max(period_start,flow.effective_from)
    work_dates=working_days(db,effective_start,period_end,product_plant(db,product_id))
    work_set=set(work_dates)
    stages=db.scalars(select(ProcessFlowStage).where(ProcessFlowStage.flow_id==flow.id).order_by(ProcessFlowStage.sequence_no)).all()
    route_ids=[s.route_operation_id for s in stages if s.route_operation_id]
    values_by_route={}
    reqs_by_route={}
    if route_ids and work_dates:
        for row in db.scalars(select(ProcessDailySummary).where(
            ProcessDailySummary.product_id==product_id,
            ProcessDailySummary.route_operation_id.in_(route_ids),
            ProcessDailySummary.summary_date>=effective_start,
            ProcessDailySummary.summary_date<=period_end,
        )):
            if row.summary_date in work_set:values_by_route.setdefault(row.route_operation_id,[]).append(row)
        for row in db.scalars(select(DailyRequirement).where(
            DailyRequirement.product_id==product_id,
            DailyRequirement.route_operation_id.in_(route_ids),
            DailyRequirement.req_date>=effective_start,
            DailyRequirement.req_date<=period_end,
        )):
            if row.req_date in work_set:reqs_by_route.setdefault(row.route_operation_id,[]).append(row)
    result=[]
    for stage in stages:
        actual_rows=values_by_route.get(stage.route_operation_id,[])
        req_rows=reqs_by_route.get(stage.route_operation_id,[])
        data_days=len({r.summary_date for r in actual_rows})
        plan_days=len({r.req_date for r in req_rows})
        plan=(sum((r.revised_plan_qty for r in req_rows),0)/plan_days) if plan_days else None
        actual=(sum((r.actual_qty for r in actual_rows),0)/data_days) if data_days else None
        reject=(sum((r.reject_qty for r in actual_rows),0)/data_days) if data_days else None
        allocation=db.scalar(select(StageScheduleAllocation).where(StageScheduleAllocation.stage_id==stage.id,StageScheduleAllocation.month==period_end.replace(day=1),StageScheduleAllocation.effective_from<=period_end).order_by(StageScheduleAllocation.effective_from.desc(),StageScheduleAllocation.revision_no.desc()).limit(1))
        result.append(dict(id=stage.id,code=stage.code,name=stage.name,role=stage.role,branch=stage.branch,variant=stage.variant,vendor=stage.vendor_name,source_column=stage.source_column,active=stage.is_active,parent_dispatch=stage.parent_dispatch,alias_of=stage.alias_of,predecessors=json.loads(stage.predecessors_json),route_operation_id=stage.route_operation_id,
          plan=float(plan) if plan is not None else None,actual=float(actual) if actual is not None else None,reject=float(reject) if reject is not None else None,
          days_with_plan=plan_days,days_with_data=data_days,
          allocated_qty=float(allocation.allocated_qty) if allocation else None,allocation_reference=allocation.reference if allocation else None))
    return {
        'flow':dict(id=flow.id,revision=flow.revision_no,effective_from=flow.effective_from,company=flow.company),
        'period':{
            'requested_start':period_start.isoformat(),'start':effective_start.isoformat(),'end':period_end.isoformat(),
            'working_days':len(work_dates),'off_days':(period_end-effective_start).days+1-len(work_dates),
            'is_range':period_start!=period_end,'truncated_to_flow':effective_start!=period_start,
        },
        'stages':result,
    }
