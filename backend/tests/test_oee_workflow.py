from datetime import date, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app
from app.enums import OEEComponent, OperationType
from app.models import (
    ActionContext, ActionWhyWhy, Customer, LossCategory, Machine, Operation,
    OperationMachineMap, Product, RouteOperation, RouteVersion, StandardCycleTime,
)


def _headers(client: TestClient) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"username": "admin", "password": "ChangeMe123!"})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _seed_oee_scope() -> tuple[int, int, int, int, int]:
    today = date.today()
    with SessionLocal() as db:
        customer = Customer(code="OEE-C", name="OEE Customer")
        db.add(customer); db.flush()
        product = Product(code="OEE-P", name="OEE Product", customer_id=customer.id)
        operation = Operation(code="OEE-OP", name="OEE Machining", operation_type=OperationType.INTERNAL)
        machine = Machine(code="OEE-M1", name="OEE Machine")
        db.add_all([product, operation, machine]); db.flush()
        version = RouteVersion(product_id=product.id, revision_no=0, effective_from=today - timedelta(days=1))
        db.add(version); db.flush()
        route = RouteOperation(route_version_id=version.id, operation_id=operation.id, sequence_no=10)
        db.add(route); db.flush()
        db.add(OperationMachineMap(route_operation_id=route.id, machine_id=machine.id, effective_from=today - timedelta(days=1)))
        db.add(StandardCycleTime(route_operation_id=route.id, machine_id=machine.id,
                                 effective_from=today - timedelta(days=1), ideal_cycle_time_sec=Decimal("30")))
        availability = db.scalar(select(LossCategory).where(LossCategory.oee_component == OEEComponent.AVAILABILITY))
        quality = db.scalar(select(LossCategory).where(LossCategory.oee_component == OEEComponent.QUALITY))
        db.commit()
        return product.id, route.id, machine.id, availability.id, quality.id


def test_controlled_oee_capture_reconciliation_and_actions():
    product_id, route_id, machine_id, availability_loss_id, quality_loss_id = _seed_oee_scope()
    client = TestClient(app); headers = _headers(client); day = date.today().isoformat()
    payload = {
        "production_date": day, "shift": "a", "product_id": product_id,
        "route_operation_id": route_id, "machine_id": machine_id,
        "shift_duration_min": 480, "planned_break_min": 30, "downtime_min": 30,
        "total_count": 100, "good_count": 95, "reject_count": 5,
        "ideal_cycle_time_sec": 99, "remarks": "Initial entry",
    }
    created = client.post("/api/oee/machine-entry", headers=headers, json=payload)
    assert created.status_code == 200, created.text
    entry = created.json()["entry"]
    assert entry["ideal_cycle_time_sec"] == 30.0
    assert any("master cycle" in x for x in created.json()["warnings"])
    assert client.post("/api/oee/machine-entry", headers=headers, json=payload).status_code == 409

    bad = {**payload, "total_count": 90, "good_count": 95}
    assert client.post("/api/oee/machine-entry", headers=headers, json=bad).status_code == 422
    assert client.put(f"/api/oee/machine-entry/{entry['id']}", headers=headers, json=payload).status_code == 422
    corrected = client.put(f"/api/oee/machine-entry/{entry['id']}",
                           headers={**headers, "X-Change-Reason": "Correct operator entry"},
                           json={**payload, "remarks": "Corrected"})
    assert corrected.status_code == 200, corrected.text

    loss_base = {"loss_date": day, "shift": "A", "product_id": product_id,
                 "route_operation_id": route_id, "machine_id": machine_id, "qty_loss": 0}
    availability = client.post("/api/oee/loss-events", headers=headers,
                               json={**loss_base, "loss_category_id": availability_loss_id,
                                     "duration_min": 20, "remark": "Breakdown"})
    quality = client.post("/api/oee/loss-events", headers=headers,
                          json={**loss_base, "loss_category_id": quality_loss_id,
                                "duration_min": 10, "qty_loss": 5, "remark": "Reject"})
    assert availability.status_code == quality.status_code == 200

    query = f"machine_id={machine_id}&summary_date={day}&shift=A&product_id={product_id}&route_operation_id={route_id}"
    summary = client.get(f"/api/oee/machine-summary?{query}", headers=headers).json()
    assert summary["summary"]["captured_loss_min"] == 20.0
    assert summary["summary"]["unclassified_loss_min"] == 10.0
    assert {x["component"] for x in summary["losses"]} == {"AVAILABILITY", "QUALITY"}
    data_quality = client.get(f"/api/insights/data-quality?as_of={day}&product_id={product_id}", headers=headers).json()
    assert data_quality["counts"]["oee_downtime_unclassified"] == 1

    loss_action = client.post(f"/api/oee/loss-events/{availability.json()['id']}/raise-action",
                              headers=headers, json={"priority": "HIGH"})
    assert loss_action.status_code == 200
    assert client.post(f"/api/oee/loss-events/{availability.json()['id']}/raise-action",
                       headers=headers, json={"priority": "HIGH"}).json()["status"] == "already_linked"
    oee_action_payload = {"production_date": day, "shift": "A", "product_id": product_id,
                          "route_operation_id": route_id, "machine_id": machine_id, "target_oee": .85}
    oee_action = client.post("/api/oee/raise-action", headers=headers, json=oee_action_payload)
    assert oee_action.status_code == 200, oee_action.text
    assert client.post("/api/oee/raise-action", headers=headers, json=oee_action_payload).json()["status"] == "already_linked"
    with SessionLocal() as db:
        assert db.scalar(select(ActionWhyWhy).where(ActionWhyWhy.action_id == oee_action.json()["action_id"]))
        assert db.scalar(select(ActionContext).where(ActionContext.loss_event_id == availability.json()["id"]))
