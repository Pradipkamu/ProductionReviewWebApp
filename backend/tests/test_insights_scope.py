from datetime import date, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.enums import ActionStatus, Priority
from app.main import app
from app.models import Action, ActionContext, Product
from test_governance_security import headers


def test_action_escalation_respects_plant_and_product_scope():
    with SessionLocal() as db:
        product_a = Product(
            code="ESC-SCOPE-A-" + uuid4().hex[:6],
            name="Plant A Part",
            plant="Plant A",
            product_group="Machining",
        )
        product_b = Product(
            code="ESC-SCOPE-B-" + uuid4().hex[:6],
            name="Plant B Part",
            plant="Plant B",
            product_group="Casting",
        )
        db.add_all([product_a, product_b])
        db.flush()

        action_a = Action(
            action_no="ACT-ESC-A-" + uuid4().hex[:8],
            reference_date=date.today(),
            problem_category="Production",
            problem_description="Plant A overdue issue",
            action_description="Recover Plant A output",
            due_at=datetime.utcnow() - timedelta(days=3),
            priority=Priority.HIGH,
            status=ActionStatus.OPEN,
        )
        action_b = Action(
            action_no="ACT-ESC-B-" + uuid4().hex[:8],
            reference_date=date.today(),
            problem_category="Production",
            problem_description="Plant B overdue issue",
            action_description="Recover Plant B output",
            due_at=datetime.utcnow() - timedelta(days=3),
            priority=Priority.HIGH,
            status=ActionStatus.OPEN,
        )
        db.add_all([action_a, action_b])
        db.flush()
        db.add_all([
            ActionContext(action_id=action_a.id, context_date=date.today(), product_id=product_a.id),
            ActionContext(action_id=action_b.id, context_date=date.today(), product_id=product_b.id),
        ])
        expected_action_id = action_a.id
        db.commit()

    client = TestClient(app)
    response = client.get(
        "/api/insights/escalation?plant=Plant%20A&product_group=Machining",
        headers=headers(client),
    )
    assert response.status_code == 200, response.text
    rows = response.json()["actions"]
    assert expected_action_id in {row["id"] for row in rows}
    assert all("Plant A" in row["problem"] for row in rows)
