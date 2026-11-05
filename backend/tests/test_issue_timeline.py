from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.enums import ActionStatus, Priority
from app.main import app
from app.models import (
    Action, ActionContext, DailyRequirement, Product, ReviewPoint, ReviewSession, User,
)
from test_governance_security import headers


def test_issue_timeline_combines_mom_actions_and_dispatch_and_hides_private_mom():
    client = TestClient(app)
    auth = headers(client)
    with SessionLocal() as db:
        admin = db.query(User).filter_by(username="admin").one()
        product = Product(
            code="ISSUE-TL-" + uuid4().hex[:6],
            name="Issue Timeline Part",
            plant="Issue Timeline Plant",
            product_group="Machining",
        )
        db.add(product)
        db.flush()

        visible = ReviewSession(
            review_date=date(2026, 11, 4),
            started_at=datetime(2026, 11, 4, 9, 0),
            owner_id=admin.id,
        )
        private = ReviewSession(
            review_date=date(2026, 11, 4),
            started_at=datetime(2026, 11, 4, 10, 0),
            owner_id=None,
        )
        db.add_all([visible, private])
        db.flush()
        visible_point = ReviewPoint(
            review_session_id=visible.id,
            sequence_no=1,
            category="Production",
            discussion_point="Review recurring machining vibration",
            product_id=product.id,
            action_required=True,
        )
        private_point = ReviewPoint(
            review_session_id=private.id,
            sequence_no=1,
            category="Confidential",
            discussion_point="This private meeting must not appear",
            product_id=product.id,
            action_required=False,
        )
        action = Action(
            action_no="ACT-ISSUE-" + uuid4().hex[:8],
            reference_date=date(2026, 11, 4),
            problem_category="Production",
            problem_description="Machining vibration issue",
            action_description="Inspect fixture and spindle",
            priority=Priority.HIGH,
            status=ActionStatus.OPEN,
        )
        db.add_all([visible_point, private_point, action])
        db.flush()
        db.add(ActionContext(
            action_id=action.id,
            context_date=date(2026, 11, 4),
            product_id=product.id,
        ))
        db.add(DailyRequirement(
            req_date=date(2026, 11, 5),
            product_id=product.id,
            route_operation_id=None,
            baseline_plan_qty=Decimal("100"),
            revised_plan_qty=Decimal("100"),
        ))
        db.commit()
        product_id = product.id
        visible_point_id = visible_point.id
        action_id = action.id
        private_point_id = private_point.id

    response = client.get(
        f"/api/insights/issue-timeline?from_date=2026-11-04&to_date=2026-11-05&plant=Issue%20Timeline%20Plant&product_id={product_id}",
        headers=auth,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    event_ids = {row.get("source_id") for row in body["events"]}
    event_types = {row["event_type"] for row in body["events"]}
    assert visible_point_id in event_ids
    assert action_id in event_ids
    assert private_point_id not in event_ids
    assert "MOM_POINT" in event_types
    assert "ACTION" in event_types
    assert "DISPATCH_ACTUAL_PENDING" in event_types
    assert body["summary"]["events"] == len(body["events"])
