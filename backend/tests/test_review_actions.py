from datetime import date

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import Customer, Product, ReviewActionLink


def auth_headers(client: TestClient):
    r = client.post('/api/auth/login', json={'username':'admin','password':'ChangeMe123!'})
    assert r.status_code == 200
    return {'Authorization': f"Bearer {r.json()['access_token']}"}


def test_review_sync_close_and_action_link():
    with SessionLocal() as db:
        c = Customer(code='REV-C', name='Review Customer')
        db.add(c); db.flush()
        p = Product(code='REV-P', name='Review Part', customer_id=c.id, plant='P1', product_group='CI')
        db.add(p); db.commit(); pid = p.id

    client = TestClient(app)
    h = auth_headers(client)

    r = client.post('/api/reviews', headers=h, json={
        'review_date':'2026-09-29', 'participants':'Production, Sales', 'comments':'Daily review'
    })
    assert r.status_code == 200, r.text
    rid = r.json()['id']

    # A second start on the same date reuses the active session.
    r2 = client.post('/api/reviews', headers=h, json={
        'review_date':'2026-09-29', 'participants':'', 'comments':'Daily review'
    })
    assert r2.status_code == 200
    assert r2.json()['id'] == rid
    assert r2.json()['existing'] is True

    active = client.get('/api/reviews/active?review_date=2026-09-29', headers=h)
    assert active.status_code == 200
    assert active.json()['id'] == rid

    a = client.post('/api/actions', headers=h, json={
        'reference_date':'2026-09-29',
        'problem_category':'Production',
        'problem_description':'Daily review shortfall',
        'action_description':'Recover in next shift',
        'priority':'HIGH',
        'contexts':[{'context_date':'2026-09-29','product_id':pid}]
    })
    assert a.status_code == 200, a.text
    assert rid in a.json()['review_session_ids']

    with SessionLocal() as db:
        links = db.query(ReviewActionLink).all()
        assert len(links) == 1
        assert links[0].review_session_id == rid

    close = client.patch(f'/api/reviews/{rid}/close', headers=h, json={'comments':'Closed after assigning actions'})
    assert close.status_code == 200, close.text
    assert close.json()['ended_at'] is not None

    active_after = client.get('/api/reviews/active?review_date=2026-09-29', headers=h)
    assert active_after.status_code == 200
    assert active_after.json() is None

    # Closing again is safe/idempotent.
    close_again = client.patch(f'/api/reviews/{rid}/close', headers=h, json={'comments':'Closed'})
    assert close_again.status_code == 200
