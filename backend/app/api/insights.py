from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, and_
from sqlalchemy.orm import Session
from ..auth import get_current_user
from ..db import get_db
from ..models import (User, Product, RouteVersion, RouteOperation, StandardCycleTime, OperationMachineMap,
 SalesPriceHistory, DailyMIS, DailyRequirement, QualityRejectionDaily, QualityRejectionMonthlyHistory,
 ImportBatch, QualityRejectionImportBatch, MachineShiftProduction, MachineLossEvent, Action, ActionContext,
 ActionWhyWhy, ActionReminder, VendorMovement, QualityPhenomenon, Customer)
from ..services.oee import calculate_oee
from ..services.escalation import refresh_reminders
from ..services.filtering import csv_ints, csv_strings
from ..enums import ActionStatus
router=APIRouter(prefix='/insights',tags=['insights'])

def scope(db, product_id=None, plant=None, customer_id=None, product_group=None):
    q=select(Product).where(Product.is_active.is_(True))
    for col, values in [(Product.id,csv_ints(product_id)),(Product.plant,csv_strings(plant)),(Product.customer_id,csv_ints(customer_id)),(Product.product_group,csv_strings(product_group))]:
        if values:q=q.where(col.in_(values))
    return db.scalars(q).all()

def data_quality(db, as_of, products):
    issues=[]; ids={p.id for p in products}
    def add(kind,p,detail,entity=None):
        issues.append(dict(kind=kind,product_id=p.id if p else None,product=p.name if p else '',detail=detail,entity_id=entity))
    for p in products:
        for kind,value in [('customer_missing',p.customer_id),('plant_missing',p.plant),('type_missing',p.product_group),('weight_missing',p.finish_weight_kg)]:
            if not value or (kind=='weight_missing' and value<=0):add(kind,p,'Complete product master')
        routes=db.scalars(select(RouteVersion).where(RouteVersion.product_id==p.id,RouteVersion.is_active.is_(True),RouteVersion.effective_from<=as_of,
            (RouteVersion.effective_to.is_(None))|(RouteVersion.effective_to>=as_of))).all()
        if not routes:add('route_missing',p,'No active route on selected date')
        if len(routes)>1:add('conflict',p,'Overlapping active routes')
        for route in routes:
            ops=db.scalars(select(RouteOperation).where(RouteOperation.route_version_id==route.id,RouteOperation.is_enabled.is_(True))).all()
            if not ops:add('route_missing',p,'Route has no enabled operations',route.id)
            for operation in ops:
                maps=db.scalars(select(OperationMachineMap).where(OperationMachineMap.route_operation_id==operation.id)).all()
                if not maps and operation.operation.operation_type.value=='INTERNAL':add('machine_mapping_missing',p,f'Operation {operation.operation.name}',operation.id)
                cycles=db.scalars(select(StandardCycleTime).where(StandardCycleTime.route_operation_id==operation.id,StandardCycleTime.effective_from<=as_of,
                    (StandardCycleTime.effective_to.is_(None))|(StandardCycleTime.effective_to>=as_of),StandardCycleTime.ideal_cycle_time_sec>0)).all()
                if not cycles and operation.operation.operation_type.value=='INTERNAL':add('cycle_time_missing',p,f'Operation {operation.operation.name}',operation.id)
        prices=db.scalars(select(SalesPriceHistory).where(SalesPriceHistory.product_id==p.id,SalesPriceHistory.effective_from<=as_of,
            (SalesPriceHistory.effective_to.is_(None))|(SalesPriceHistory.effective_to>=as_of))).all()
        if not prices or not any(x.price>0 for x in prices):add('price_missing',p,'No positive effective price')
        if len(prices)>1:add('conflict',p,'Overlapping effective price ranges')
    byid={p.id:p for p in products}
    for r in db.scalars(select(QualityRejectionDaily).where(QualityRejectionDaily.product_id.in_(ids),QualityRejectionDaily.rejection_date<=as_of)):
        if r.denominator_qty is None or r.denominator_qty<=0:add('ppm_denominator_pending',byid[r.product_id],str(r.rejection_date),r.id)
    for r in db.scalars(select(QualityRejectionMonthlyHistory).where(QualityRejectionMonthlyHistory.product_id.in_(ids),QualityRejectionMonthlyHistory.month<=as_of)):
        dispatch=db.scalars(select(DailyMIS.actual_qty).where(DailyMIS.product_id==r.product_id,DailyMIS.mis_date>=r.month,DailyMIS.mis_date<(r.month.replace(day=28)+timedelta(days=4)).replace(day=1))).all()
        if not dispatch or sum(dispatch)<=0:add('ppm_denominator_pending',byid[r.product_id],f'Historical MIS dispatch missing for {r.month}',r.id)
        if r.data_quality_note:add('conflict',byid[r.product_id],r.data_quality_note,r.id)
    for model in [ImportBatch,QualityRejectionImportBatch]:
        for batch in db.scalars(select(model)):
            if batch.status!='COMPLETED':add('unresolved_import',None,f'{batch.file_name}: {batch.status}',batch.id)
    # SQL NULL business keys allow duplicates despite composite UNIQUE constraints.
    seen=Counter((r.req_date,r.product_id,r.route_operation_id) for r in db.scalars(select(DailyRequirement).where(DailyRequirement.product_id.in_(ids),DailyRequirement.req_date<=as_of)))
    for key,count in seen.items():
        if count>1:add('duplicate',byid[key[1]],f'{count} requirements share {key[0]} / operation {key[2]}')
    return {'counts':dict(Counter(r['kind'] for r in issues)),'issues':issues,'total':len(issues)}

@router.get('/data-quality')
def quality(as_of:date,product_id:str|None=None,plant:str|None=None,customer_id:str|None=None,product_group:str|None=None,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    return data_quality(db,as_of,scope(db,product_id,plant,customer_id,product_group))

@router.get('/drilldown/{kind}')
def drilldown(kind:str,from_date:date,to_date:date,product_id:str|None=None,plant:str|None=None,customer_id:str|None=None,product_group:str|None=None,machine_id:str|None=None,phenomenon_id:str|None=None,operation_id:str|None=None,shift:str|None=None,
              db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    if to_date<from_date:raise HTTPException(422,'End date precedes start date')
    ids=[p.id for p in scope(db,product_id,plant,customer_id,product_group)]
    if kind=='compliance':
        mis=db.scalars(select(DailyMIS).where(DailyMIS.mis_date.between(from_date,to_date),DailyMIS.product_id.in_(ids))).all()
        contexts=db.scalars(select(ActionContext).where(ActionContext.context_date.between(from_date,to_date),ActionContext.product_id.in_(ids))).all()
        requirements=db.scalars(select(DailyRequirement).where(DailyRequirement.req_date.between(from_date,to_date),DailyRequirement.product_id.in_(ids))).all()
        return {'mis':mis,'requirements':requirements,'actions':[db.get(Action,c.action_id) for c in contexts]}
    if kind=='ppm':
        from .quality import _daily_rows, _historical_rows, _serialize_daily, _serialize_history
        daily=_daily_rows(db,from_date=from_date,to_date=to_date,plant=plant,product_id=product_id,phenomenon_id=phenomenon_id,operation_id=operation_id,machine_id=machine_id,shift=shift,customer_id=customer_id,product_group=product_group)
        history=_historical_rows(db,from_date=from_date,to_date=to_date,plant=plant,product_id=product_id,phenomenon_id=phenomenon_id,customer_id=customer_id,product_group=product_group) if not any([operation_id,machine_id,shift]) else []
        # Same denominator resolver as existing quality reports.
        from .quality import _history_dispatch_resolution
        resolved = _history_dispatch_resolution(db,history)
        return {'daily':[_serialize_daily(db,r) for r in daily],'history':[_serialize_history(db,r,resolved) for r in history],'phenomena':db.scalars(select(QualityPhenomenon)).all()}
    if kind=='oee':
        q=select(MachineShiftProduction).where(MachineShiftProduction.production_date.between(from_date,to_date),MachineShiftProduction.product_id.in_(ids))
        lq=select(MachineLossEvent).where(MachineLossEvent.loss_date.between(from_date,to_date))
        lq=lq.where(MachineLossEvent.product_id.in_(ids) | MachineLossEvent.product_id.is_(None))
        mids=csv_ints(machine_id)
        if mids:q=q.where(MachineShiftProduction.machine_id.in_(mids));lq=lq.where(MachineLossEvent.machine_id.in_(mids))
        return {'production':[{**{c.key:getattr(r,c.key) for c in r.__table__.columns}, **calculate_oee(r.shift_duration_min,r.planned_break_min,r.downtime_min,r.total_count,r.good_count,r.ideal_cycle_time_sec)} for r in db.scalars(q)],'losses':db.scalars(lq).all()}
    raise HTTPException(404,'Unknown drill-down')

@router.get('/escalation')
def escalation(db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    refresh_reminders(db)
    today=date.today();actions=db.scalars(select(Action)).all();plans={p.action_id:p for p in db.scalars(select(ActionWhyWhy))}
    groups=defaultdict(list)
    for a in actions:groups[(a.problem_category or '', ' '.join(a.problem_description.lower().split()))].append(a)
    rows=[]
    for a in actions:
        peers=[x for x in groups[(a.problem_category or '', ' '.join(a.problem_description.lower().split()))] if x.id!=a.id]
        recurrence=any(x.closed_at and a.raised_at>x.closed_at for x in peers)
        age=max(0,(today-a.due_at.date()).days) if a.due_at and a.status!=ActionStatus.CLOSED else 0
        plan=plans.get(a.id)
        if age or peers or (plan and plan.effectiveness_check_date and plan.effectiveness_check_date<today and not plan.effectiveness_result):
            rows.append(dict(id=a.id,action_no=a.action_no,problem=a.problem_description,owner_id=a.owner_id,status=a.status.value,
                overdue_days=age,level='ADMIN' if age>=14 else 'MANAGEMENT' if age>=7 else 'OWNER',repeated_problem_count=len(peers),
                recurrence_after_closure=recurrence,effectiveness_due=plan.effectiveness_check_date if plan else None,effectiveness_result=plan.effectiveness_result if plan else None))
    reminders=db.scalars(select(ActionReminder).where(ActionReminder.reminder_date==today).order_by(ActionReminder.id.desc())).all()
    if user.role.value not in {'ADMIN','MANAGEMENT'}:
        owned={a.id for a in actions if a.owner_id==user.id}
        reminders=[r for r in reminders if r.action_id in owned or r.level==user.role.value]
    return {'actions':rows,'reminders':reminders,'repeat_rule':'Same normalized problem description and category; review before treating as confirmed recurrence.'}

@router.post('/reminders/{reminder_id}/acknowledge')
def acknowledge(reminder_id:int,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    reminder=db.get(ActionReminder,reminder_id)
    if not reminder:raise HTTPException(404,'Reminder not found')
    action=db.get(Action,reminder.action_id)
    if user.role.value not in {'ADMIN','MANAGEMENT'} and action.owner_id!=user.id:raise HTTPException(403,'Only owner or management can acknowledge')
    reminder.acknowledged_by_id=user.id;reminder.acknowledged_at=datetime.utcnow();db.commit()
    return {'status':'acknowledged'}

@router.get('/exceptions')
def exceptions(as_of:date,product_id:str|None=None,plant:str|None=None,customer_id:str|None=None,product_group:str|None=None,
 compliance_target:float=Query(.9,ge=0,le=1),ppm_target:float=Query(1000,ge=0),oee_target:float=Query(.85,ge=0,le=1),major_loss_min:float=Query(60,ge=0),db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    products=scope(db,product_id,plant,customer_id,product_group);ids=[p.id for p in products];names={p.id:p.name for p in products};rows=[]
    def add(kind,detail,pid=None,value=None,entity_id=None):rows.append(dict(kind=kind,detail=detail,product_id=pid,product=names.get(pid,''),value=value,entity_id=entity_id))
    for mis in db.scalars(select(DailyMIS).where(DailyMIS.mis_date==as_of,DailyMIS.product_id.in_(ids))):
        req=db.scalar(select(DailyRequirement).where(DailyRequirement.req_date==as_of,DailyRequirement.product_id==mis.product_id,DailyRequirement.route_operation_id.is_(None)))
        plan=req.revised_plan_qty if req else mis.plan_qty
        if plan>0 and mis.actual_qty/plan<compliance_target:add('low_compliance',f'{as_of}: {mis.actual_qty} / {plan}',mis.product_id,float(mis.actual_qty/plan),mis.id)
    daily_quality=defaultdict(list)
    from .quality import _aggregate_daily
    for r in db.scalars(select(QualityRejectionDaily).where(QualityRejectionDaily.rejection_date==as_of,QualityRejectionDaily.product_id.in_(ids))):
        daily_quality[r.product_id].append(r)
    for pid,rejections in daily_quality.items():
        aggregate=_aggregate_daily(rejections)
        if aggregate['ppm'] is not None and aggregate['ppm']>ppm_target:
            add('high_ppm',f'{len(rejections)} rejection records / phenomena on {as_of}',pid,aggregate['ppm'])
    for r in db.scalars(select(MachineShiftProduction).where(MachineShiftProduction.production_date==as_of,MachineShiftProduction.product_id.in_(ids))):
        oee=calculate_oee(r.shift_duration_min,r.planned_break_min,r.downtime_min,r.total_count,r.good_count,r.ideal_cycle_time_sec)['oee_reported']
        if oee<oee_target:add('low_oee',f'Machine #{r.machine_id}, shift {r.shift}',r.product_id,oee,r.id)
    for r in db.scalars(select(MachineLossEvent).where(MachineLossEvent.loss_date==as_of,MachineLossEvent.duration_min>=major_loss_min)):
        if r.product_id in ids or r.product_id is None:add('major_loss',f'Machine #{r.machine_id}, loss #{r.loss_category_id}',r.product_id,float(r.duration_min),r.id)
    for r in db.scalars(select(VendorMovement).where(VendorMovement.product_id.in_(ids),VendorMovement.expected_return_date<as_of)):
        if r.outward_qty>r.receipt_qty:add('overdue_vendor_wip',f'Expected {r.expected_return_date}',r.product_id,float(r.outward_qty-r.receipt_qty),r.id)
    for a in db.scalars(select(Action).where(Action.status!=ActionStatus.CLOSED,Action.due_at<datetime.combine(as_of,datetime.min.time()))):
        contexts=db.scalars(select(ActionContext.product_id).where(ActionContext.action_id==a.id)).all()
        if set(contexts)&set(ids) or (not any([product_id,plant,customer_id,product_group]) and not contexts):add('overdue_action',a.action_no,None,(as_of-a.due_at.date()).days,a.id)
    for r in db.scalars(select(DailyRequirement).where(DailyRequirement.req_date.between(as_of,as_of+timedelta(days=7)),DailyRequirement.product_id.in_(ids),DailyRequirement.route_operation_id.is_(None))):
        routes=db.scalars(select(RouteVersion).where(RouteVersion.product_id==r.product_id,RouteVersion.is_active.is_(True))).all()
        if r.revised_plan_qty>0 and not routes:add('schedule_risk',f'Plan {r.revised_plan_qty} on {r.req_date} has no route',r.product_id,float(r.revised_plan_qty),r.id)
    dq=data_quality(db,as_of,products)
    for issue in dq['issues']:add('data_quality',issue['kind']+': '+issue['detail'],issue['product_id'],None,issue['entity_id'])
    return {'counts':dict(Counter(r['kind'] for r in rows)),'exceptions':rows,'thresholds':dict(compliance=compliance_target,ppm=ppm_target,oee=oee_target,major_loss_min=major_loss_min)}
