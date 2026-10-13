from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy import select, func

from app.db import SessionLocal
from app.main import app
from app.models import (
    Machine, Product, Operation, RouteVersion, RouteOperation,
    OperationMachineMap, StandardCycleTime, OperatorRequirementHistory,
    MachineCapacitySetting,
)
from app.enums import OperationType
from test_governance_security import headers


def test_complete_machine_setup_only_revises_modified_masters():
    with SessionLocal() as db:
        product = Product(code="SET-P", name="Setup Part")
        operation = Operation(code="SET-OP", name="OP10", operation_type=OperationType.INTERNAL)
        machine = Machine(code="SET-M", name="VMC")
        db.add_all([product, operation, machine])
        db.flush()
        route = RouteVersion(product_id=product.id, revision_no=1, effective_from=date(2026, 1, 1), is_active=True)
        db.add(route)
        db.flush()
        ro = RouteOperation(route_version_id=route.id, operation_id=operation.id, sequence_no=10)
        db.add(ro)
        db.commit()
        operation_id, machine_id = ro.id, machine.id
    client = TestClient(app)
    auth = headers(client)
    payload = {
        "route_operation_id": operation_id, "machine_id": machine_id,
        "effective_from": "2026-01-01", "priority": 1,
        "ideal_cycle_time_sec": 50, "standard_cycle_time_sec": 60, "pieces_per_cycle": 2,
        "operators_per_machine": 0.5, "shifts_per_day": 2, "shift_minutes": 480,
        "planned_break_minutes": 30, "planning_efficiency": 0.85,
        "reason": "Approved initial setup",
    }
    endpoint = "/api/capacity/complete-setup"
    first = client.post(endpoint, json=payload, headers=auth)
    assert first.status_code == 200, first.text
    assert set(first.json()["changed"]) == {"mapping", "cycle", "operator", "capacity"}
    same = client.post(endpoint, json=payload, headers=auth)
    assert same.status_code == 200, same.text
    assert same.json()["no_changes"]

    changed = {**payload, "effective_from": "2026-02-01",
               "operators_per_machine": 0.75, "reason": "Revised manpower"}
    second = client.post(endpoint, json=changed, headers=auth)
    assert second.status_code == 200, second.text
    assert second.json()["changed"] == ["operator"]
    data = client.get(endpoint, params={
        "route_operation_id": operation_id, "machine_id": machine_id,
        "effective_from": "2026-02-01",
    }, headers=auth)
    assert data.status_code == 200, data.text
    assert data.json()["operator"]["operators_per_machine"] == 0.75
    with SessionLocal() as db:
        for model, count in ((OperationMachineMap, 1), (StandardCycleTime, 1),
                             (OperatorRequirementHistory, 2), (MachineCapacitySetting, 1)):
            assert db.scalar(select(func.count()).select_from(model)) == count
        history = db.scalars(select(OperatorRequirementHistory).order_by(
            OperatorRequirementHistory.effective_from)).all()
        assert history[0].effective_to == date(2026, 1, 31)

    # Earlier dates must not insert new revisions ahead of the latest.
    old = client.post(endpoint, json={**changed, "effective_from": "2026-01-15",
                                      "operators_per_machine": 1}, headers=auth)
    assert old.status_code == 409, old.text


def test_complete_setup_invalid_values_leave_no_partial_master_updates():
    client = TestClient(app)
    auth = headers(client)
    response = client.post("/api/capacity/complete-setup", headers=auth, json={
        "route_operation_id": 999, "machine_id": 999, "effective_from": "2026-01-01",
        "priority": 1, "ideal_cycle_time_sec": 50, "pieces_per_cycle": 1,
        "operators_per_machine": 1, "shifts_per_day": 2, "shift_minutes": 480,
        "planned_break_minutes": 480, "planning_efficiency": 0.85,
        "reason": "Bad setup",
    })
    assert response.status_code == 422
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(OperationMachineMap)) == 0
