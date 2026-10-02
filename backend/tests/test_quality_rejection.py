from datetime import date
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook
from sqlalchemy import select

from app.db import SessionLocal
from app.enums import OperationType, SourceType
from app.models import (
    Customer, DailyMIS, Operation, Product, QualityPhenomenon, QualityRejectionDaily,
    RouteOperation, RouteVersion,
)
from app.services.quality_import import import_daily_rejection_workbook, upsert_phenomenon


def _headers_for_quality(client):
    login = client.post('/api/auth/login', json={'username':'admin','password':'ChangeMe123!'})
    assert login.status_code == 200
    return {'Authorization': f"Bearer {login.json()['access_token']}"}


def _seed_quality_context(db):
    c=Customer(code='Q-C',name='Quality Customer');db.add(c);db.flush()
    p=Product(code='Q-P',name='K70 Cylinder block',customer_id=c.id,plant='2020',product_group='CI');db.add(p);db.flush()
    op=Operation(code='DISP_DONE',name='Disp_Done',operation_type=OperationType.DISPATCH);db.add(op);db.flush()
    rv=RouteVersion(product_id=p.id,revision_no=0,effective_from=date(2026,9,1),is_active=True);db.add(rv);db.flush()
    ro=RouteOperation(route_version_id=rv.id,operation_id=op.id,sequence_no=10,is_dispatch=True,standard_yield=Decimal('1'));db.add(ro)
    mis=DailyMIS(mis_date=date(2026,9,30),product_id=p.id,plan_qty=Decimal('2100'),actual_qty=Decimal('2000'),sales_price=Decimal('1'),plan_sales=Decimal('2100'),actual_sales=Decimal('2000'),source=SourceType.MANUAL);db.add(mis)
    ph=upsert_phenomenon(db,'BORE O/S',default_team='Operation')
    db.commit()
    return p,ro,ph


def _make_daily_xlsx(path:Path,reject=15):
    wb=Workbook();ws=wb.active;ws.title='Daily_Rejection_Data'
    ws.append(['Date','Shift','Product','Plant','Customer','Type','Detection Process','Responsible Process','Machine','Phenomenon','Reject Qty','Rework Qty','Scrap Qty','Remark','Raise Action'])
    ws.append([date(2026,9,30),'A','K70 Cylinder block','2020','Quality Customer','CI','Disp_Done','',None,'BORE O/S',reject,5,10,'Daily check','Yes'])
    wb.save(path)


def test_daily_rejection_uses_dispatch_done_denominator(tmp_path):
    path=tmp_path/'daily_quality.xlsx';_make_daily_xlsx(path,15)
    with SessionLocal() as db:
        _seed_quality_context(db)
        stats=import_daily_rejection_workbook(db,path)
        db.commit()
        assert stats['created']==1
        row=db.scalar(select(QualityRejectionDaily))
        assert row.denominator_source=='DISP_DONE'
        assert row.denominator_qty==Decimal('2000')
        assert row.ppm==Decimal('7500.000')
        assert row.action_required is True


def test_daily_rejection_business_key_updates_instead_of_duplicate(tmp_path):
    path=tmp_path/'daily_quality.xlsx';_make_daily_xlsx(path,15)
    with SessionLocal() as db:
        _seed_quality_context(db)
        first=import_daily_rejection_workbook(db,path);db.commit()
        assert first['created']==1
        _make_daily_xlsx(path,18)
        second=import_daily_rejection_workbook(db,path);db.commit()
        assert second['updated']==1
        assert db.query(QualityRejectionDaily).count()==1
        row=db.scalar(select(QualityRejectionDaily))
        assert row.reject_qty==Decimal('18')
        assert row.ppm==Decimal('9000.000')


def test_phenomenon_upsert_dedupes_same_batch_and_suffixes_code_collisions():
    """Regression: SessionLocal has autoflush=False, so same-workbook masters must be flushed."""
    with SessionLocal() as db:
        p1 = upsert_phenomenon(db, 'DAMAGE', default_team='Operation')
        p2 = upsert_phenomenon(db, 'Damage', default_team='Operation')
        p3 = upsert_phenomenon(db, 'OD -', default_team='Operation')
        p4 = upsert_phenomenon(db, 'OD (-) (+)', default_team='Operation')
        db.commit()

        assert p1.id == p2.id
        assert p1.code == 'DAMAGE'
        assert p3.code == 'OD'
        assert p4.code == 'OD_2'
        rows = db.scalars(select(QualityPhenomenon)).all()
        assert len(rows) == 3


def test_historical_rejection_duplicate_record_keys_fail_preflight(tmp_path):
    from openpyxl import Workbook
    from app.services.quality_import import import_historical_rejection_workbook

    path = tmp_path / 'historical_dup.xlsx'
    wb = Workbook()
    ws = wb.active
    ws.title = 'Historical_Rejection_Import'
    ws.append([
        'Record_Key','Month','WebApp_Product','Phenomenon_WebApp','Reject_Qty',
        'Source','Source_Sheet','Record_Scope','Include_In_Overall_Aggregate',
        'Detection_Operation','Responsible_Team','Denominator_Source'
    ])
    key = 'HMCL|Total|2026-06|Damage'
    ws.append([key, date(2026,6,1), 'K70 Cylinder block', 'BORE O/S', 10, 'HMCL', 'Total', 'AGGREGATE_TOTAL', 'Yes', 'Disp_Done', 'Operation', 'DISP_DONE'])
    ws.append([key, date(2026,6,1), 'K70 Cylinder block', 'BORE O/S', 15, 'HMCL', 'Total', 'AGGREGATE_TOTAL', 'Yes', 'Disp_Done', 'Operation', 'DISP_DONE'])
    wb.save(path)

    with SessionLocal() as db:
        _seed_quality_context(db)
        try:
            import_historical_rejection_workbook(db, path)
            assert False, 'expected duplicate Record_Key validation error'
        except ValueError as exc:
            text = str(exc)
            assert 'duplicate Record_Key' in text
            assert key in text


def test_historical_rejection_visible_without_dispatch_qty():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.models import QualityRejectionMonthlyHistory

    with SessionLocal() as db:
        p, _, ph = _seed_quality_context(db)
        db.add(QualityRejectionMonthlyHistory(
            record_key='HMCL|Total|2026-06|BORE O/S',
            month=date(2026,6,1), source='HMCL', source_sheet='Total', record_scope='AGGREGATE_TOTAL',
            include_in_aggregate=True, product_id=p.id, plant=None, detection_operation='Disp_Done',
            responsible_team='Operation', phenomenon_id=ph.id, reject_qty=Decimal('25'),
            denominator_source='DISP_DONE', dispatch_qty=None, ppm=None,
        ))
        db.commit()

    client = TestClient(app)
    login = client.post('/api/auth/login', json={'username':'admin','password':'ChangeMe123!'})
    assert login.status_code == 200
    h={'Authorization': f"Bearer {login.json()['access_token']}"}

    r = client.get('/api/quality/dashboard?from_date=2026-06-01&to_date=2026-06-30', headers=h)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j['reject_qty'] == 25.0
    assert j['historical_records'] == 1
    assert j['denominator_qty'] == 0.0
    assert j['ppm'] is None

    pto = client.get('/api/quality/pareto?group_by=phenomenon&from_date=2026-06-01&to_date=2026-06-30', headers=h)
    assert pto.status_code == 200, pto.text
    assert pto.json()[0]['reject_qty'] == 25.0

    hist = client.get('/api/quality/history?from_date=2026-06-01&to_date=2026-06-30', headers=h)
    assert hist.status_code == 200, hist.text
    assert len(hist.json()) == 1
    assert hist.json()[0]['dispatch_qty'] is None


def test_zero_rejection_without_denominator_does_not_block_month_ppm():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.models import QualityRejectionMonthlyHistory

    with SessionLocal() as db:
        p, _, ph = _seed_quality_context(db)
        db.add_all([
            QualityRejectionMonthlyHistory(
                record_key='HMCL|Total|2026-06|HAS REJECTION', month=date(2026,6,1), source='HMCL',
                source_sheet='Total', record_scope='AGGREGATE_TOTAL', include_in_aggregate=True,
                product_id=p.id, phenomenon_id=ph.id, reject_qty=Decimal('25'),
                denominator_source='DISP_DONE', dispatch_qty=Decimal('2500'), ppm=Decimal('10000'),
            ),
            QualityRejectionMonthlyHistory(
                record_key='HMCL|Total|2026-06|ZERO', month=date(2026,6,1), source='HMCL',
                source_sheet='Total', record_scope='AGGREGATE_TOTAL', include_in_aggregate=True,
                product_id=p.id, phenomenon_id=ph.id, reject_qty=Decimal('0'),
                denominator_source='DISP_DONE', dispatch_qty=None, ppm=None,
            ),
        ])
        db.commit()

    client = TestClient(app)
    h = _headers_for_quality(client)
    dashboard = client.get('/api/quality/dashboard?from_date=2026-06-01&to_date=2026-06-30', headers=h).json()
    trend = client.get('/api/quality/monthly-trend?from_month=2026-06-01&to_month=2026-06-01', headers=h).json()[0]
    assert dashboard['ppm_pending_rows'] == 0
    assert dashboard['ppm'] == 10000.0
    assert trend['ppm_pending_rows'] == 0
    assert trend['ppm'] == 10000.0


def test_historical_rejection_auto_uses_historical_mis_dispatch_qty():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.models import QualityRejectionMonthlyHistory

    with SessionLocal() as db:
        p, _, ph = _seed_quality_context(db)
        # Matching historical MIS for June; monthly Actual = 1,000 + 1,500 = 2,500.
        db.add(DailyMIS(mis_date=date(2026,6,10), product_id=p.id, plan_qty=Decimal('1100'), actual_qty=Decimal('1000'),
                        sales_price=Decimal('1'), plan_sales=Decimal('1100'), actual_sales=Decimal('1000'), source=SourceType.EXCEL))
        db.add(DailyMIS(mis_date=date(2026,6,20), product_id=p.id, plan_qty=Decimal('1600'), actual_qty=Decimal('1500'),
                        sales_price=Decimal('1'), plan_sales=Decimal('1600'), actual_sales=Decimal('1500'), source=SourceType.EXCEL))
        db.add(QualityRejectionMonthlyHistory(
            record_key='HMCL|Total|2026-06|MIS AUTO',
            month=date(2026,6,1), source='HMCL', source_sheet='Total', record_scope='AGGREGATE_TOTAL',
            include_in_aggregate=True, product_id=p.id, plant=None, detection_operation='Disp_Done',
            responsible_team='Operation', phenomenon_id=ph.id, reject_qty=Decimal('25'),
            denominator_source='DISP_DONE', dispatch_qty=None, ppm=None,
        ))
        db.commit()

    client = TestClient(app)
    login = client.post('/api/auth/login', json={'username':'admin','password':'ChangeMe123!'})
    assert login.status_code == 200
    h={'Authorization': f"Bearer {login.json()['access_token']}"}

    hist = client.get('/api/quality/history?from_date=2026-06-01&to_date=2026-06-30', headers=h)
    assert hist.status_code == 200, hist.text
    row = hist.json()[0]
    assert row['dispatch_qty'] == 2500.0
    assert row['dispatch_qty_source'] == 'MIS_HISTORY'
    assert row['ppm'] == 10000.0

    dash = client.get('/api/quality/dashboard?from_date=2026-06-01&to_date=2026-06-30', headers=h)
    assert dash.status_code == 200, dash.text
    j = dash.json()
    assert j['denominator_qty'] == 2500.0
    assert j['ppm'] == 10000.0


def test_historical_rejection_import_persists_mis_dispatch_fallback(tmp_path):
    from openpyxl import Workbook
    from app.services.quality_import import import_historical_rejection_workbook
    from app.models import QualityRejectionMonthlyHistory

    path = tmp_path / 'historical_mis_denominator.xlsx'
    wb = Workbook()
    ws = wb.active
    ws.title = 'Historical_Rejection_Import'
    ws.append([
        'Record_Key','Month','WebApp_Product','Phenomenon_WebApp','Reject_Qty',
        'Source','Source_Sheet','Record_Scope','Include_In_Overall_Aggregate',
        'Detection_Operation','Responsible_Team','Denominator_Source'
    ])
    ws.append(['HMCL|Total|2026-06|AUTO', date(2026,6,1), 'K70 Cylinder block', 'BORE O/S', 20,
               'HMCL', 'Total', 'AGGREGATE_TOTAL', 'Yes', 'Disp_Done', 'Operation', 'DISP_DONE'])
    wb.save(path)

    with SessionLocal() as db:
        p, _, _ = _seed_quality_context(db)
        db.add(DailyMIS(mis_date=date(2026,6,15), product_id=p.id, plan_qty=Decimal('2100'), actual_qty=Decimal('2000'),
                        sales_price=Decimal('1'), plan_sales=Decimal('2100'), actual_sales=Decimal('2000'), source=SourceType.EXCEL))
        db.commit()
        stats = import_historical_rejection_workbook(db, path)
        db.commit()
        assert stats['dispatch_from_mis'] == 1
        row = db.scalar(select(QualityRejectionMonthlyHistory).where(QualityRejectionMonthlyHistory.record_key=='HMCL|Total|2026-06|AUTO'))
        assert row.dispatch_qty == Decimal('2000')
        assert row.ppm == Decimal('10000.000')
