from datetime import date, timedelta
from io import BytesIO
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import select
from app.main import app
from app.db import SessionLocal
from app.models import Product, User, VendorMovement, Vendor, RouteVersion, RouteOperation, Operation, QualityRejectionMonthlyHistory, DailyMIS, QualityPhenomenon
from app.enums import UserRole
from app.auth import hash_password
from test_governance_security import headers


def test_import_preview_rejects_closed_month_and_collects_row_errors():
    with SessionLocal() as db:db.add(Product(code='P1',name='Part 1'));db.commit()
    c=TestClient(app);h=headers(c)
    c.post('/api/governance/months/close',headers=h,json={'month':'2026-08-01','reason':'Month approved'})
    wb=Workbook();ws=wb.active;ws.title='Historical_Daily_MIS_Import';ws.append(['Date','Product','Plan_Qty','Actual_Qty']);ws.append([date(2026,8,2),'Part 1',100,90])
    b=BytesIO();wb.save(b)
    r=c.post('/api/import/preview/historical-daily-mis',headers=h,files={'file':('history.xlsx',b.getvalue())})
    assert not r.json()['can_confirm'] and 'closed' in r.json()['errors'][0],r.text
    ws.append(['invalid','Unknown',-1,-2]);ws.append(['invalid','Unknown 2',-3,-4]);b=BytesIO();wb.save(b)
    r=c.post('/api/import/preview/historical-daily-mis',headers=h,files={'file':('history.xlsx',b.getvalue())})
    assert r.json()['counts']['rejected']==2,r.text
    assert any('Row 3:' in x for x in r.json()['errors']) and any('Row 4:' in x for x in r.json()['errors'])


def test_quality_user_cannot_import_planning_workbook():
    with SessionLocal() as db:db.add(User(username='quality',full_name='Quality',password_hash=hash_password('QualityPassword123!'),role=UserRole.QUALITY,must_change_password=False));db.commit()
    c=TestClient(app);h=headers(c,'quality','QualityPassword123!')
    assert c.post('/api/import/preview/historical-daily-mis',headers=h,files={'file':('a.xlsx',b'')}).status_code==403


def test_dispatch_ppm_prefers_matching_mis_over_stale_uploaded_denominator():
    from app.api.quality import _history_dispatch_resolution
    with SessionLocal() as db:
        p=Product(code='P1',name='Part 1');phen=QualityPhenomenon(code='PH1',name='Defect',normalized_name='defect');db.add_all([p,phen]);db.flush()
        db.add(DailyMIS(product_id=p.id,mis_date=date(2026,8,3),actual_qty=200))
        r=QualityRejectionMonthlyHistory(record_key='R1',month=date(2026,8,1),product_id=p.id,phenomenon_id=phen.id,reject_qty=2,dispatch_qty=100,denominator_source='Disp_Done')
        db.add(r);db.flush()
        assert _history_dispatch_resolution(db,[r])[r.id]==(200,'MIS_HISTORY')
