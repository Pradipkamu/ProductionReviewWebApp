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
def monitor(product_id:int,monitor_date:date,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    product=db.get(Product,product_id)
    if not product:raise HTTPException(404,'Product not found')
    flow=active_flow(db,product_id,monitor_date)
    if not flow:return {'flow':None,'stages':[]}
    stages=db.scalars(select(ProcessFlowStage).where(ProcessFlowStage.flow_id==flow.id).order_by(ProcessFlowStage.sequence_no)).all()
    values={s.route_operation_id:s for s in db.scalars(select(ProcessDailySummary).where(ProcessDailySummary.product_id==product_id,ProcessDailySummary.summary_date==monitor_date))}
    requirements={s.route_operation_id:s for s in db.scalars(select(DailyRequirement).where(DailyRequirement.product_id==product_id,DailyRequirement.req_date==monitor_date))}
    result=[]
    for stage in stages:
        actual=values.get(stage.route_operation_id);req=requirements.get(stage.route_operation_id)
        allocation=db.scalar(select(StageScheduleAllocation).where(StageScheduleAllocation.stage_id==stage.id,StageScheduleAllocation.month==monitor_date.replace(day=1),StageScheduleAllocation.effective_from<=monitor_date).order_by(StageScheduleAllocation.effective_from.desc(),StageScheduleAllocation.revision_no.desc()).limit(1))
        result.append(dict(id=stage.id,code=stage.code,name=stage.name,role=stage.role,branch=stage.branch,variant=stage.variant,vendor=stage.vendor_name,source_column=stage.source_column,active=stage.is_active,parent_dispatch=stage.parent_dispatch,alias_of=stage.alias_of,predecessors=json.loads(stage.predecessors_json),route_operation_id=stage.route_operation_id,
          plan=float(req.revised_plan_qty) if req else None,actual=float(actual.actual_qty) if actual else None,reject=float(actual.reject_qty) if actual else None,
          allocated_qty=float(allocation.allocated_qty) if allocation else None,allocation_reference=allocation.reference if allocation else None))
    return {'flow':dict(id=flow.id,revision=flow.revision_no,effective_from=flow.effective_from,company=flow.company),'stages':result}
