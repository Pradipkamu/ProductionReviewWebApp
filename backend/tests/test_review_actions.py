from datetime import date, datetime, timedelta
from io import BytesIO
from uuid import uuid4

from openpyxl import load_workbook

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.enums import ActionStatus, Priority, UserRole
from app.main import app
from app.models import (
    Action, ActionContext, ActionHistory, Customer, Product, ReviewActionLink,
    ReviewParticipantPresence, ReviewPoint, ReviewSession, User,
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
    created = client.post('/api/reviews', headers=h, json={
        'review_date':'2026-09-29', 'participants':'Production, Sales', 'comments':'Daily review'
    })
    assert created.status_code == 200, created.text
    assert created.json()['existing'] is False
    rid = created.json()['id']
    active = client.get('/api/reviews/active?review_date=2026-09-29', headers=h)
    assert active.status_code == 200
    assert active.json()['id'] == rid
    action = client.post('/api/actions', headers=h, json={
        'reference_date':'2026-09-29', 'problem_category':'Production',
        'problem_description':'Daily review shortfall', 'action_description':'Recover in next shift',
        'priority':'HIGH', 'contexts':[{'context_date':'2026-09-29','product_id':pid}]
    })
    assert action.status_code == 200, action.text
    assert rid in action.json()['review_session_ids']
    with SessionLocal() as db:
        links = db.query(ReviewActionLink).all()
        assert len(links) == 1
        assert links[0].review_session_id == rid
    point = client.post(f'/api/reviews/{rid}/points', headers=h, json={
        'category':'Production', 'discussion_point':'Review recovery of daily production shortfall',
        'action_required':False,
    })
    assert point.status_code == 200, point.text
    mom = client.get(f'/api/reviews/{rid}/mom', headers=h)
    assert mom.status_code == 200, mom.text
    assert action.json()['id'] in {x['id'] for x in mom.json()['linked_actions']}
    assert len(mom.json()['points']) == 1
    close = client.patch(f'/api/reviews/{rid}/close', headers=h, json={'comments':'Closed after assigning actions'})
    assert close.status_code == 200, close.text
    assert close.json()['ended_at'] is not None
    active_after = client.get('/api/reviews/active?review_date=2026-09-29', headers=h)
    assert active_after.status_code == 200
    assert active_after.json() is None
    assert client.patch(f'/api/reviews/{rid}/close', headers=h, json={'comments':'Closed'}).status_code == 200


def test_action_linking_is_scoped_to_the_current_users_active_mom():
    client = TestClient(app)
    h = auth_headers(client)
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.username == 'admin'))
        other = User(username=f'mom-other-{uuid4().hex[:8]}', full_name='Other Meeting Owner',
                     password_hash='not-used-in-this-test', role=UserRole.PRODUCTION, is_active=True,
                     must_change_password=False)
        db.add(other); db.flush()
        own = ReviewSession(review_date=date(2026,10,22), started_at=datetime.utcnow()-timedelta(minutes=5),
                            participants='Production', owner_id=admin.id)
        foreign = ReviewSession(review_date=date(2026,10,22), started_at=datetime.utcnow(),
                                participants='Quality', owner_id=other.id)
        db.add_all([own, foreign]); db.commit()
        own_id, foreign_id = own.id, foreign.id
    active = client.get('/api/reviews/active?review_date=2026-10-22', headers=h)
    assert active.status_code == 200, active.text
    assert active.json()['id'] == own_id
    created = client.post('/api/actions', headers=h, json={
        'reference_date':'2026-10-22', 'problem_category':'Production',
        'problem_description':'Scoped action link test',
        'action_description':'Link only to the caller\'s meeting', 'priority':'HIGH', 'contexts':[],
    })
    assert created.status_code == 200, created.text
    assert created.json()['review_session_ids'] == [own_id]
    assert foreign_id not in created.json()['review_session_ids']


def test_joined_participant_active_mom_is_not_reported_as_owner():
    client = TestClient(app)
    h = auth_headers(client)
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.username == 'admin'))
        owner = User(username=f'mom-presence-owner-{uuid4().hex[:8]}', full_name='MOM Owner',
                     password_hash='not-used-in-this-test', role=UserRole.PRODUCTION, is_active=True,
                     must_change_password=False)
        db.add(owner); db.flush()
        meeting = ReviewSession(review_date=date(2026,10,24), started_at=datetime.utcnow(),
                                participants='Production, Quality', owner_id=owner.id)
        db.add(meeting); db.flush()
        db.add(ReviewParticipantPresence(review_session_id=meeting.id, user_id=admin.id))
        db.commit()
        meeting_id = meeting.id
    response = client.get('/api/reviews/active?review_date=2026-10-24', headers=h)
    assert response.status_code == 200, response.text
    assert response.json()['id'] == meeting_id
    assert response.json()['is_owner'] is False
    assert response.json()['is_participant'] is True


def test_mom_point_and_action_stay_synchronised_in_both_directions():
    client = TestClient(app)
    h = auth_headers(client)
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.username == 'admin'))
        second_owner = User(username=f'mom-owner-{uuid4().hex[:8]}', full_name='Updated Action Owner',
                            password_hash='not-used-in-this-test', role=UserRole.QUALITY, is_active=True,
                            must_change_password=False)
        customer = Customer(code=f'MOM-SYNC-C-{uuid4().hex[:8]}', name='MOM Sync Customer')
        db.add_all([second_owner, customer]); db.flush()
        product_a = Product(code=f'MOM-SYNC-A-{uuid4().hex[:8]}', name='MOM Sync Product A',
                            customer_id=customer.id, plant='P1', product_group='CI')
        product_b = Product(code=f'MOM-SYNC-B-{uuid4().hex[:8]}', name='MOM Sync Product B',
                            customer_id=customer.id, plant='P1', product_group='CI')
        db.add_all([product_a, product_b]); db.commit()
        admin_id, new_owner_id = admin.id, second_owner.id
        product_a_id, product_b_id = product_a.id, product_b.id
    review = client.post('/api/reviews', headers=h, json={
        'review_date':'2026-10-23', 'participants':'Production, Quality', 'comments':'MOM action sync test',
    })
    assert review.status_code == 200, review.text
    rid = review.json()['id']
    point = client.post(f'/api/reviews/{rid}/points', headers=h, json={
        'category':'Quality', 'discussion_point':'Investigate bore rejection on Product A',
        'action_required':True, 'action_description':'Contain Product A and verify the defect cause',
        'owner_id':admin_id, 'due_at':'2026-10-25T10:00:00+05:30', 'priority':'HIGH', 'product_id':product_a_id,
    })
    assert point.status_code == 200, point.text
    point_id, action_id = point.json()['id'], point.json()['action']['id']
    with SessionLocal() as db:
        db.add(ActionContext(action_id=action_id, context_date=date(2026,10,22), product_id=product_a_id))
        db.commit()
    edited = client.patch(f'/api/reviews/{rid}/points/{point_id}', headers=h, json={
        'category':'Production', 'discussion_point':'Updated problem: inspect Product B bore rejection',
        'action_required':True,
        'action_description':'Contain Product B, complete root cause and verify effectiveness',
        'owner_id':new_owner_id, 'due_at':'2026-10-27T12:30:00+05:30',
        'priority':'CRITICAL', 'product_id':product_b_id,
    })
    assert edited.status_code == 200, edited.text
    with SessionLocal() as db:
        action = db.get(Action, action_id)
        assert action.problem_category == 'Production'
        assert action.problem_description == 'Updated problem: inspect Product B bore rejection'
        assert action.action_description == 'Contain Product B, complete root cause and verify effectiveness'
        assert action.owner_id == new_owner_id and action.priority == Priority.CRITICAL
        contexts = db.scalars(select(ActionContext).where(ActionContext.action_id == action_id)).all()
        assert len(contexts) == 2
        assert any(x.context_date == date(2026,10,23) and x.product_id == product_b_id for x in contexts)
        assert any(x.context_date == date(2026,10,22) and x.product_id == product_a_id for x in contexts)
        links = db.scalars(select(ReviewActionLink).where(ReviewActionLink.review_session_id == rid,
                                  ReviewActionLink.action_id == action_id)).all()
        assert len(links) == 1
        history = db.scalars(select(ActionHistory).where(ActionHistory.action_id == action_id).order_by(ActionHistory.id)).all()
        assert any('problem category' in (x.comment or '') and 'owner' in (x.comment or '') and 'priority' in (x.comment or '') for x in history)
    mom = client.get(f'/api/reviews/{rid}/mom', headers=h)
    assert mom.status_code == 200, mom.text
    mom_point = next(x for x in mom.json()['points'] if x['id'] == point_id)
    assert mom_point['action']['id'] == action_id
    assert mom_point['action']['owner_id'] == new_owner_id and mom_point['action']['priority'] == 'CRITICAL'
    assert mom_point['product_id'] == product_b_id
    assert action_id not in {x['id'] for x in mom.json()['linked_actions']}
    progress = client.patch(f'/api/actions/{action_id}', headers=h, json={'status':'IN_PROGRESS','comment':'Owner started investigation'})
    assert progress.status_code == 200, progress.text
    refreshed = client.get(f'/api/reviews/{rid}/mom', headers=h).json()
    refreshed_point = next(x for x in refreshed['points'] if x['id'] == point_id)
    assert refreshed_point['action']['status'] == 'IN_PROGRESS'
    assert refreshed['meeting']['action_count'] == 1
    closed = client.patch(f'/api/actions/{action_id}', headers=h, json={
        'status':'CLOSED', 'comment':'Verified and closed', 'closure_remark':'Inspection passed',
    })
    assert closed.status_code == 200, closed.text
    with SessionLocal() as db:
        assert db.get(Action, action_id).closed_at is not None
    blocked = client.patch(f'/api/reviews/{rid}/points/{point_id}', headers=h, json={
        'category':'Production', 'discussion_point':'Try to change a closed action',
        'action_required':True, 'action_description':'Change after closure',
        'owner_id':new_owner_id, 'due_at':'2026-10-28T10:00:00+05:30',
        'priority':'HIGH', 'product_id':product_b_id,
    })
    assert blocked.status_code == 409, blocked.text
    reopened = client.patch(f'/api/actions/{action_id}', headers=h, json={
        'status':'IN_PROGRESS', 'comment':'Reopened for additional verification',
    })
    assert reopened.status_code == 200, reopened.text
    with SessionLocal() as db:
        saved = db.get(Action, action_id)
        assert saved.status == ActionStatus.IN_PROGRESS and saved.closed_at is None
        assert saved.closure_remark is None
    final_mom = client.get(f'/api/reviews/{rid}/mom', headers=h).json()
    final_point = next(x for x in final_mom['points'] if x['id'] == point_id)
    assert final_point['action']['status'] == 'IN_PROGRESS'


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
        old_review = ReviewSession(review_date=date(2026, 10, 14), started_at=datetime.utcnow(), participants="Production", owner_id=owner.id)
        current_review = ReviewSession(review_date=date(2026, 10, 15), started_at=datetime.utcnow(), participants="Production", owner_id=owner.id)
        future_review = ReviewSession(review_date=date(2026, 10, 16), started_at=datetime.utcnow(), participants="Production", owner_id=owner.id)
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
    linked_action_ids = {x["id"] for x in response.json()["linked_actions"]}
    assert current_action_id in linked_action_ids
    assert future_id not in linked_action_ids

    export = client.get(f"/api/reviews/{current_id}/xlsx", headers=h)
    assert export.status_code == 200, export.text
    workbook = load_workbook(BytesIO(export.content), read_only=True)
    exported_rows = list(workbook["MOM"].iter_rows(min_row=7, values_only=True))
    assert any(row[1] == "Linked Action" and row[3] == "Test management issue" for row in exported_rows)
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
