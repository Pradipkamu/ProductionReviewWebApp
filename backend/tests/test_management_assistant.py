from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app
from app.models import GovernanceAudit
from test_governance_security import headers


def test_management_assistant_query_returns_grounded_sources_and_audit():
    client = TestClient(app)
    response = client.post(
        "/api/insights/assistant-query",
        params={
            "query": "Which actions are overdue?",
            "as_of": date(2026, 11, 5).isoformat(),
        },
        headers=headers(client),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["query"] == "Which actions are overdue?"
    assert body["as_of"] == "2026-11-05"
    assert body["answer"]
    assert body["definition"]
    assert {x["path"] for x in body["sources"]} == {
        "/insights/exceptions",
        "/insights/escalation",
        "/insights/data-quality",
    }

    with SessionLocal() as db:
        audit = db.scalar(
            select(GovernanceAudit)
            .where(GovernanceAudit.event == "ASSISTANT_QUERY")
            .order_by(GovernanceAudit.id.desc())
        )
        assert audit is not None
        assert audit.reason == "Which actions are overdue?"
        assert "sources" in (audit.after_json or "")
