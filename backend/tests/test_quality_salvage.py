from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import hash_password
from app.db import SessionLocal
from app.enums import OperationType, UserRole
from app.main import app
from app.models import (
    Customer, Operation, Product, QualityPhenomenon, QualityRejectionDaily,
    RouteOperation, RouteVersion, User,
)
from app.services.quality_import import upsert_phenomenon


def _user(db, username, role):
    row = User(
        username=username,
        password_hash=hash_password("SalvageTest123!"),
        full_name=username.title(),
        role=role,
        is_active=True,
        must_change_password=False,
    )
    db.add(row)
    db.flush()
    return row


def _headers(client, username):
    response = client.post("/api/auth/login", json={"username": username, "password": "SalvageTest123!"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _seed():
    with SessionLocal() as db:
        customer = Customer(code="SAL-C", name="Salvage Customer")
        db.add(customer)
        db.flush()
        product = Product(code="SAL-P", name="Salvage Test Part", customer_id=customer.id, plant="2020")
        db.add(product)
        db.flush()
        operation = Operation(code="SAL-OP", name="Machining", operation_type=OperationType.INTERNAL)
        db.add(operation)
        db.flush()
        route = RouteVersion(product_id=product.id, revision_no=0, effective_from=date(2026, 1, 1), is_active=True)
        db.add(route)
        db.flush()
        route_operation = RouteOperation(route_version_id=route.id, operation_id=operation.id, sequence_no=10)
        db.add(route_operation)
        db.flush()
        phenomenon = upsert_phenomenon(db, "Salvage Test Defect", default_team="Operation")
        rejection = QualityRejectionDaily(
            record_key="salvage-test-record",
            rejection_date=date(2026, 10, 1),
            shift="A",
            product_id=product.id,
            plant="2020",
            detection_route_operation_id=route_operation.id,
            phenomenon_id=phenomenon.id,
            reject_qty=Decimal("100"),
            denominator_qty=Decimal("2000"),
            denominator_source="DISP_DONE",
            ppm=Decimal("50000"),
        )
        db.add(rejection)
        _user(db, "salvage-production", UserRole.PRODUCTION)
        _user(db, "salvage-quality", UserRole.QUALITY)
        _user(db, "salvage-admin", UserRole.ADMIN)
        db.commit()
        return rejection.id




def test_salvage_dropdown_options_include_historical_plant_assignments():
    rejection_id = _seed()
    with SessionLocal() as db:
        rejection = db.get(QualityRejectionDaily, rejection_id)
        product = db.get(Product, rejection.product_id)
        rejection.plant = "OLD-PLANT"
        product.plant = "NEW-PLANT"
        product_id = product.id
        db.commit()

    client = TestClient(app)
    production = _headers(client, "salvage-production")

    plants = client.get("/api/quality/salvage/plants", headers=production)
    assert plants.status_code == 200, plants.text
    assert "OLD-PLANT" in plants.json()
    assert "NEW-PLANT" in plants.json()

    historical_parts = client.get(
        "/api/quality/salvage/parts",
        params={"plant": "OLD-PLANT"},
        headers=production,
    )
    assert historical_parts.status_code == 200, historical_parts.text
    assert any(row["id"] == product_id and row["code"] == "SAL-P" for row in historical_parts.json())

    current_parts = client.get(
        "/api/quality/salvage/parts",
        params={"plant": "NEW-PLANT"},
        headers=production,
    )
    assert current_parts.status_code == 200, current_parts.text
    assert any(row["id"] == product_id for row in current_parts.json())


def test_salvage_rejection_filters_use_effective_plant_and_exact_product():
    rejection_id = _seed()
    with SessionLocal() as db:
        rejection = db.get(QualityRejectionDaily, rejection_id)
        rejection.plant = None
        product_id = rejection.product_id
        db.commit()

    client = TestClient(app)
    production = _headers(client, "salvage-production")
    response = client.get(
        "/api/quality/salvage/rejections",
        params={
            "from_date": "2026-10-01",
            "to_date": "2026-10-01",
            "plant": "2020",
            "product_id": product_id,
        },
        headers=production,
    )
    assert response.status_code == 200, response.text
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["product_id"] == product_id
    assert rows[0]["plant"] == "2020"

    no_match = client.get(
        "/api/quality/salvage/rejections",
        params={
            "from_date": "2026-10-01",
            "to_date": "2026-10-01",
            "plant": "2020",
            "product_id": product_id + 999999,
        },
        headers=production,
    )
    assert no_match.status_code == 200, no_match.text
    assert no_match.json() == []


def test_pending_salvage_does_not_change_rejection_reports_but_quality_approval_does():
    rejection_id = _seed()
    client = TestClient(app)
    production = _headers(client, "salvage-production")
    quality = _headers(client, "salvage-quality")

    submitted = client.post(
        "/api/quality/salvage/requests",
        headers=production,
        json={"rejection_id": rejection_id, "salvage_qty": 25, "reason": "Reworked and accepted after dimensional re-inspection."},
    )
    assert submitted.status_code == 200, submitted.text
    request_id = submitted.json()["id"]

    daily = client.get("/api/quality/daily?from_date=2026-10-01&to_date=2026-10-01", headers=production)
    assert daily.status_code == 200, daily.text
    assert daily.json()[0]["reject_qty"] == 100.0
    assert daily.json()[0]["approved_salvage_qty"] == 0.0

    report = client.get("/api/quality/report-pack?from_date=2026-10-01&to_date=2026-10-01", headers=production)
    assert report.status_code == 200, report.text
    assert report.json()["summary"]["reject_qty"] == 100.0

    approved = client.post(
        "/api/quality/salvage/requests/" + str(request_id) + "/review",
        headers=quality,
        json={"action": "APPROVE", "note": "Inspection evidence verified."},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["net_reject_qty"] == 75.0

    daily = client.get("/api/quality/daily?from_date=2026-10-01&to_date=2026-10-01", headers=quality)
    assert daily.status_code == 200, daily.text
    row = daily.json()[0]
    assert row["original_reject_qty"] == 100.0
    assert row["approved_salvage_qty"] == 25.0
    assert row["reject_qty"] == 75.0
    assert row["ppm"] == 37500.0

    report = client.get("/api/quality/report-pack?from_date=2026-10-01&to_date=2026-10-01", headers=quality)
    assert report.status_code == 200, report.text
    assert report.json()["summary"]["reject_qty"] == 75.0


def test_salvage_request_cannot_exceed_remaining_rejection_or_duplicate_pending_request():
    rejection_id = _seed()
    client = TestClient(app)
    production = _headers(client, "salvage-production")
    payload = {"rejection_id": rejection_id, "salvage_qty": 60, "reason": "Verified rework and acceptance evidence."}
    first = client.post("/api/quality/salvage/requests", headers=production, json=payload)
    assert first.status_code == 200, first.text

    duplicate = client.post("/api/quality/salvage/requests", headers=production, json=payload)
    assert duplicate.status_code == 409

    too_much = client.post(
        "/api/quality/salvage/requests",
        headers=production,
        json={"rejection_id": rejection_id, "salvage_qty": 101, "reason": "Verified rework and acceptance evidence."},
    )
    assert too_much.status_code == 422


def test_requester_cannot_approve_own_request_and_rejection_requires_reason():
    rejection_id = _seed()
    client = TestClient(app)
    admin = _headers(client, "salvage-admin")
    production = _headers(client, "salvage-production")
    quality = _headers(client, "salvage-quality")

    own = client.post(
        "/api/quality/salvage/requests",
        headers=admin,
        json={"rejection_id": rejection_id, "salvage_qty": 10, "reason": "Admin raised for test separation of duties."},
    )
    assert own.status_code == 200
    denied = client.post(
        "/api/quality/salvage/requests/" + str(own.json()["id"]) + "/review",
        headers=admin,
        json={"action": "APPROVE"},
    )
    assert denied.status_code == 403

    rejection_id_2 = _seed_second_rejection()
    request = client.post(
        "/api/quality/salvage/requests",
        headers=production,
        json={"rejection_id": rejection_id_2, "salvage_qty": 5, "reason": "Rework passed inspection and is accepted."},
    )
    assert request.status_code == 200
    rejected = client.post(
        "/api/quality/salvage/requests/" + str(request.json()["id"]) + "/review",
        headers=quality,
        json={"action": "REJECT", "note": " "},
    )
    assert rejected.status_code == 422
    rejected = client.post(
        "/api/quality/salvage/requests/" + str(request.json()["id"]) + "/review",
        headers=quality,
        json={"action": "REJECT", "note": "Inspection evidence was insufficient."},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "REJECTED"


def _seed_second_rejection():
    with SessionLocal() as db:
        product = db.scalar(select(Product).where(Product.code == "SAL-P"))
        phenomenon = db.scalar(select(QualityPhenomenon).where(QualityPhenomenon.name == "Salvage Test Defect"))
        route = db.scalar(select(RouteVersion).where(RouteVersion.product_id == product.id))
        route_operation = db.scalar(select(RouteOperation).where(RouteOperation.route_version_id == route.id))
        row = QualityRejectionDaily(
            record_key="salvage-test-record-2",
            rejection_date=date(2026, 10, 2),
            shift="B",
            product_id=product.id,
            plant="2020",
            detection_route_operation_id=route_operation.id,
            phenomenon_id=phenomenon.id,
            reject_qty=Decimal("20"),
            denominator_qty=Decimal("500"),
            denominator_source="DISP_DONE",
            ppm=Decimal("40000"),
        )
        db.add(row)
        db.commit()
        return row.id
