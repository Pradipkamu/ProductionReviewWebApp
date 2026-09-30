from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import Customer, DailyMIS, Product, SalesPriceHistory, WorkingCalendarChangeLog


def auth_headers(client: TestClient):
    r = client.post('/api/auth/login', json={'username':'admin','password':'ChangeMe123!'})
    assert r.status_code == 200
    return {'Authorization': f"Bearer {r.json()['access_token']}"}


def seed_product():
    with SessionLocal() as db:
        c = Customer(code='P-C', name='Price Customer'); db.add(c); db.flush()
        p = Product(code='P-P', name='Price Part', customer_id=c.id, plant='2020', product_group='CI'); db.add(p); db.flush()
        db.add(SalesPriceHistory(product_id=p.id, effective_from=date(2026,9,1), price=Decimal('100'), source='EXCEL', reason='Opening'))
        db.add_all([
            DailyMIS(mis_date=date(2026,9,14), product_id=p.id, plan_qty=10, actual_qty=8, sales_price=100, plan_sales=1000, actual_sales=800),
            DailyMIS(mis_date=date(2026,9,15), product_id=p.id, plan_qty=10, actual_qty=9, sales_price=100, plan_sales=1000, actual_sales=900),
        ])
        db.commit(); return p.id


def test_price_revision_preserves_history_and_reprices_future_mis():
    pid=seed_product(); client=TestClient(app); h=auth_headers(client)
    r=client.post('/api/masters/prices', headers=h, json={'product_id':pid,'effective_from':'2026-09-15','price':125,'reason':'Customer revision'})
    assert r.status_code==200, r.text
    hist=client.get(f'/api/masters/prices/{pid}',headers=h).json()
    assert hist[0]['price']==125
    with SessionLocal() as db:
        a=db.query(DailyMIS).filter_by(product_id=pid,mis_date=date(2026,9,14)).one()
        b=db.query(DailyMIS).filter_by(product_id=pid,mis_date=date(2026,9,15)).one()
        assert Decimal(str(a.sales_price))==Decimal('100.0000')
        assert Decimal(str(b.sales_price))==Decimal('125.0000')
        assert Decimal(str(b.actual_sales))==Decimal('1125.00')


def test_calendar_defaults_bulk_and_history():
    client=TestClient(app); h=auth_headers(client)
    rows=client.get('/api/masters/calendar?month=2026-09-01&plant=2020',headers=h).json()
    assert len(rows)==30
    sunday=[x for x in rows if x['date']=='2026-09-06'][0]
    assert sunday['working'] is False and sunday['explicit'] is False
    r=client.post('/api/masters/calendar/bulk',headers=h,json={
        'plant':'2020','start_date':'2026-09-21','end_date':'2026-09-22','mode':'SET_OFF',
        'holiday_name':'Plant shutdown','reason':'Maintenance shutdown'
    })
    assert r.status_code==200, r.text
    rows=client.get('/api/masters/calendar?month=2026-09-01&plant=2020',headers=h).json()
    d21=[x for x in rows if x['date']=='2026-09-21'][0]
    assert d21['working'] is False and d21['holiday']=='Plant shutdown' and d21['explicit'] is True
    hist=client.get('/api/masters/calendar/history?month=2026-09-01&plant=2020',headers=h).json()
    assert len(hist)>=2
    with SessionLocal() as db:
        assert db.query(WorkingCalendarChangeLog).count()>=2
