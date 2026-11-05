from ..time_utils import ist_today, ist_date, ist_day_start_utc
from collections import Counter, defaultdict
import json
from datetime import date, datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, and_, extract, func, or_
from sqlalchemy.orm import Session
from ..auth import get_current_user
from ..db import get_db
from ..models import (User, Product, RouteVersion, RouteOperation, StandardCycleTime, OperationMachineMap,
 SalesPriceHistory, DailyMIS, DailyRequirement, QualityRejectionDaily, QualityRejectionMonthlyHistory,
 ImportBatch, QualityRejectionImportBatch, MachineShiftProduction, MachineLossEvent, Action, ActionContext,
 ActionWhyWhy, ActionReminder, VendorMovement, QualityPhenomenon, Customer, LossCategory,
 ReviewPoint, ReviewSession, ReviewParticipantPresence, ReviewMeetingRequest, ReviewActionLink, GovernanceAudit,
 ProcessFlowVersion, ProcessFlowStage, StageScheduleAllocation, Operation,
 OperatorRequirementHistory, MachineCapacitySetting, Machine)
from ..services.oee import calculate_oee
from ..services.escalation import refresh_reminders
from ..services.filtering import csv_ints, csv_strings
from ..enums import ActionStatus, OEEComponent
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
    from ..services.machine_cost import next_pm_date
    for machine in db.scalars(select(Machine).where(Machine.is_active.is_(True))):
        pm_due = next_pm_date(machine)
        if pm_due and pm_due < as_of:
            add('machine_pm_overdue', None, f'{machine.code} PM was due on {pm_due}', machine.id)
    routes_by_product=defaultdict(list)
    for route in db.scalars(select(RouteVersion).where(
        RouteVersion.product_id.in_(ids), RouteVersion.is_active.is_(True),
        RouteVersion.effective_from<=as_of,
        (RouteVersion.effective_to.is_(None)) | (RouteVersion.effective_to>=as_of))):
        routes_by_product[route.product_id].append(route)
    flows={}
    for flow in db.scalars(select(ProcessFlowVersion).where(
        ProcessFlowVersion.product_id.in_(ids), ProcessFlowVersion.effective_from<=as_of
    ).order_by(ProcessFlowVersion.effective_from.desc(), ProcessFlowVersion.revision_no.desc())):
        flows.setdefault(flow.product_id, flow)
    stages_by_flow=defaultdict(list)
    for stage in db.scalars(select(ProcessFlowStage).where(
        ProcessFlowStage.flow_id.in_([flow.id for flow in flows.values()]),
        ProcessFlowStage.is_active.is_(True))):
        stages_by_flow[stage.flow_id].append(stage)
    stage_ids={stage.id for stages in stages_by_flow.values() for stage in stages}
    scheduled_stages=set(db.scalars(select(StageScheduleAllocation.stage_id).where(
        StageScheduleAllocation.stage_id.in_(stage_ids),
        StageScheduleAllocation.month==as_of.replace(day=1),
        StageScheduleAllocation.effective_from<=as_of)).all())
    route_ids={route.id for routes in routes_by_product.values() for route in routes}
    ops_by_route=defaultdict(list)
    for route_op in db.scalars(select(RouteOperation).where(
        RouteOperation.route_version_id.in_(route_ids), RouteOperation.is_enabled.is_(True))):
        ops_by_route[route_op.route_version_id].append(route_op)
    op_ids={op.id for ops in ops_by_route.values() for op in ops}
    names={op.id:op for op in db.scalars(select(Operation).where(
        Operation.id.in_({r.operation_id for ops in ops_by_route.values() for r in ops})))}
    stage_by_operation={stage.route_operation_id:stage for stage in db.scalars(select(ProcessFlowStage).where(
        ProcessFlowStage.route_operation_id.in_(op_ids)))}
    active_maps=db.scalars(select(OperationMachineMap).where(
        OperationMachineMap.route_operation_id.in_(op_ids), OperationMachineMap.is_active.is_(True),
        OperationMachineMap.effective_from<=as_of,
        (OperationMachineMap.effective_to.is_(None)) | (OperationMachineMap.effective_to>=as_of))).all()
    mapped_ops={x.route_operation_id for x in active_maps}
    maps_by_op=defaultdict(list)
    for x in active_maps:maps_by_op[x.route_operation_id].append(x)
    timed_ops=set(db.scalars(select(StandardCycleTime.route_operation_id).where(
        StandardCycleTime.route_operation_id.in_(op_ids), StandardCycleTime.effective_from<=as_of,
        (StandardCycleTime.effective_to.is_(None)) | (StandardCycleTime.effective_to>=as_of),
        StandardCycleTime.ideal_cycle_time_sec>0)).all())
    operator_ops=set(db.scalars(select(OperatorRequirementHistory.route_operation_id).where(
        OperatorRequirementHistory.route_operation_id.in_(op_ids),
        OperatorRequirementHistory.effective_from<=as_of,
        (OperatorRequirementHistory.effective_to.is_(None)) | (OperatorRequirementHistory.effective_to>=as_of),
        OperatorRequirementHistory.operators_per_machine>0)).all())
    mapped_machine_ids={x.machine_id for x in active_maps}
    capacity_machines=set(db.scalars(select(MachineCapacitySetting.machine_id).where(
        MachineCapacitySetting.machine_id.in_(mapped_machine_ids),
        MachineCapacitySetting.effective_from<=as_of,
        (MachineCapacitySetting.effective_to.is_(None)) | (MachineCapacitySetting.effective_to>=as_of))).all()) if mapped_machine_ids else set()
    prices_by_product=defaultdict(list)
    for price in db.scalars(select(SalesPriceHistory).where(
        SalesPriceHistory.product_id.in_(ids), SalesPriceHistory.effective_from<=as_of,
        (SalesPriceHistory.effective_to.is_(None)) | (SalesPriceHistory.effective_to>=as_of))):
        prices_by_product[price.product_id].append(price)
    for p in products:
        for kind,value in [('customer_missing',p.customer_id),('plant_missing',p.plant),('type_missing',p.product_group),('weight_missing',p.finish_weight_kg)]:
            if not value or (kind=='weight_missing' and value<=0):add(kind,p,'Complete product master')
        routes=routes_by_product[p.id]
        flow=flows.get(p.id)
        if flow:
            routes=[r for r in routes if r.id==flow.route_version_id]
            if not flow.company:add('company_missing',p,'Complete company in the next process definition revision')
            for stage in stages_by_flow[flow.id]:
                if stage.role.startswith('VENDOR') and not stage.vendor_name:add('vendor_missing',p,stage.name,stage.id)
                if stage.id not in scheduled_stages:add('stage_schedule_missing',p,stage.name,stage.id)
        if not routes:add('route_missing',p,'No active route on selected date')
        if len(routes)>1:add('conflict',p,'Overlapping active routes')
        for route in routes:
            ops=ops_by_route[route.id]
            if not ops:add('route_missing',p,'Route has no enabled operations',route.id)
            for operation in ops:
                stage=stage_by_operation.get(operation.id) if flow else None
                op=names[operation.operation_id]
                requires_machine=stage.role=='PRODUCTION' if stage else op.operation_type.value=='INTERNAL'
                if operation.id not in mapped_ops and requires_machine:add('machine_mapping_missing',p,f'Operation {op.name}',operation.id)
                if operation.id not in timed_ops and requires_machine:add('cycle_time_missing',p,f'Operation {op.name}',operation.id)
                if operation.id not in operator_ops and requires_machine:add('operator_requirement_missing',p,f'Operation {op.name}',operation.id)
                for mapping in maps_by_op.get(operation.id,[]):
                    if mapping.machine_id not in capacity_machines and requires_machine:add('machine_capacity_setting_missing',p,f'Operation {op.name}, machine {mapping.machine_id}',mapping.id)
        prices=prices_by_product[p.id]
        if not prices or not any(x.price>0 for x in prices):add('price_missing',p,'No positive effective price')
        if len(prices)>1:add('conflict',p,'Overlapping effective price ranges')
    byid={p.id:p for p in products}
    for r in db.scalars(select(QualityRejectionDaily).where(QualityRejectionDaily.product_id.in_(ids),QualityRejectionDaily.rejection_date<=as_of)):
        net_reject = (r.reject_qty or 0) - (r.approved_salvage_qty or 0)
        if net_reject > 0 and (r.denominator_qty is None or r.denominator_qty<=0):
            add('ppm_denominator_pending',byid[r.product_id],str(r.rejection_date),r.id)
    history=db.scalars(select(QualityRejectionMonthlyHistory).where(
        QualityRejectionMonthlyHistory.product_id.in_(ids),QualityRejectionMonthlyHistory.month<=as_of)).all()
    dispatch_by_month={}
    if history:
        start=min(r.month for r in history)
        end=(max(r.month for r in history).replace(day=28)+timedelta(days=4)).replace(day=1)
        dispatch_by_month={
            (pid,int(year),int(month)):quantity for pid,year,month,quantity in db.execute(
                select(DailyMIS.product_id,extract('year',DailyMIS.mis_date),extract('month',DailyMIS.mis_date),func.sum(DailyMIS.actual_qty))
                .where(DailyMIS.product_id.in_(ids),DailyMIS.mis_date>=start,DailyMIS.mis_date<end)
                .group_by(DailyMIS.product_id,extract('year',DailyMIS.mis_date),extract('month',DailyMIS.mis_date)))
        }
    for r in history:
        if dispatch_by_month.get((r.product_id,r.month.year,r.month.month),0)<=0:
            add('ppm_denominator_pending',byid[r.product_id],f'Historical MIS dispatch missing for {r.month}',r.id)
        if r.data_quality_note:add('conflict',byid[r.product_id],r.data_quality_note,r.id)
    for model in [ImportBatch,QualityRejectionImportBatch]:
        for batch in db.scalars(select(model)):
            if batch.status!='COMPLETED':add('unresolved_import',None,f'{batch.file_name}: {batch.status}',batch.id)
    # SQL NULL business keys allow duplicates despite composite UNIQUE constraints.
    seen=Counter((r.req_date,r.product_id,r.route_operation_id) for r in db.scalars(select(DailyRequirement).where(DailyRequirement.product_id.in_(ids),DailyRequirement.req_date<=as_of)))
    for key,count in seen.items():
        if count>1:add('duplicate',byid[key[1]],f'{count} requirements share {key[0]} / operation {key[2]}')
    # Daily OEE readiness: expose bad starters before they distort management trends.
    oee_rows=db.scalars(select(MachineShiftProduction).where(MachineShiftProduction.product_id.in_(ids),MachineShiftProduction.production_date==as_of)).all()
    availability_loss=defaultdict(float)
    for loss,category in db.execute(select(MachineLossEvent,LossCategory).join(LossCategory,LossCategory.id==MachineLossEvent.loss_category_id).where(
        MachineLossEvent.loss_date==as_of,MachineLossEvent.product_id.in_(ids),LossCategory.oee_component==OEEComponent.AVAILABILITY)):
        availability_loss[(loss.machine_id,loss.shift,loss.product_id,loss.route_operation_id)]+=float(loss.duration_min or 0)
    oee_seen=Counter((r.production_date,r.shift,r.product_id,r.route_operation_id,r.machine_id) for r in oee_rows)
    for key,count in oee_seen.items():
        if count>1:add('oee_duplicate_shift',byid[key[2]],f'{count} OEE entries share shift {key[1]} / machine {key[4]} / operation {key[3]}')
    for r in oee_rows:
        if not r.ideal_cycle_time_sec or r.ideal_cycle_time_sec<=0:add('oee_cycle_missing',byid[r.product_id],f'Shift {r.shift}, machine {r.machine_id}',r.id)
        unexplained=float(r.total_count or 0)-float(r.good_count or 0)-float(r.reject_count or 0)
        if unexplained>0:add('oee_output_unclassified',byid[r.product_id],f'{unexplained:g} output not classified on shift {r.shift}, machine {r.machine_id}',r.id)
        captured=availability_loss[(r.machine_id,r.shift,r.product_id,r.route_operation_id)]
        unclassified=float(r.downtime_min or 0)-captured
        if unclassified>0.01:add('oee_downtime_unclassified',byid[r.product_id],f'{unclassified:g} downtime minutes not classified on shift {r.shift}, machine {r.machine_id}',r.id)
        if unclassified<-0.01:add('oee_loss_overclassified',byid[r.product_id],f'{-unclassified:g} availability-loss minutes exceed downtime on shift {r.shift}, machine {r.machine_id}',r.id)
    return {'counts':dict(Counter(r['kind'] for r in issues)),'issues':issues,'total':len(issues)}

@router.get('/issue-timeline')
def issue_timeline(
    from_date: date,
    to_date: date,
    product_id: str | None = None,
    plant: str | None = None,
    customer_id: str | None = None,
    product_group: str | None = None,
    limit: int = Query(300, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Unified, permission-aware issue timeline across manufacturing records.

    This endpoint only composes existing source records. It does not change PPM,
    OEE, dispatch or action calculations. MOM points are included only for meetings
    the caller owns or has joined/been approved to view.
    """
    if to_date < from_date:
        raise HTTPException(422, "to_date must be on or after from_date")
    if (to_date - from_date).days > 92:
        raise HTTPException(422, "Issue timeline range cannot exceed 93 days")

    products = scope(db, product_id, plant, customer_id, product_group)
    ids = [p.id for p in products]
    if not ids:
        return {
            "from_date": from_date.isoformat(),
            "to_date": to_date.isoformat(),
            "summary": {"events": 0, "mom": 0, "actions": 0, "quality": 0, "losses": 0, "dispatch": 0},
            "events": [],
        }
    by_product = {p.id: p for p in products}
    events: list[dict] = []

    # MOM rows obey the same owner/participant/approved-request access rule
    # used by the meeting register. Never return another user's private MOM.
    visible_meetings = select(ReviewSession.id).where(or_(
        ReviewSession.owner_id == user.id,
        ReviewSession.id.in_(select(ReviewParticipantPresence.review_session_id).where(
            ReviewParticipantPresence.user_id == user.id
        )),
        ReviewSession.id.in_(select(ReviewMeetingRequest.review_session_id).where(
            ReviewMeetingRequest.requester_id == user.id,
            ReviewMeetingRequest.status.in_(["ACKNOWLEDGED", "LEFT"]),
        )),
    ))
    points = db.execute(
        select(ReviewPoint, ReviewSession, Product)
        .join(ReviewSession, ReviewSession.id == ReviewPoint.review_session_id)
        .join(Product, Product.id == ReviewPoint.product_id)
        .where(
            ReviewSession.id.in_(visible_meetings),
            ReviewSession.review_date.between(from_date, to_date),
            ReviewPoint.product_id.in_(ids),
        )
        .order_by(ReviewSession.review_date.desc(), ReviewPoint.sequence_no)
        .limit(limit)
    ).all()
    for point, meeting, product in points:
        events.append({
            "event_type": "MOM_POINT",
            "event_date": meeting.review_date.isoformat(),
            "product_id": product.id,
            "product_code": product.code,
            "product": product.name,
            "plant": product.plant,
            "title": point.category or "MOM discussion",
            "detail": point.discussion_point,
            "source": "Daily MOM",
            "source_id": point.id,
            "review_session_id": meeting.id,
            "action_id": point.action_id,
            "status": "ACTION_REQUIRED" if point.action_required else "DISCUSSION",
            "severity": "WATCH" if point.action_required else "INFO",
        })

    # Action register events are restricted to the selected product context.
    action_context_rows = db.execute(
        select(Action, ActionContext, Product)
        .join(ActionContext, ActionContext.action_id == Action.id)
        .join(Product, Product.id == ActionContext.product_id)
        .where(
            ActionContext.product_id.in_(ids),
            ActionContext.context_date.between(from_date, to_date),
        )
        .order_by(ActionContext.context_date.desc(), Action.id.desc())
        .limit(limit)
    ).all()
    seen_actions = set()
    for action, context, product in action_context_rows:
        if action.id in seen_actions:
            continue
        seen_actions.add(action.id)
        events.append({
            "event_type": "ACTION",
            "event_date": context.context_date.isoformat(),
            "product_id": product.id,
            "product_code": product.code,
            "product": product.name,
            "plant": product.plant,
            "title": action.action_no,
            "detail": action.problem_description,
            "action_description": action.action_description,
            "source": "Action Register",
            "source_id": action.id,
            "action_id": action.id,
            "status": action.status.value,
            "priority": action.priority.value,
            "owner_id": action.owner_id,
            "due_at": action.due_at.isoformat() if action.due_at else None,
            "severity": "OVERDUE" if action.due_at and action.status != ActionStatus.CLOSED and action.due_at < datetime.utcnow() else "WATCH",
        })

    quality_rows = db.execute(
        select(QualityRejectionDaily, Product, QualityPhenomenon)
        .join(Product, Product.id == QualityRejectionDaily.product_id)
        .join(QualityPhenomenon, QualityPhenomenon.id == QualityRejectionDaily.phenomenon_id)
        .where(
            QualityRejectionDaily.product_id.in_(ids),
            QualityRejectionDaily.rejection_date.between(from_date, to_date),
        )
        .order_by(QualityRejectionDaily.rejection_date.desc(), QualityRejectionDaily.id.desc())
        .limit(limit)
    ).all()
    for rejection, product, phenomenon in quality_rows:
        net_reject = max(0.0, float(rejection.reject_qty or 0) - float(rejection.approved_salvage_qty or 0))
        if net_reject <= 0:
            continue
        events.append({
            "event_type": "QUALITY_REJECTION",
            "event_date": rejection.rejection_date.isoformat(),
            "product_id": product.id,
            "product_code": product.code,
            "product": product.name,
            "plant": rejection.plant or product.plant,
            "title": phenomenon.name,
            "detail": rejection.remark or f"{net_reject:g} rejected pieces recorded",
            "source": "Quality Rejection",
            "source_id": rejection.id,
            "reject_qty": net_reject,
            "denominator_qty": float(rejection.denominator_qty) if rejection.denominator_qty is not None else None,
            "ppm": float(rejection.ppm) if rejection.ppm is not None else None,
            "ppm_state": "PENDING" if rejection.denominator_qty is None or rejection.denominator_qty <= 0 else "AVAILABLE",
            "route_operation_id": rejection.detection_route_operation_id,
            "machine_id": rejection.machine_id,
            "severity": "CRITICAL" if phenomenon.criticality == "CRITICAL" else "WATCH",
        })

    loss_rows = db.execute(
        select(MachineLossEvent, Product, Machine, LossCategory)
        .join(Product, Product.id == MachineLossEvent.product_id)
        .join(Machine, Machine.id == MachineLossEvent.machine_id)
        .join(LossCategory, LossCategory.id == MachineLossEvent.loss_category_id)
        .where(
            MachineLossEvent.product_id.in_(ids),
            MachineLossEvent.loss_date.between(from_date, to_date),
        )
        .order_by(MachineLossEvent.loss_date.desc(), MachineLossEvent.id.desc())
        .limit(limit)
    ).all()
    for loss, product, machine, category in loss_rows:
        events.append({
            "event_type": "PRODUCTION_LOSS",
            "event_date": loss.loss_date.isoformat(),
            "product_id": product.id,
            "product_code": product.code,
            "product": product.name,
            "plant": product.plant or machine.plant,
            "title": category.name,
            "detail": loss.remark or f"{float(loss.duration_min):g} minutes recorded",
            "source": "Machine Loss",
            "source_id": loss.id,
            "duration_min": float(loss.duration_min),
            "qty_loss": float(loss.qty_loss or 0),
            "route_operation_id": loss.route_operation_id,
            "machine_id": machine.id,
            "machine_code": machine.code,
            "shift": loss.shift,
            "severity": "WATCH" if float(loss.duration_min or 0) > 0 else "INFO",
        })

    # Dispatch signals: revised requirements are preferred per date; Daily MIS
    # is the fallback. Missing actual uploads are separate from saved zeroes.
    requirements = db.scalars(select(DailyRequirement).where(
        DailyRequirement.product_id.in_(ids),
        DailyRequirement.route_operation_id.is_(None),
        DailyRequirement.req_date.between(from_date, to_date),
    )).all()
    mis_rows = db.scalars(select(DailyMIS).where(
        DailyMIS.product_id.in_(ids),
        DailyMIS.mis_date.between(from_date, to_date),
    )).all()
    req_by_key = {(row.product_id, row.req_date): row for row in requirements}
    mis_by_key = {(row.product_id, row.mis_date): row for row in mis_rows}
    for pid, event_day in sorted(set(req_by_key) | set(mis_by_key), key=lambda k: (k[1], k[0]), reverse=True):
        requirement = req_by_key.get((pid, event_day))
        mis = mis_by_key.get((pid, event_day))
        plan_qty = (
            float(requirement.revised_plan_qty or 0) if requirement is not None
            else float(mis.plan_qty or 0) if mis is not None else None
        )
        actual_qty = float(mis.actual_qty or 0) if mis is not None else None
        if plan_qty is None:
            continue
        if actual_qty is not None and actual_qty >= plan_qty:
            continue
        product = by_product[pid]
        events.append({
            "event_type": "DISPATCH_GAP" if actual_qty is not None else "DISPATCH_ACTUAL_PENDING",
            "event_date": event_day.isoformat(),
            "product_id": product.id,
            "product_code": product.code,
            "product": product.name,
            "plant": product.plant,
            "title": "Dispatch below plan" if actual_qty is not None else "Dispatch actual pending",
            "detail": f"Plan {plan_qty:g}; actual {actual_qty:g}" if actual_qty is not None else f"Plan {plan_qty:g}; actual not uploaded",
            "source": "Revised Schedule" if requirement is not None else "Daily MIS",
            "source_id": requirement.id if requirement is not None else mis.id if mis is not None else None,
            "schedule_revision_id": requirement.schedule_revision_id if requirement is not None else mis.schedule_revision_id if mis is not None else None,
            "plan_qty": plan_qty,
            "actual_qty": actual_qty,
            "gap_qty": plan_qty - actual_qty if actual_qty is not None else None,
            "severity": "WATCH",
        })

    events.sort(key=lambda row: (row["event_date"], row["event_type"], row["source_id"] or 0), reverse=True)
    events = events[:limit]
    counts = Counter(row["event_type"] for row in events)
    return {
        "from_date": from_date.isoformat(),
        "to_date": to_date.isoformat(),
        "scope": {
            "products": len(products),
            "plants": sorted({p.plant for p in products if p.plant}),
        },
        "summary": {
            "events": len(events),
            "mom": counts.get("MOM_POINT", 0),
            "actions": counts.get("ACTION", 0),
            "quality": counts.get("QUALITY_REJECTION", 0),
            "losses": counts.get("PRODUCTION_LOSS", 0),
            "dispatch": counts.get("DISPATCH_GAP", 0) + counts.get("DISPATCH_ACTUAL_PENDING", 0),
        },
        "events": events,
    }


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
        from .quality import _by_id, _daily_context, _daily_rows, _historical_rows, _serialize_daily, _serialize_history
        daily=_daily_rows(db,from_date=from_date,to_date=to_date,plant=plant,product_id=product_id,phenomenon_id=phenomenon_id,operation_id=operation_id,machine_id=machine_id,shift=shift,customer_id=customer_id,product_group=product_group)
        history=_historical_rows(db,from_date=from_date,to_date=to_date,plant=plant,product_id=product_id,phenomenon_id=phenomenon_id,customer_id=customer_id,product_group=product_group) if not any([operation_id,machine_id,shift]) else []
        # Same denominator resolver as existing quality reports.
        from .quality import _history_dispatch_resolution
        resolved = _history_dispatch_resolution(db,history)
        products = _by_id(db, Product, {r.product_id for r in history})
        phenomena = _by_id(db, QualityPhenomenon, {r.phenomenon_id for r in history})
        context = _daily_context(db, daily)
        return {'daily':[_serialize_daily(r,context) for r in daily],
                'history':[_serialize_history(r,products,phenomena,resolved) for r in history],
                'phenomena':db.scalars(select(QualityPhenomenon)).all()}
    if kind=='oee':
        q=select(MachineShiftProduction).where(MachineShiftProduction.production_date.between(from_date,to_date),MachineShiftProduction.product_id.in_(ids))
        lq=select(MachineLossEvent).where(MachineLossEvent.loss_date.between(from_date,to_date))
        lq=lq.where(MachineLossEvent.product_id.in_(ids) | MachineLossEvent.product_id.is_(None))
        mids=csv_ints(machine_id)
        if mids:q=q.where(MachineShiftProduction.machine_id.in_(mids));lq=lq.where(MachineLossEvent.machine_id.in_(mids))
        return {'production':[{**{c.key:getattr(r,c.key) for c in r.__table__.columns}, **calculate_oee(r.shift_duration_min,r.planned_break_min,r.downtime_min,r.total_count,r.good_count,r.ideal_cycle_time_sec)} for r in db.scalars(q)],'losses':db.scalars(lq).all()}
    raise HTTPException(404,'Unknown drill-down')

@router.get('/escalation')
def escalation(
    product_id:str|None=None,
    plant:str|None=None,
    customer_id:str|None=None,
    product_group:str|None=None,
    db:Session=Depends(get_db),
    user:User=Depends(get_current_user),
):
    refresh_reminders(db)
    today=ist_today()
    product_ids=csv_ints(product_id)
    plants=csv_strings(plant)
    customer_ids=csv_ints(customer_id)
    groups=csv_strings(product_group)
    scoped=any([product_ids,plants,customer_ids,groups])
    if scoped:
        products=scope(db,product_id,plant,customer_id,product_group)
        ids=[p.id for p in products]
        linked_ids=set(db.scalars(select(ActionContext.action_id).where(
            ActionContext.product_id.in_(ids)
        ).distinct()).all()) if ids else set()
        actions=db.scalars(select(Action).where(Action.id.in_(linked_ids))).all() if linked_ids else []
    else:
        actions=db.scalars(select(Action)).all()
    action_ids={a.id for a in actions}
    plans={p.action_id:p for p in db.scalars(select(ActionWhyWhy).where(ActionWhyWhy.action_id.in_(action_ids or {-1})))}
    groups=defaultdict(list)
    for a in actions:groups[(a.problem_category or '', ' '.join(a.problem_description.lower().split()))].append(a)
    rows=[]
    for a in actions:
        peers=[x for x in groups[(a.problem_category or '', ' '.join(a.problem_description.lower().split()))] if x.id!=a.id]
        recurrence=any(x.closed_at and a.raised_at>x.closed_at for x in peers)
        age=max(0,(today-ist_date(a.due_at)).days) if a.due_at and a.status!=ActionStatus.CLOSED else 0
        plan=plans.get(a.id)
        if age or peers or (plan and plan.effectiveness_check_date and plan.effectiveness_check_date<today and not plan.effectiveness_result):
            rows.append(dict(id=a.id,action_no=a.action_no,problem=a.problem_description,owner_id=a.owner_id,status=a.status.value,
                overdue_days=age,level='ADMIN' if age>=14 else 'MANAGEMENT' if age>=7 else 'OWNER',repeated_problem_count=len(peers),
                recurrence_after_closure=recurrence,effectiveness_due=plan.effectiveness_check_date if plan else None,effectiveness_result=plan.effectiveness_result if plan else None))
    reminders=db.scalars(select(ActionReminder).where(ActionReminder.reminder_date==today).order_by(ActionReminder.id.desc())).all()
    if scoped:
        reminders=[r for r in reminders if r.action_id in action_ids]
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
    for a in db.scalars(select(Action).where(Action.status!=ActionStatus.CLOSED,Action.due_at<ist_day_start_utc(as_of))):
        contexts=db.scalars(select(ActionContext.product_id).where(ActionContext.action_id==a.id)).all()
        if set(contexts)&set(ids) or (not any([product_id,plant,customer_id,product_group]) and not contexts):add('overdue_action',a.action_no,None,(as_of-ist_date(a.due_at)).days,a.id)
    for r in db.scalars(select(DailyRequirement).where(DailyRequirement.req_date.between(as_of,as_of+timedelta(days=7)),DailyRequirement.product_id.in_(ids),DailyRequirement.route_operation_id.is_(None))):
        routes=db.scalars(select(RouteVersion).where(RouteVersion.product_id==r.product_id,RouteVersion.is_active.is_(True))).all()
        if r.revised_plan_qty>0 and not routes:add('schedule_risk',f'Plan {r.revised_plan_qty} on {r.req_date} has no route',r.product_id,float(r.revised_plan_qty),r.id)
    dq=data_quality(db,as_of,products)
    for issue in dq['issues']:add('data_quality',issue['kind']+': '+issue['detail'],issue['product_id'],None,issue['entity_id'])
    return {'counts':dict(Counter(r['kind'] for r in rows)),'exceptions':rows,'thresholds':dict(compliance=compliance_target,ppm=ppm_target,oee=oee_target,major_loss_min=major_loss_min)}


@router.post('/assistant-query')
def assistant_query(
    query: str,
    as_of: date,
    product_id: str | None = None,
    plant: str | None = None,
    customer_id: str | None = None,
    product_group: str | None = None,
    compliance_target: float = Query(.9, ge=0, le=1),
    ppm_target: float = Query(1000, ge=0),
    oee_target: float = Query(.85, ge=0, le=1),
    major_loss_min: float = Query(60, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return a deterministic, permission-aware management answer with source references.

    This endpoint is intentionally not generative. It composes existing exception,
    escalation and data-quality rules, records the query in GovernanceAudit, and
    returns source API paths plus calculation definitions.
    """
    normalized = " ".join((query or "").split())
    if len(normalized) < 2 or len(normalized) > 300:
        raise HTTPException(422, "Query must contain 2 to 300 characters")
    exception_data = exceptions(
        as_of=as_of,
        product_id=product_id,
        plant=plant,
        customer_id=customer_id,
        product_group=product_group,
        compliance_target=compliance_target,
        ppm_target=ppm_target,
        oee_target=oee_target,
        major_loss_min=major_loss_min,
        db=db,
        user=user,
    )
    escalation_data = escalation(
        product_id=product_id,
        plant=plant,
        customer_id=customer_id,
        product_group=product_group,
        db=db,
        user=user,
    )
    dq = data_quality(db, as_of, scope(db, product_id, plant, customer_id, product_group))
    q = normalized.casefold()
    sources = [
        {
            "title": "Operational exception register",
            "path": "/insights/exceptions",
            "as_of": as_of.isoformat(),
        },
        {
            "title": "Action escalation and reminders",
            "path": "/insights/escalation",
            "as_of": as_of.isoformat(),
        },
        {
            "title": "Data-quality findings",
            "path": "/insights/data-quality",
            "as_of": as_of.isoformat(),
        },
    ]

    if any(word in q for word in ("quality", "ppm", "rejection", "defect")):
        counts = dq.get("counts", {})
        answer = (
            f"Quality readiness for {as_of}: {dq['total']} data-quality findings are recorded. "
            f"PPM remains Pending wherever the dispatch denominator is missing. "
            f"Top quality findings: {dict(list(counts.items())[:6])}."
        )
        definition = "PPM uses the established plant-specific denominator rules; missing denominators are not replaced by company-wide MIS."
    elif any(word in q for word in ("overdue", "action", "follow", "escalat")):
        overdue = [row for row in escalation_data["actions"] if row["overdue_days"] > 0]
        answer = (
            f"{len(overdue)} overdue action records are visible for the selected scope as of {as_of}. "
            "Use the Action Register to review owners, due dates and Why-Why effectiveness."
        )
        definition = "Overdue means an open action has a due date earlier than the current India date; reminder records are deduplicated per action/day/kind."
    elif any(word in q for word in ("vendor", "wip", "supplier")):
        vendor_rows = [x for x in exception_data["exceptions"] if x["kind"] == "overdue_vendor_wip"]
        answer = (
            f"{len(vendor_rows)} vendor WIP exception records are present in the selected scope as of {as_of}. "
            "Use the Vendor Performance scorecard for pending quantity, aging and overdue exposure."
        )
        definition = "Vendor exposure is derived from outward quantity minus recorded receipts; late is based on expected return date versus the selected as-of date."
    else:
        counts = exception_data.get("counts", {})
        answer = (
            f"{len(exception_data.get('exceptions', []))} operational exceptions are returned for {as_of}, "
            f"including {counts.get('CRITICAL', 0)} critical, {counts.get('WARNING', 0)} warning and "
            f"{counts.get('BLOCKER', 0)} blocker records."
        )
        definition = "Exceptions use the existing configurable compliance, PPM, OEE, loss and data-quality rules; no new targets are invented by the assistant."

    audit = GovernanceAudit(
        actor_id=user.id,
        event="ASSISTANT_QUERY",
        entity="management_assistant",
        entity_id=None,
        month=as_of.replace(day=1),
        reason=normalized,
        before_json=None,
        after_json=json.dumps(
            {"answer": answer, "sources": sources, "definition": definition},
            default=str,
            sort_keys=True,
        ),
    )
    db.add(audit)
    db.commit()
    return {
        "query": normalized,
        "as_of": as_of.isoformat(),
        "answer": answer,
        "definition": definition,
        "sources": sources,
        "scope": {
            "plant": csv_strings(plant),
            "product_group": csv_strings(product_group),
            "customer_id": csv_ints(customer_id),
            "product_id": csv_ints(product_id),
        },
    }
