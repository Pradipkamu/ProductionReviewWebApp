import json
from datetime import date
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from ..auth import get_current_user
from ..db import get_db
from ..models import User, Product, ProcessFlowStage, ProcessDailySummary, DailyRequirement, StageScheduleAllocation
from ..services.process_flows import active_flow, approved_design
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
def monitor(product_id:int,monitor_date:date,from_date:date|None=None,to_date:date|None=None,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    if (from_date is None)!=(to_date is None):raise HTTPException(422,'Provide both From and To dates')
    start,end=(from_date,to_date) if from_date is not None else (monitor_date,monitor_date)
    if start>end:raise HTTPException(422,'From date must be on or before To date')
    product=db.get(Product,product_id)
    if not product:raise HTTPException(404,'Product not found')
    flow=active_flow(db,product_id,end)
    if not flow:return {'flow':None,'stages':[],'from_date':start,'to_date':end}
    if start<flow.effective_from:raise HTTPException(422,f'Current flow R{flow.revision_no} starts {flow.effective_from}; choose a range within this revision')
    stages=db.scalars(select(ProcessFlowStage).where(ProcessFlowStage.flow_id==flow.id).order_by(ProcessFlowStage.sequence_no)).all()
    route_ids=[s.route_operation_id for s in stages if s.route_operation_id is not None]
    values={rid:(qty,reject,days) for rid,qty,reject,days in db.execute(
        select(ProcessDailySummary.route_operation_id,func.sum(ProcessDailySummary.actual_qty),func.sum(ProcessDailySummary.reject_qty),func.count(ProcessDailySummary.id))
        .where(ProcessDailySummary.product_id==product_id,ProcessDailySummary.route_operation_id.in_(route_ids),ProcessDailySummary.summary_date>=start,ProcessDailySummary.summary_date<=end)
        .group_by(ProcessDailySummary.route_operation_id))}
    requirements={rid:(qty,days) for rid,qty,days in db.execute(
        select(DailyRequirement.route_operation_id,func.sum(DailyRequirement.revised_plan_qty),func.count(DailyRequirement.id))
        .where(DailyRequirement.product_id==product_id,DailyRequirement.route_operation_id.in_(route_ids),DailyRequirement.req_date>=start,DailyRequirement.req_date<=end)
        .group_by(DailyRequirement.route_operation_id))}
    period_days=(end-start).days+1
    result=[]
    for stage in stages:
        actual=values.get(stage.route_operation_id);req=requirements.get(stage.route_operation_id)
        allocation=db.scalar(select(StageScheduleAllocation).where(StageScheduleAllocation.stage_id==stage.id,StageScheduleAllocation.month==end.replace(day=1),StageScheduleAllocation.effective_from<=end).order_by(StageScheduleAllocation.effective_from.desc(),StageScheduleAllocation.revision_no.desc()).limit(1))
        result.append(dict(id=stage.id,code=stage.code,name=stage.name,role=stage.role,branch=stage.branch,variant=stage.variant,vendor=stage.vendor_name,source_column=stage.source_column,active=stage.is_active,parent_dispatch=stage.parent_dispatch,alias_of=stage.alias_of,predecessors=json.loads(stage.predecessors_json),route_operation_id=stage.route_operation_id,
          plan=float(req[0]) if req else None,actual=float(actual[0]) if actual else None,reject=float(actual[1]) if actual else None,
          plan_days=int(req[1]) if req else 0,actual_days=int(actual[2]) if actual else 0,
          allocated_qty=float(allocation.allocated_qty) if allocation else None,allocation_reference=allocation.reference if allocation else None))
    return {'flow':dict(id=flow.id,revision=flow.revision_no,effective_from=flow.effective_from,company=flow.company),'stages':result,
            'from_date':start,'to_date':end,'period_days':period_days}
