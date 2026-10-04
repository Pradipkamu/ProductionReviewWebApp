from datetime import date
from openpyxl import Workbook
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from app.main import app
from app.db import SessionLocal
from app.models import DailyMIS, DailyRequirement, ProcessDailySummary, ImportBatch, GovernanceAudit, HistoricalCorrectionGrant, User, Product
from app.enums import UserRole
from test_governance_security import headers
from test_process_flows import setup, actual, HEADERS, preview


def workbook(tmp_path, plan=120, dispatch=8, stage_dispatch=None, reason='', extra=None, mis=True):
    w=Workbook();s=w.active;s.title='Daily_Actuals';s.append(HEADERS['stage-daily'])
    rows=[actual(qty=30,reject_qty=2,reason=reason),actual(code='P04_DISP_DONE',qty=dispatch if stage_dispatch is None else stage_dispatch,reason=reason)]
    if extra:rows.append(extra)
    for row in rows:s.append([row.get(k) for k in HEADERS['stage-daily']])
    if mis:
        m=w.create_sheet('Historical_Daily_MIS_Import');m.append(['Date','Product','Plan_Qty','Actual_Qty']);m.append([date(2026,10,2),'Kubota Head',plan,dispatch])
    p=tmp_path/'combined.xlsx';w.save(p);return p


def test_combined_preview_and_commit_populates_plan_actual_and_stage_once(tmp_path):
    setup();c=TestClient(app);h=headers(c);p=workbook(tmp_path)
    r=preview(c,h,p,'daily-production');assert r.json()['can_confirm'],r.text
    assert r.json()['counts']['new']==3
    assert r.json()['stats']['customer_mis']['mis_created']==1
    assert r.json()['stats']['stage_actuals']['new']==2
    with SessionLocal() as db:assert not db.scalar(select(DailyMIS)) and not db.scalar(select(ProcessDailySummary))
    token=r.json()['preview_token'];r=c.post('/api/import/confirm',headers=h,json={'preview_token':token});assert r.status_code==200,r.text
    with SessionLocal() as db:
        m=db.scalar(select(DailyMIS));assert (m.plan_qty,m.actual_qty)==(120,8)
        req=db.scalar(select(DailyRequirement).where(DailyRequirement.route_operation_id.is_(None)));assert (req.baseline_plan_qty,req.revised_plan_qty)==(120,120)
        assert db.scalar(select(func.count()).select_from(ProcessDailySummary))==2
        assert db.scalar(select(func.count()).select_from(ImportBatch))==1
    assert c.post('/api/import/confirm',headers=h,json={'preview_token':token}).status_code==409
    assert preview(c,h,p,'daily-production').json()['status']=='already_imported'
    p=workbook(tmp_path,reason='Same facts from refreshed export')
    r=preview(c,h,p,'daily-production');assert r.json()['counts']=={'new':0,'updated':0,'unchanged':3,'rejected':0},r.text


def test_dispatch_conflict_and_missing_tab_reject_without_any_writes(tmp_path):
    setup();c=TestClient(app);h=headers(c)
    p=workbook(tmp_path,stage_dispatch=9)
    assert not preview(c,h,p,'daily-production').json()['can_confirm']
    p=workbook(tmp_path,mis=False)
    assert not preview(c,h,p,'daily-production').json()['can_confirm']
    with SessionLocal() as db:assert not db.scalar(select(DailyMIS)) and not db.scalar(select(ProcessDailySummary))


def test_late_duplicate_stage_rolls_back_customer_plan_changes(tmp_path):
    setup();c=TestClient(app);h=headers(c)
    p=workbook(tmp_path,extra=actual(qty=30,reject_qty=2))
    r=preview(c,h,p,'daily-production');assert not r.json()['can_confirm'] and 'Duplicate' in str(r.json()['errors']),r.text
    with SessionLocal() as db:
        assert not db.scalar(select(DailyMIS)) and not db.scalar(select(DailyRequirement)) and not db.scalar(select(ProcessDailySummary))


def test_existing_plan_and_actual_corrections_need_reason_and_are_audited(tmp_path):
    setup();c=TestClient(app);h=headers(c)
    p=workbook(tmp_path);r=preview(c,h,p,'daily-production')
    assert c.post('/api/import/confirm',headers=h,json={'preview_token':r.json()['preview_token']}).status_code==200
    p=workbook(tmp_path,plan=130,dispatch=9)
    r=preview(c,h,p,'daily-production');assert not r.json()['can_confirm'],r.text
    with SessionLocal() as db:assert db.scalar(select(DailyMIS)).plan_qty==120
    p=workbook(tmp_path,plan=130,dispatch=8)
    assert not preview(c,h,p,'daily-production').json()['can_confirm']
    p=workbook(tmp_path,plan=130,dispatch=9,reason='Customer approved daily correction')
    r=preview(c,h,p,'daily-production');assert r.json()['can_confirm'],r.text
    assert c.post('/api/import/confirm',headers=h,json={'preview_token':r.json()['preview_token']}).status_code==200
    with SessionLocal() as db:
        m=db.scalar(select(DailyMIS));assert (m.plan_qty,m.actual_qty)==(130,9)
        evidence=db.scalars(select(GovernanceAudit).where(GovernanceAudit.entity=='daily_mis',GovernanceAudit.event=='UPDATE')).all()
        assert evidence and all(a.reason=='Customer approved daily correction' for a in evidence)


def test_closed_month_grant_not_consumed_by_preview_and_used_once(tmp_path):
    setup();c=TestClient(app);h=headers(c)
    assert c.post('/api/governance/months/close',headers=h,json={'month':'2026-10-01','reason':'Approved close'}).status_code==200
    p=workbook(tmp_path,reason='Authorized closed-month daily correction')
    assert not preview(c,h,p,'daily-production').json()['can_confirm']
    with SessionLocal() as db:uid=db.scalar(select(User.id).where(User.username=='admin'))
    grant=c.post('/api/governance/corrections',headers=h,json={'month':'2026-10-01','reason':'Authorized closed-month daily correction','user_id':uid}).json()['correction_id']
    hc={**h,'X-Correction-ID':str(grant)}
    r=preview(c,hc,p,'daily-production');assert r.json()['can_confirm'],r.text
    with SessionLocal() as db:assert db.get(HistoricalCorrectionGrant,grant).used_at is None and not db.scalar(select(DailyMIS))
    r=c.post('/api/import/confirm',headers=hc,json={'preview_token':r.json()['preview_token']});assert r.status_code==200,r.text
    with SessionLocal() as db:assert db.get(HistoricalCorrectionGrant,grant).used_at is not None


def test_stale_combined_preview_and_plan_roles(tmp_path):
    setup();c=TestClient(app);h=headers(c);p=workbook(tmp_path)
    r=preview(c,h,p,'daily-production');assert r.json()['can_confirm']
    with SessionLocal() as db:
        product=db.scalar(select(Product).order_by(Product.id));product.name=product.name+' revised';db.commit()
    assert c.post('/api/import/confirm',headers=h,json={'preview_token':r.json()['preview_token']}).status_code==409
    for role in [UserRole.PRODUCTION,UserRole.QUALITY,UserRole.VIEW_ONLY]:
        with SessionLocal() as db:db.scalar(select(User).where(User.username=='admin')).role=role;db.commit()
        assert preview(c,h,p,'daily-production').status_code==403
    with SessionLocal() as db:db.scalar(select(User).where(User.username=='admin')).role=UserRole.PLANNING;db.commit()
    assert preview(c,h,p,'daily-production').json()['can_confirm']
