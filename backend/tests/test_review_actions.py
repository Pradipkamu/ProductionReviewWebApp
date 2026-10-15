from datetime import date, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.enums import ActionStatus, Priority
from app.main import app
from app.models import (
    Action, ActionContext, ActionHistory, Customer, Product, ReviewActionLink,
    ReviewPoint, ReviewSession, User,
)


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

    # A meeting with a recorded discussion point must be retained on closure.
    point = client.post(f'/api/reviews/{rid}/points', headers=h, json={
        'category': 'Production', 'discussion_point': 'Review recovery of daily production shortfall',
        'action_required': False,
    })
    assert point.status_code == 200, point.text

    close = client.patch(f'/api/reviews/{rid}/close', headers=h, json={'comments':'Closed after assigning actions'})
    assert close.status_code == 200, close.text
    assert close.json()['ended_at'] is not None

    active_after = client.get('/api/reviews/active?review_date=2026-09-29', headers=h)
    assert active_after.status_code == 200
    assert active_after.json() is None

    # Closing again is safe/idempotent.
    close_again = client.patch(f'/api/reviews/{rid}/close', headers=h, json={'comments':'Closed'})
    assert close_again.status_code == 200


def test_empty_meeting_is_discarded_on_close():
    client = TestClient(app)
    h = auth_headers(client)
    created = client.post('/api/reviews', headers=h, json={
        'review_date': '2026-09-30', 'participants': 'Production',
        'comments': 'No topics raised',
    })
    assert created.status_code == 200, created.text
    rid = created.json()['id']
    closed = client.patch(f'/api/reviews/{rid}/close', headers=h, json={'comments': 'Nothing to discuss'})
    assert closed.status_code == 200, closed.text
    assert closed.json()['discarded'] is True
    with SessionLocal() as db:
        from app.models import ReviewSession
        assert db.get(ReviewSession, rid) is None



def test_review_history_carries_only_earlier_meeting_actions_and_counts_all_links():
    client = TestClient(app)
    h = auth_headers(client)
    with SessionLocal() as db:
        owner = db.scalar(select(User).where(User.username == "admin"))
        old_review = ReviewSession(review_date=date(2026, 10, 14), started_at=datetime.utcnow(), participants="Production")
        current_review = ReviewSession(review_date=date(2026, 10, 15), started_at=datetime.utcnow(), participants="Production")
        future_review = ReviewSession(review_date=date(2026, 10, 16), started_at=datetime.utcnow(), participants="Production")
        db.add_all([old_review, current_review, future_review])
        db.flush()

        def make_action(prefix, reference_date, action_type="WHY_WHY"):
            return Action(
                action_no=f"{prefix}-{uuid4().hex[:12]}",
                reference_date=reference_date,
                problem_description="Test management issue",
                action_description="Complete the committed corrective work",
                priority=Priority.HIGH,
                status=ActionStatus.OPEN,
                action_type=action_type,
                requires_whywhy=False,
                owner_id=owner.id,
                due_at=datetime.utcnow() - timedelta(days=1),
            )

        old_action = make_action("MOM-OLD", old_review.review_date)
        current_action = make_action("MOM-CURRENT", current_review.review_date)
        future_action = make_action("MOM-FUTURE", future_review.review_date)
        legacy_action = make_action("MOM-LEGACY", date(2026, 10, 13), "DAILY_REVIEW")
        db.add_all([old_action, current_action, future_action, legacy_action])
        db.flush()
        db.add_all([
            ReviewActionLink(review_session_id=old_review.id, action_id=old_action.id),
            ReviewActionLink(review_session_id=current_review.id, action_id=current_action.id),
            ReviewActionLink(review_session_id=future_review.id, action_id=future_action.id),
            ActionHistory(
                action_id=old_action.id,
                changed_by_id=owner.id,
                old_status=ActionStatus.OPEN,
                new_status=ActionStatus.IN_PROGRESS,
                changed_at=datetime.utcnow() - timedelta(hours=4),
                comment="Owner confirmed recovery is underway",
            ),
        ])
        current_id = current_review.id
        old_id, current_action_id, future_id, legacy_id = old_action.id, current_action.id, future_action.id, legacy_action.id
        db.commit()

    history = client.get("/api/reviews", headers=h)
    assert history.status_code == 200, history.text
    current_row = next(x for x in history.json() if x["id"] == current_id)
    assert current_row["action_count"] == 1
    assert current_row["overdue_action_count"] == 1

    response = client.get(f"/api/reviews/{current_id}/mom", headers=h)
    assert response.status_code == 200, response.text
    carried_ids = {x["id"] for x in response.json()["previous_pending_actions"]}
    assert old_id in carried_ids
    assert legacy_id in carried_ids
    assert current_action_id not in carried_ids
    assert future_id not in carried_ids
    old_item = next(x for x in response.json()["previous_pending_actions"] if x["id"] == old_id)
    assert old_item["last_followup_comment"] == "Owner confirmed recovery is underway"
    assert old_item["last_followup_at"] is not None

    # An empty MOM with an action linked through the Actions page must be retained.
    closed = client.patch(f"/api/reviews/{current_id}/close", headers=h, json={"comments": "Action reviewed"})
    assert closed.status_code == 200, closed.text
    assert closed.json()["discarded"] is False
    assert closed.json()["ended_at"] is not None


def test_mom_participants_product_context_and_action_accountability():
    client = TestClient(app)
    h = auth_headers(client)
    with SessionLocal() as db:
        owner = db.scalar(select(User).where(User.username == "admin"))
        customer = Customer(code=f"MOM-C-{uuid4().hex[:8]}", name="MOM Context Customer")
        db.add(customer); db.flush()
        product = Product(
            code=f"MOM-P-{uuid4().hex[:8]}",
            name="MOM Context Product",
            customer_id=customer.id,
            plant="P1",
            product_group="CI",
        )
        db.add(product); db.commit()
        owner_id, product_id = owner.id, product.id

    created = client.post("/api/reviews", headers=h, json={
        "review_date": "2026-10-15", "participants": "Production", "comments": "Initial notes",
    })
    assert created.status_code == 200, created.text
    rid = created.json()["id"]

    updated = client.patch(f"/api/reviews/{rid}", headers=h, json={
        "participants": "Production, Quality", "comments": "Daily management review",
    })
    assert updated.status_code == 200, updated.text
    assert updated.json()["participants"] == "Production, Quality"
    assert updated.json()["comments"] == "Daily management review"

    missing_due = client.post(f"/api/reviews/{rid}/points", headers=h, json={
        "category": "Quality",
        "discussion_point": "Check rejection increase for the selected product",
        "action_required": True,
        "action_description": "Verify defect root cause and contain affected stock",
        "owner_id": owner_id,
        "product_id": product_id,
    })
    assert missing_due.status_code == 422

    point = client.post(f"/api/reviews/{rid}/points", headers=h, json={
        "category": "Quality",
        "discussion_point": "Check rejection increase for the selected product",
        "action_required": True,
        "action_description": "Verify defect root cause and contain affected stock",
        "owner_id": owner_id,
        "due_at": "2026-10-17T10:00:00+05:30",
        "priority": "HIGH",
        "product_id": product_id,
    })
    assert point.status_code == 200, point.text
    assert point.json()["product_id"] == product_id
    assert point.json()["product"] == "MOM Context Product"

    with SessionLocal() as db:
        saved = db.scalar(select(ReviewPoint).where(ReviewPoint.review_session_id == rid))
        assert saved is not None and saved.product_id == product_id
        action_context = db.scalar(select(ActionContext).where(ActionContext.action_id == saved.action_id))
        assert action_context is not None and action_context.product_id == product_id

    closed = client.patch(f"/api/reviews/{rid}/close", headers=h, json={"comments": "Closed"})
    assert closed.status_code == 200
    assert closed.json()["discarded"] is False
