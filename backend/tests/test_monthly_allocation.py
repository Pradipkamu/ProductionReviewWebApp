"""Integration tests for all-product monthly proposals and guarded approval."""
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app
from app.models import DailyRequirement
from test_capacity_planning import _setup_shared_machine_context, _post
from test_governance_security import headers


def test_monthly_preview_reserves_machine_and_bulk_approval_detects_schedule_changes():
    p1, ro1, p2, ro2, machine = _setup_shared_machine_context()
    client = TestClient(app)
    auth = headers(client)
    for ro in (ro1, ro2):
        _post(client, auth, "/api/masters/machine-maps", {
            "route_operation_id": ro, "machine_id": machine,
            "effective_from": "2026-02-01", "priority": 1, "reason": "approved mapping"
        })
        _post(client, auth, "/api/masters/cycle-times", {
            "route_operation_id": ro, "machine_id": machine, "effective_from": "2026-02-01",
            "ideal_cycle_time_sec": 60, "standard_cycle_time_sec": 60,
            "pieces_per_cycle": 1, "reason": "approved cycle"
        })
        _post(client, auth, "/api/capacity/operator-requirements", {
            "route_operation_id": ro, "machine_id": machine,
            "effective_from": "2026-02-01", "operators_per_machine": 0.5, "reason": "shared operator"
        })
    _post(client, auth, "/api/capacity/machine-settings", {
        "machine_id": machine, "effective_from": "2026-02-01",
        "shifts_per_day": 1, "shift_minutes": 480,
        "planned_break_minutes": 0, "planning_efficiency": 1,
        "reason": "approved hours"
    })
    url = "/api/capacity/monthly-preview?month=2026-02-01"
    preview = client.get(url, headers=auth)
    assert preview.status_code == 200, preview.text
    report = preview.json()
    assert len(report["operations"]) == 2
    assert sum(o["allocated_qty"] for o in report["operations"]) == 960
    assert any(a["kind"] == "SHORTAGE" for a in report["alerts"])
    assert report["machines"] and max(m["load_percent"] for m in report["machines"]) <= 100.0001

    approval = {
        "month": "2026-02-01", "strategy": "priority",
        "preview_token": report["preview_token"], "reason": "Approved all-product loading"
    }
    with SessionLocal() as db:
        row = db.scalar(select(DailyRequirement).where(DailyRequirement.product_id == p2))
        row.revised_plan_qty = 520
        db.commit()
    stale = client.post("/api/capacity/monthly-approve", headers=auth, json=approval)
    assert stale.status_code == 409, stale.text

    fresh = client.get(url, headers=auth).json()
    approval["preview_token"] = fresh["preview_token"]
    saved = client.post("/api/capacity/monthly-approve", headers=auth, json=approval)
    assert saved.status_code == 200, saved.text
    assert saved.json()["approved"] == 2
    second = client.get(url, headers=auth).json()
    assert all(o["source"] == "SAVED" for o in second["operations"])
    assert second["preview_token"] != approval["preview_token"]
