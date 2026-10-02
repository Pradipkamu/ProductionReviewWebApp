from datetime import date, datetime, timedelta
from io import BytesIO
from openpyxl import Workbook
from fastapi.testclient import TestClient
from sqlalchemy import event, select, func
from app.main import app
from app.db import SessionLocal
from app.models import Product, DailyMIS, Vendor, Operation, RouteVersion, RouteOperation, VendorMovement, VendorReceipt, Action, ActionWhyWhy, ActionReminder
from app.enums import ActionStatus
from test_governance_security import headers
from app.api.insights import data_quality


def workbook():
    wb=Workbook();ws=wb.active;ws.title='Historical_Daily_MIS_Import'
    ws.append(['Date','Product','Plan_Qty','Actual_Qty']);ws.append([date(2026,8,1),'Part 1',100,90])
    bio=BytesIO();wb.save(bio);return bio.getvalue()


def test_preview_is_read_only_and_confirmation_is_atomic():
    with SessionLocal() as db:db.add(Product(code='P1',name='Part 1'));db.commit()
    c=TestClient(app);h=headers(c)
    r=c.post('/api/import/preview/historical-daily-mis',headers=h,files={'file':('history.xlsx',workbook())})
    assert r.status_code==200,r.text
    assert r.json()['counts']['new']==1,r.text
    with SessionLocal() as db:assert db.scalar(select(func.count()).select_from(DailyMIS))==0
    confirmed=c.post('/api/import/confirm',headers=h,json={'preview_token':r.json()['preview_token']})
    assert confirmed.status_code==200,confirmed.text
    with SessionLocal() as db:assert db.scalar(select(func.count()).select_from(DailyMIS))==1
    assert c.post('/api/import/confirm',headers=h,json={'preview_token':r.json()['preview_token']}).status_code==409


def test_data_quality_queries_are_independent_of_product_count():
    with SessionLocal() as db:
        products=[Product(code=f'CHECK-{i}',name=f'Check {i}') for i in range(15)]
        db.add_all(products);db.flush()
        statements=[]

        def track(_conn,_cursor,statement,_params,_context,_many):
            if statement.lstrip().upper().startswith('SELECT'):statements.append(statement)

        event.listen(db.bind,'before_cursor_execute',track)
        try:
            single=data_quality(db,date(2026,9,30),products[:1])
            single_queries=len(statements)
            statements.clear()
            all_products=data_quality(db,date(2026,9,30),products)
            all_queries=len(statements)
        finally:
            event.remove(db.bind,'before_cursor_execute',track)
        assert single['counts']['route_missing']==1
        assert all_products['counts']['route_missing']==15
        assert all_queries==single_queries


def test_preview_becomes_stale_after_master_edit():
    with SessionLocal() as db:db.add(Product(code='P1',name='Part 1'));db.commit()
    c=TestClient(app);h=headers(c)
    r=c.post('/api/import/preview/historical-daily-mis',headers=h,files={'file':('history.xlsx',workbook())})
    with SessionLocal() as db:db.scalar(select(Product)).plant='Changed Plant';db.commit()
    assert c.post('/api/import/confirm',headers=h,json={'preview_token':r.json()['preview_token']}).status_code==409
    with SessionLocal() as db:assert db.scalar(select(func.count()).select_from(DailyMIS))==0


def test_partial_receipts_are_additive_idempotent_and_capped():
    with SessionLocal() as db:
        p=Product(code='P1',name='Part 1');v=Vendor(code='V1',name='V1');op=Operation(code='O1',name='O1');db.add_all([p,v,op]);db.flush()
        route=RouteVersion(product_id=p.id,revision_no=0,effective_from=date(2026,1,1));db.add(route);db.flush()
        ro=RouteOperation(route_version_id=route.id,operation_id=op.id,sequence_no=1);db.add(ro);db.flush()
        vm=VendorMovement(product_id=p.id,vendor_id=v.id,route_operation_id=ro.id,outward_date=date.today()-timedelta(days=40),outward_qty=100);db.add(vm);db.commit();mid=vm.id
    c=TestClient(app);h=headers(c)
    payload=dict(receipt_date=date.today().isoformat(),receipt_qty=30,reject_qty=2,reference='R1')
    r=c.post(f'/api/vendor/movements/{mid}/receipts',headers=h,json=payload)
    assert r.status_code==200,r.text
    assert r.json()['pending_qty']==70
    assert c.post(f'/api/vendor/movements/{mid}/receipts',headers=h,json=payload).json()['status']=='already_received'
    r=c.post(f'/api/vendor/movements/{mid}/receipts',headers=h,json={**payload,'receipt_qty':40,'reference':'R2'})
    assert r.json()['pending_qty']==30,r.text
    assert c.post(f'/api/vendor/movements/{mid}/receipts',headers=h,json={**payload,'receipt_qty':31,'reference':'R3'}).status_code==409
    with SessionLocal() as db:
        assert db.get(VendorMovement,mid).receipt_qty==70
        assert len(db.scalars(select(VendorReceipt)).all())==2


def test_insights_reminders_and_drilldown():
    with SessionLocal() as db:
        p=Product(code='P1',name='Part 1');db.add(p);db.flush()
        db.add(DailyMIS(product_id=p.id,mis_date=date.today(),plan_qty=100,actual_qty=50))
        a=Action(action_no='A1',reference_date=date.today(),problem_description='Repeated defect',action_description='Repair',due_at=datetime.now()-timedelta(days=15))
        db.add(a);db.flush();db.add(ActionWhyWhy(action_id=a.id,effectiveness_check_date=date.today()-timedelta(days=2)));db.commit()
    c=TestClient(app);h=headers(c);d=date.today().isoformat()
    assert c.get(f'/api/insights/data-quality?as_of={d}',headers=h).json()['counts']['route_missing']==1
    assert c.get(f'/api/insights/exceptions?as_of={d}',headers=h).json()['counts']['low_compliance']==1
    for kind in ['compliance','ppm','oee']:
        r=c.get(f'/api/insights/drilldown/{kind}?from_date={d}&to_date={d}',headers=h);assert r.status_code==200,r.text
    for _ in range(2):
        r=c.get('/api/insights/escalation',headers=h);assert r.status_code==200,r.text
    assert r.json()['actions'][0]['level']=='ADMIN'
    with SessionLocal() as db:assert len(db.scalars(select(ActionReminder)).all())==2
