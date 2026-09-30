from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.enums import ActionStatus, OEEComponent, OperationType
from app.models import (
    Action, ActionContext, Customer, DailyMIS, DailyRequirement, LossCategory,
    Machine, MachineLossEvent, MachineShiftProduction, Operation, ProcessDailySummary,
    Product, RouteOperation, RouteVersion, ScheduleRevision, User, Vendor, VendorMovement,
)


def auth_headers(client: TestClient):
    r = client.post('/api/auth/login', json={'username':'admin','password':'ChangeMe123!'})
    assert r.status_code == 200
    return {'Authorization': f"Bearer {r.json()['access_token']}"}


def seed_core():
    with SessionLocal() as db:
        c=Customer(code='C_ADV',name='Customer ADV'); db.add(c); db.flush()
        p=Product(code='P_ADV',name='Advanced Part',customer_id=c.id,plant='Plant 1',product_group='Aluminium'); db.add(p); db.flush()
        op1=Operation(code='OP1',name='Machining',operation_type=OperationType.INTERNAL); op2=Operation(code='OP2',name='Dispatch',operation_type=OperationType.DISPATCH); db.add_all([op1,op2]); db.flush()
        rv=RouteVersion(product_id=p.id,revision_no=0,effective_from=date(2026,9,1)); db.add(rv); db.flush()
        ro1=RouteOperation(route_version_id=rv.id,operation_id=op1.id,sequence_no=10); ro2=RouteOperation(route_version_id=rv.id,operation_id=op2.id,sequence_no=20,is_dispatch=True); db.add_all([ro1,ro2]); db.flush()
        db.add_all([
            DailyRequirement(req_date=date(2026,9,28),product_id=p.id,route_operation_id=ro1.id,revised_plan_qty=Decimal('100'),baseline_plan_qty=Decimal('100')),
            DailyRequirement(req_date=date(2026,9,28),product_id=p.id,route_operation_id=ro2.id,revised_plan_qty=Decimal('90'),baseline_plan_qty=Decimal('90')),
            ProcessDailySummary(summary_date=date(2026,9,28),product_id=p.id,route_operation_id=ro1.id,plan_qty=Decimal('100'),actual_qty=Decimal('80'),good_qty=Decimal('78'),reject_qty=Decimal('2')),
            ProcessDailySummary(summary_date=date(2026,9,28),product_id=p.id,route_operation_id=ro2.id,plan_qty=Decimal('90'),actual_qty=Decimal('70'),good_qty=Decimal('70')),
            DailyMIS(mis_date=date(2026,9,28),product_id=p.id,plan_qty=Decimal('90'),actual_qty=Decimal('70'),sales_price=Decimal('10'),plan_sales=Decimal('900'),actual_sales=Decimal('700')),
            ScheduleRevision(product_id=p.id,month=date(2026,9,1),revision_no=0,effective_from=date(2026,9,1),monthly_target_qty=Decimal('2000')),
        ])
        v=Vendor(code='V1',name='Vendor 1'); db.add(v); db.flush()
        db.add(VendorMovement(product_id=p.id,route_operation_id=ro1.id,vendor_id=v.id,outward_date=date(2026,9,20),outward_qty=Decimal('100'),expected_return_date=date(2026,9,22),receipt_date=date(2026,9,23),receipt_qty=Decimal('80'),reject_qty=Decimal('2')))
        m=Machine(code='M1',name='Machine 1'); db.add(m); db.flush()
        db.add(MachineShiftProduction(production_date=date(2026,9,28),shift='A',product_id=p.id,route_operation_id=ro1.id,machine_id=m.id,shift_duration_min=Decimal('480'),planned_break_min=Decimal('30'),downtime_min=Decimal('50'),total_count=Decimal('600'),good_count=Decimal('580'),ideal_cycle_time_sec=Decimal('36')))
        lc=LossCategory(code='BREAK',name='Breakdown',oee_component=OEEComponent.AVAILABILITY); db.add(lc); db.flush()
        db.add(MachineLossEvent(loss_date=date(2026,9,28),shift='A',product_id=p.id,route_operation_id=ro1.id,machine_id=m.id,loss_category_id=lc.id,duration_min=Decimal('40')))
        owner=db.query(User).first()
        a=Action(action_no='ACT-ADV-1',reference_date=date(2026,9,25),problem_category='Breakdown',problem_description='Machine stopped',action_description='Repair',owner_id=owner.id,due_at=datetime(2026,9,27,12),status=ActionStatus.OPEN,gap_when_raised=Decimal('-20')); db.add(a); db.flush()
        db.add(ActionContext(action_id=a.id,context_date=date(2026,9,25),product_id=p.id,route_operation_id=ro1.id,machine_id=m.id))
        db.commit()
        return p.id, m.id, v.id


def test_advanced_reports_endpoints():
    pid, mid, vid = seed_core()
    client=TestClient(app); h=auth_headers(client)
    urls=[
        f'/api/reports/process-compliance?as_of=2026-09-29&product_id={pid}',
        f'/api/reports/process-funnel?report_date=2026-09-28&product_id={pid}',
        f'/api/reports/vendor-performance?as_of=2026-09-29&product_id={pid}',
        f'/api/reports/oee-trends?as_of=2026-09-29&product_id={pid}&machine_id={mid}',
        f'/api/reports/loss-pareto?as_of=2026-09-29&product_id={pid}&machine_id={mid}',
        f'/api/reports/action-performance?as_of=2026-09-29&product_id={pid}',
        f'/api/reports/schedule-impact?as_of=2026-09-29&product_id={pid}',
        f'/api/reports/month-end-forecast?as_of=2026-09-29&product_id={pid}',
    ]
    for url in urls:
        r=client.get(url,headers=h)
        assert r.status_code == 200, (url,r.text)
    j=client.get(f'/api/reports/process-funnel?report_date=2026-09-28&product_id={pid}',headers=h).json()
    assert len(j['operations']) == 2
    o=client.get(f'/api/reports/oee-trends?as_of=2026-09-29&machine_id={mid}',headers=h).json()
    assert o['summary']['oee'] > 0
    loss=client.get(f'/api/reports/loss-pareto?as_of=2026-09-29&machine_id={mid}',headers=h).json()
    assert loss['summary']['loss_minutes'] == 40.0
