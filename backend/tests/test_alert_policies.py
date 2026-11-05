from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app
from app.models import AlertPolicy
from test_governance_security import headers


def test_alert_policy_can_be_read_and_updated_by_management():
    with SessionLocal() as db:
        policy = db.scalar(select(AlertPolicy).where(AlertPolicy.code == "dispatch_compliance"))
        if policy is None:
            policy = AlertPolicy(
                code="dispatch_compliance",
                name="Dispatch compliance minimum",
                threshold=0.9,
                recipient_roles="MANAGEMENT,ADMIN",
            )
            db.add(policy)
            db.commit()
            db.refresh(policy)
        policy_id = policy.id

    client = TestClient(app)
    response = client.get("/api/insights/alert-policies", headers=headers(client))
    assert response.status_code == 200, response.text
    rows = response.json()
    row = next(item for item in rows if item["id"] == policy_id)
    assert row["code"] == "dispatch_compliance"

    updated = client.patch(
        f"/api/insights/alert-policies/{policy_id}",
        params={"threshold": "0.95", "quiet_start": "22:00", "quiet_end": "06:00"},
        headers=headers(client),
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["threshold"] == 0.95
    assert body["quiet_start"] == "22:00"
    assert body["quiet_end"] == "06:00"
