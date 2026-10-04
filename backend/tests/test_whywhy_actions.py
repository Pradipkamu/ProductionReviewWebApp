from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.api import actions as actions_api
from app.main import app
from app.models import Customer, Product


def auth_headers(client: TestClient):
    r = client.post('/api/auth/login', json={'username':'admin','password':'ChangeMe123!'})
    assert r.status_code == 200
    return {'Authorization': f"Bearer {r.json()['access_token']}"}


def test_standard_whywhy_required_for_action_closure(tmp_path, monkeypatch):
    monkeypatch.setattr(actions_api.settings, 'attachments_dir', str(tmp_path / 'attachments'))
    with SessionLocal() as db:
        c = Customer(code='WW-C', name='WhyWhy Customer')
        db.add(c); db.flush()
        p = Product(code='WW-P', name='WhyWhy Part', customer_id=c.id, plant='P1', product_group='CI')
        db.add(p); db.commit(); pid = p.id

    client = TestClient(app)
    h = auth_headers(client)
    created = client.post('/api/actions', headers=h, json={
        'reference_date':'2026-09-30',
        'problem_category':'Quality',
        'problem_description':'Bore oversize',
        'action_description':'Segregate suspect stock',
        'priority':'HIGH',
        'contexts':[{'context_date':'2026-09-30','product_id':pid}]
    })
    assert created.status_code == 200, created.text
    action_id = created.json()['id']

    plan = client.get(f'/api/actions/{action_id}/plan', headers=h)
    assert plan.status_code == 200
    assert plan.json()['plan']['containment_action'] == 'Segregate suspect stock'
    assert plan.json()['plan']['can_close'] is False

    premature = client.patch(f'/api/actions/{action_id}', headers=h, json={
        'status':'CLOSED', 'comment':'try close', 'closure_remark':'done'
    })
    assert premature.status_code == 400
    assert 'Why-Why' in premature.text

    saved = client.put(f'/api/actions/{action_id}/plan', headers=h, json={
        'why1':'Bore diameter drifted',
        'why2':'Insert was worn',
        'why3':'Tool life limit not followed',
        'root_cause':'Tool life control was not defined in the standard',
        'corrective_action':'Replace insert and define tool life limit',
        'preventive_action':'Apply tool life counter to similar operations',
        'verification_method':'Check next 100 pieces and daily trend',
        'verification_result':'100 pieces OK and PPM reduced',
        'effectiveness_result':'Effective - no recurrence in verification period',
        'lessons_learned':'Horizontal deployment to all boring machines'
    })
    assert saved.status_code == 200, saved.text
    assert saved.json()['plan']['can_close'] is True
    assert saved.json()['plan']['completion_percent'] == 100

    rejected = client.post(
        f'/api/actions/{action_id}/attachments',
        headers=h,
        files={'file':('unsafe.html',b'<script>alert(1)</script>','text/html')},
    )
    assert rejected.status_code == 422

    uploaded = client.post(
        f'/api/actions/{action_id}/attachments',
        headers=h,
        files={'file':('evidence.pdf',b'%PDF-1.7\ncontrolled evidence','application/pdf')},
        data={'caption':'Verification evidence'},
    )
    assert uploaded.status_code == 200, uploaded.text
    attachment_id=uploaded.json()['id']
    downloaded=client.get(f'/api/actions/{action_id}/attachments/{attachment_id}',headers=h)
    assert downloaded.status_code == 200
    assert downloaded.headers['x-content-type-options']=='nosniff'
    assert downloaded.headers['cache-control']=='private, no-store'

    pdf = client.get(f'/api/actions/{action_id}/pdf', headers=h)
    assert pdf.status_code == 200, pdf.text
    assert pdf.headers['content-type'].startswith('application/pdf')
    assert 'WhyWhy_ActionPlan.pdf' in pdf.headers.get('content-disposition', '')
    assert pdf.content.startswith(b'%PDF')
    assert len(pdf.content) > 1500

    closed = client.patch(f'/api/actions/{action_id}', headers=h, json={
        'status':'CLOSED', 'comment':'verified', 'closure_remark':'Why-Why completed and effective'
    })
    assert closed.status_code == 200, closed.text
    assert closed.json()['status'] == 'CLOSED'
