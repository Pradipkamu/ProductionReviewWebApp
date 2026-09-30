import json
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app
from app.models import DailyMIS, DailyRequirement, GovernanceAudit, HistoricalCorrectionGrant, Product, ScheduleRevision, User
from test_governance_security import headers


def imported_month():
    with SessionLocal() as db:
        p = Product(code='HMCL', name='HMCL Cylinder block', plant='2070')
        db.add(p); db.flush()
        for day in range(1, 32):
            d = date(2026, 5, day)
            db.add(DailyMIS(product_id=p.id, mis_date=d, plan_qty=0, actual_qty=180520 if day == 1 else 0))
            db.add(DailyRequirement(product_id=p.id, req_date=d, baseline_plan_qty=0, revised_plan_qty=0, is_frozen=True))
        db.commit()
        return p.id


def payload(pid, effective='2026-05-01'):
    return dict(product_id=pid, month='2026-05-01', effective_from=effective,
        monthly_target_qty=200000, reason='Correct missing imported May schedule')


def test_zero_historical_plan_requires_explicit_correction_and_reflects_in_report():
    pid = imported_month(); c = TestClient(app); h = headers(c)
    body = payload(pid)
    pv = c.post('/api/schedules/preview', headers=h, json=body).json()
    assert pv['protected_days'] == 31 and pv['result_plan_qty'] == 0
    assert c.post('/api/schedules', headers=h, json=body).status_code == 409
    with SessionLocal() as db:
        assert not db.scalars(select(ScheduleRevision)).all()
    body['correct_imported_plans'] = True
    pv = c.post('/api/schedules/preview', headers=h, json=body).json()
    assert pv['protected_days'] == 0 and pv['result_plan_qty'] == 200000
    result = c.post('/api/schedules', headers=h, json=body)
    assert result.status_code == 200, result.text
    assert result.json()['corrected_imported_days'] == 31
    report = c.get(f'/api/reports/compliance?as_of=2026-05-31&product_id={pid}', headers=h).json()
    assert report['summary']['plan'] == 200000
    assert report['summary']['actual'] == 180520
    with SessionLocal() as db:
        requirements = db.scalars(select(DailyRequirement)).all()
        assert all(r.baseline_plan_qty == 0 and r.is_frozen for r in requirements)
        mis = db.scalars(select(DailyMIS)).all()
        assert all(r.plan_qty == 0 and r.schedule_revision_id == result.json()['id'] for r in mis)
        audits = db.scalars(select(GovernanceAudit).where(GovernanceAudit.entity == 'daily_requirements', GovernanceAudit.event == 'UPDATE')).all()
        assert len(audits) == 31
        assert all(a.reason == body['reason'] for a in audits)
        assert Decimal(json.loads(audits[0].before_json)['revised_plan_qty']) == 0


def test_effective_date_preserves_earlier_nonzero_imported_plan_and_actual():
    pid = imported_month()
    with SessionLocal() as db:
        for r in db.scalars(select(DailyRequirement)):
            r.baseline_plan_qty = 100; r.revised_plan_qty = 100
        db.commit()
    c = TestClient(app); h = headers(c)
    body = {**payload(pid, '2026-05-15'), 'correct_imported_plans': True}
    result = c.post('/api/schedules', headers=h, json=body)
    assert result.status_code == 200, result.text
    with SessionLocal() as db:
        reqs = db.scalars(select(DailyRequirement).order_by(DailyRequirement.req_date)).all()
        assert all(r.revised_plan_qty == 100 and r.schedule_revision_id is None for r in reqs[:14])
        assert sum(r.revised_plan_qty for r in reqs[14:]) == 19480
        assert all(r.baseline_plan_qty == 100 and r.is_frozen for r in reqs)
        assert db.scalar(select(DailyMIS).where(DailyMIS.mis_date == date(2026, 5, 1))).actual_qty == 180520


def test_closed_month_authorization_survives_preview_and_is_consumed_on_apply():
    pid = imported_month(); c = TestClient(app); h = headers(c)
    body = {**payload(pid), 'correct_imported_plans': True}
    body['reason'] = ''
    assert c.post('/api/schedules', headers=h, json=body).status_code == 422
    body['reason'] = 'Correct missing May schedule'
    assert c.post('/api/governance/months/close', headers=h, json={'month':'2026-05-01', 'reason':'May finalized'}).status_code == 200
    assert c.post('/api/schedules', headers=h, json=body).status_code == 409
    with SessionLocal() as db:
        assert not db.scalars(select(ScheduleRevision)).all()
        uid = db.scalar(select(User.id).where(User.username == 'admin'))
    grant = c.post('/api/governance/corrections', headers=h, json={'month':'2026-05-01', 'reason':body['reason'], 'user_id':uid}).json()['correction_id']
    hc = {**h, 'X-Correction-ID':str(grant)}
    assert c.post('/api/schedules/preview', headers=hc, json=body).status_code == 200
    with SessionLocal() as db:
        assert db.get(HistoricalCorrectionGrant, grant).used_at is None
    result = c.post('/api/schedules', headers=hc, json=body)
    assert result.status_code == 200, result.text
    assert c.post('/api/schedules', headers=hc, json=body).status_code == 409
    with SessionLocal() as db:
        assert db.get(HistoricalCorrectionGrant, grant).used_at is not None
