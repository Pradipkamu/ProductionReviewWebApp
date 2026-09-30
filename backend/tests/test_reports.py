from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import Action, ActionContext, Customer, DailyMIS, DailyRequirement, Product


def auth_headers(client: TestClient):
    r = client.post('/api/auth/login', json={'username':'admin','password':'ChangeMe123!'})
    assert r.status_code == 200
    return {'Authorization': f"Bearer {r.json()['access_token']}"}


def test_compliance_reports_use_revised_plan():
    with SessionLocal() as db:
        c=Customer(code='C1',name='Customer 1'); db.add(c); db.flush()
        p=Product(code='P1',name='Part 1',customer_id=c.id); db.add(p); db.flush()
        db.add_all([
            DailyMIS(mis_date=date(2026,9,1),product_id=p.id,plan_qty=Decimal('100'),actual_qty=Decimal('90'),sales_price=Decimal('10'),plan_sales=Decimal('1000'),actual_sales=Decimal('900')),
            DailyMIS(mis_date=date(2026,9,2),product_id=p.id,plan_qty=Decimal('100'),actual_qty=Decimal('120'),sales_price=Decimal('10'),plan_sales=Decimal('1000'),actual_sales=Decimal('1200')),
        ])
        # Revised requirement from the schedule engine must drive report plan.
        db.add(DailyRequirement(req_date=date(2026,9,2),product_id=p.id,route_operation_id=None,baseline_plan_qty=Decimal('100'),revised_plan_qty=Decimal('150')))
        db.commit(); pid=p.id
    client=TestClient(app); h=auth_headers(client)
    r=client.get(f'/api/reports/compliance?as_of=2026-09-02&product_id={pid}&metric=qty',headers=h)
    assert r.status_code == 200, r.text
    j=r.json()
    assert len(j['daily']) == 2
    assert j['summary']['plan'] == 250.0
    assert j['summary']['actual'] == 210.0
    assert round(j['summary']['compliance'],3) == .84
    rs=client.get(f'/api/reports/compliance?as_of=2026-09-02&product_id={pid}&metric=sales',headers=h)
    assert rs.status_code == 200
    assert rs.json()['summary']['plan'] == 2500.0


def test_compliance_filters_and_tonnage():
    with SessionLocal() as db:
        c=Customer(code='C2',name='Customer 2'); db.add(c); db.flush()
        p1=Product(code='P2A',name='Part A',customer_id=c.id,plant='Plant A',product_group='Aluminium',finish_weight_kg=Decimal('2.0')); db.add(p1)
        p2=Product(code='P2B',name='Part B',customer_id=c.id,plant='Plant B',product_group='Cast Iron',finish_weight_kg=Decimal('5.0')); db.add(p2); db.flush()
        db.add_all([
            DailyMIS(mis_date=date(2026,9,1),product_id=p1.id,plan_qty=Decimal('100'),actual_qty=Decimal('90'),sales_price=Decimal('10'),plan_sales=Decimal('1000'),actual_sales=Decimal('900')),
            DailyMIS(mis_date=date(2026,9,1),product_id=p2.id,plan_qty=Decimal('100'),actual_qty=Decimal('100'),sales_price=Decimal('10'),plan_sales=Decimal('1000'),actual_sales=Decimal('1000')),
        ])
        db.commit()
    client=TestClient(app); h=auth_headers(client)
    r=client.get('/api/reports/compliance?as_of=2026-09-01&plant=Plant%20A&metric=tonnage',headers=h)
    assert r.status_code == 200, r.text
    j=r.json()
    assert j['summary']['plan'] == 0.2
    assert j['summary']['actual'] == 0.18
    assert len(j['parts']) == 1
    assert j['parts'][0]['plant'] == 'Plant A'
    assert j['parts'][0]['product_group'] == 'Aluminium'


def test_compliance_weekly_window_is_last_8_weeks():
    with SessionLocal() as db:
        c = Customer(code='C8W', name='Customer 8W'); db.add(c); db.flush()
        p = Product(code='P8W', name='Part 8W', customer_id=c.id); db.add(p); db.flush()
        # Twelve Monday records ending in the selected current week.
        start = date(2026, 7, 13)
        for i in range(12):
            d = start + __import__('datetime').timedelta(weeks=i)
            db.add(DailyMIS(
                mis_date=d, product_id=p.id,
                plan_qty=Decimal('100'), actual_qty=Decimal(str(80+i)),
                sales_price=Decimal('10'), plan_sales=Decimal('1000'), actual_sales=Decimal(str((80+i)*10)),
            ))
        db.commit(); pid = p.id
    client = TestClient(app); h = auth_headers(client)
    r = client.get(f'/api/reports/compliance?as_of=2026-09-28&product_id={pid}&metric=qty', headers=h)
    assert r.status_code == 200, r.text
    weekly = r.json()['weekly']
    assert len(weekly) == 8
    assert weekly[0]['start'] == '2026-08-10'
    assert weekly[-1]['start'] == '2026-09-28'
    assert all(x['label'].startswith('W') and '•' not in x['label'] for x in weekly)


def test_compliance_accepts_multi_select_filters():
    with SessionLocal() as db:
        c=Customer(code='CMS',name='Multi Customer'); db.add(c); db.flush()
        p1=Product(code='MS1',name='Multi A',customer_id=c.id,plant='Plant A',product_group='AL'); db.add(p1)
        p2=Product(code='MS2',name='Multi B',customer_id=c.id,plant='Plant B',product_group='CI'); db.add(p2)
        p3=Product(code='MS3',name='Multi C',customer_id=c.id,plant='Plant C',product_group='CI'); db.add(p3); db.flush()
        for p,actual in [(p1,90),(p2,80),(p3,70)]:
            db.add(DailyMIS(mis_date=date(2026,9,1),product_id=p.id,plan_qty=Decimal('100'),actual_qty=Decimal(str(actual)),sales_price=Decimal('10'),plan_sales=Decimal('1000'),actual_sales=Decimal(str(actual*10))))
        db.commit(); pids=f'{p1.id},{p2.id}'
    client=TestClient(app); h=auth_headers(client)
    r=client.get(f'/api/reports/compliance?as_of=2026-09-01&product_id={pids}&plant=Plant%20A,Plant%20B&metric=qty',headers=h)
    assert r.status_code == 200, r.text
    j=r.json()
    assert j['summary']['plan'] == 200.0
    assert j['summary']['actual'] == 170.0
    assert {x['product'] for x in j['parts']} == {'Multi A','Multi B'}


def test_compliance_daily_action_counts_are_scoped_and_distinct():
    with SessionLocal() as db:
        c=Customer(code='CACT',name='Action Customer'); db.add(c); db.flush()
        p1=Product(code='ACT1',name='Action Part 1',customer_id=c.id,plant='P1'); db.add(p1)
        p2=Product(code='ACT2',name='Action Part 2',customer_id=c.id,plant='P2'); db.add(p2); db.flush()
        for p in (p1,p2):
            db.add(DailyMIS(mis_date=date(2026,9,3),product_id=p.id,plan_qty=Decimal('100'),actual_qty=Decimal('90'),sales_price=Decimal('10'),plan_sales=Decimal('1000'),actual_sales=Decimal('900')))
        a1=Action(action_no='ACT-2026-T001',reference_date=date(2026,9,3),problem_description='Gap 1',action_description='Follow up 1')
        a2=Action(action_no='ACT-2026-T002',reference_date=date(2026,9,3),problem_description='Gap 2',action_description='Follow up 2')
        a3=Action(action_no='ACT-2026-T003',reference_date=date(2026,9,3),problem_description='Other product',action_description='Follow up 3')
        db.add_all([a1,a2,a3]); db.flush()
        # Two contexts for a1 must still count as one distinct action.
        db.add_all([
            ActionContext(action_id=a1.id,context_date=date(2026,9,3),product_id=p1.id),
            ActionContext(action_id=a1.id,context_date=date(2026,9,3),product_id=p1.id),
            ActionContext(action_id=a2.id,context_date=date(2026,9,3),product_id=p1.id),
            ActionContext(action_id=a3.id,context_date=date(2026,9,3),product_id=p2.id),
        ])
        db.commit(); pid=p1.id
    client=TestClient(app); h=auth_headers(client)
    r=client.get(f'/api/reports/compliance?as_of=2026-09-03&product_id={pid}&metric=qty',headers=h)
    assert r.status_code == 200, r.text
    j=r.json()
    assert j['summary']['actions_raised'] == 2
    assert len(j['daily']) == 1
    assert j['daily'][0]['action_count'] == 2
