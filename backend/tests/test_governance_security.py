from datetime import date, datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app
from app.models import User, Product, DailyMIS, GovernanceAudit, HistoricalCorrectionGrant, SecurityEvent, UserSession
from app.db import SessionLocal
from app.enums import UserRole
from app.auth import hash_password


def headers(client, username='admin', password='ChangeMe123!'):
    r = client.post('/api/auth/login', json=dict(username=username, password=password))
    assert r.status_code == 200
    return {'Authorization': 'Bearer ' + r.json()['access_token']}


def test_initial_password_gate_and_token_revocation():
    with SessionLocal() as db:
        user = db.scalar(select(User)); user.must_change_password=True; db.commit()
    client = TestClient(app); h=headers(client)
    assert client.get('/api/masters/products', headers=h).status_code == 403
    assert client.get('/api/auth/me', headers=h).json()['must_change_password']
    r = client.post('/api/auth/change-password', headers=h, json=dict(current_password='ChangeMe123!',new_password='SaferPassword932!'))
    assert r.status_code == 200, r.text
    assert client.get('/api/auth/me', headers=h).status_code == 401
    assert client.get('/api/masters/products', headers={'Authorization':'Bearer '+r.json()['access_token']}).status_code == 200


def test_view_only_cannot_write_or_manage_users():
    with SessionLocal() as db:
        db.add(User(username='viewer', full_name='Viewer', role=UserRole.VIEW_ONLY, password_hash=hash_password('ViewPassword123!'),must_change_password=False)); db.commit()
    c=TestClient(app); h=headers(c, 'viewer', 'ViewPassword123!')
    assert c.get('/api/masters/products',headers=h).status_code == 200
    assert c.post('/api/masters/machines',headers=h,json={'code':'M1','name':'M1'}).status_code == 403
    assert c.get('/api/masters/users',headers=h).status_code == 403
    assert c.post('/api/governance/months/close',headers=h,json={'month':'2026-08-01','reason':'Month checked'}).status_code == 403


def test_month_close_grant_reason_audit_and_single_use():
    with SessionLocal() as db:
        p=Product(code='P1',name='P1');db.add(p);db.flush()
        row=DailyMIS(product_id=p.id,mis_date=date(2026,8,4),actual_qty=10,sales_price=2);db.add(row);db.commit(); rid=row.id; uid=db.scalar(select(User.id))
    c=TestClient(app);h=headers(c)
    assert c.post('/api/governance/months/close',headers=h,json={'month':'2026-08-17','reason':'Approved month close'}).status_code == 200
    payload={'actual_qty':11,'reason':'Approved quantity correction'}
    assert c.put(f'/api/mis/{rid}',headers=h,json=payload).status_code == 409
    grant=c.post('/api/governance/corrections',headers=h,json={'month':'2026-08-01','reason':'Approved quantity correction','user_id':uid}).json()['correction_id']
    hc={**h,'X-Correction-ID':str(grant)}
    r=c.put(f'/api/mis/{rid}',headers=hc,json=payload)
    assert r.status_code == 200,r.text
    assert c.put(f'/api/mis/{rid}',headers=hc,json={'actual_qty':12,'reason':'Another quantity correction'}).status_code == 409
    with SessionLocal() as db:
        audit=db.scalar(select(GovernanceAudit).where(GovernanceAudit.entity=='daily_mis'))
        assert '10' in audit.before_json and '11' in audit.after_json
        assert db.get(HistoricalCorrectionGrant,grant).used_at is not None
        assert db.get(DailyMIS,rid).actual_qty == 11


def test_login_lockout_session_revoke_and_security_audit():
    with SessionLocal() as db:
        db.add(User(
            username='operator',
            full_name='Operator',
            role=UserRole.PRODUCTION,
            password_hash=hash_password('OperatorPassword123!'),
            must_change_password=False,
        ))
        db.commit()

    c=TestClient(app)
    for _ in range(4):
        assert c.post('/api/auth/login',json={'username':'operator','password':'wrong'}).status_code == 401
    locked=c.post('/api/auth/login',json={'username':'operator','password':'wrong'})
    assert locked.status_code == 429
    assert c.post('/api/auth/login',json={'username':'operator','password':'OperatorPassword123!'}).status_code == 429

    with SessionLocal() as db:
        user=db.scalar(select(User).where(User.username=='operator'))
        assert user.failed_login_attempts == 5
        assert user.locked_until is not None
        assert db.scalar(select(SecurityEvent).where(SecurityEvent.username=='operator').order_by(SecurityEvent.id.desc())) is not None
        user.locked_until=datetime.utcnow()-timedelta(minutes=1)
        user.failed_login_attempts=0
        db.commit()

    login=c.post('/api/auth/login',json={'username':'operator','password':'OperatorPassword123!'})
    assert login.status_code == 200,login.text
    h={'Authorization':'Bearer '+login.json()['access_token']}
    status=c.get('/api/auth/security-status',headers=h)
    assert status.status_code == 200
    assert status.json()['https_required'] is False
    sessions=c.get('/api/auth/sessions',headers=h)
    assert sessions.status_code == 200 and len(sessions.json()) == 1
    session=sessions.json()[0]
    assert session['is_current'] is True and session['revoked_at'] is None
    revoked=c.delete(f"/api/auth/sessions/{session['id']}",headers=h)
    assert revoked.status_code == 200 and revoked.json()['current_session'] is True
    assert c.get('/api/auth/me',headers=h).status_code == 401
    with SessionLocal() as db:
        assert db.scalar(select(UserSession).where(UserSession.id==session['id'])).revoked_at is not None


def test_admin_can_review_all_sessions_and_security_events():
    c=TestClient(app)
    admin=headers(c)
    sessions=c.get('/api/auth/sessions?all_users=true',headers=admin)
    assert sessions.status_code == 200
    assert any(x['is_current'] for x in sessions.json())
    events=c.get('/api/auth/security-events?limit=20',headers=admin)
    assert events.status_code == 200
    assert any(x['event_type']=='LOGIN_SUCCESS' for x in events.json())
