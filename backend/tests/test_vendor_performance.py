from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.enums import OperationType
from app.main import app
from app.models import (
    Operation, Product, RouteOperation, RouteVersion, Vendor, VendorMovement,
)
from test_governance_security import headers


def _seed_vendor_ledger():
    with SessionLocal() as db:
        product = Product(code="VPERF-P1", name="Vendor Performance Part", plant="Plant 1")
        operation = Operation(
            code="VPERF-OP", name="Heat Treatment",
            operation_type=OperationType.VENDOR_PROCESS,
        )
        vendor_a = Vendor(code="VPERF-A", name="Vendor A")
        vendor_b = Vendor(code="VPERF-B", name="Vendor B")
        db.add_all([product, operation, vendor_a, vendor_b])
        db.flush()

        route = RouteVersion(
            product_id=product.id, revision_no=1,
            effective_from=date(2026, 1, 1), is_active=True,
        )
        db.add(route)
        db.flush()
        route_operation = RouteOperation(
            route_version_id=route.id, operation_id=operation.id, sequence_no=10,
        )
        db.add(route_operation)
        db.flush()

        db.add_all([
            VendorMovement(
                product_id=product.id, route_operation_id=route_operation.id,
                vendor_id=vendor_a.id, outward_date=date(2026, 11, 1),
                outward_qty=Decimal("100"), receipt_qty=Decimal("20"),
                reject_qty=Decimal("5"), expected_return_date=date(2026, 11, 4),
            ),
            VendorMovement(
                product_id=product.id, route_operation_id=route_operation.id,
                vendor_id=vendor_a.id, outward_date=date(2026, 10, 1),
                outward_qty=Decimal("50"), receipt_qty=Decimal("0"),
                expected_return_date=date(2026, 12, 1),
            ),
            VendorMovement(
                product_id=product.id, route_operation_id=route_operation.id,
                vendor_id=vendor_b.id, outward_date=date(2026, 10, 20),
                outward_qty=Decimal("10"), receipt_qty=Decimal("10"),
                expected_return_date=date(2026, 11, 4),
            ),
        ])
        db.commit()


def test_vendor_performance_reconciles_pending_overdue_and_aging():
    _seed_vendor_ledger()
    client = TestClient(app)
    response = client.get(
        "/api/vendor/performance?as_of=2026-11-05",
        headers=headers(client),
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["summary"] == {
        "open_lots": 2,
        "pending_qty": 130.0,
        "overdue_lots": 1,
        "overdue_qty": 80.0,
        "vendors_with_pending": 1,
    }
    buckets = {row["bucket"]: row["pending_qty"] for row in body["aging_buckets"]}
    assert buckets["0-7 days"] == 80.0
    assert buckets["Over 30 days"] == 50.0
    assert buckets["8-15 days"] == 0.0
    assert buckets["16-30 days"] == 0.0

    vendor = body["vendors"][0]
    assert vendor["vendor"] == "Vendor A"
    assert vendor["open_lots"] == 2
    assert vendor["pending_qty"] == 130.0
    assert vendor["overdue_lots"] == 1
    assert vendor["overdue_qty"] == 80.0
    assert vendor["oldest_age_days"] == 35


def test_vendor_performance_is_as_of_date_stable():
    _seed_vendor_ledger()
    client = TestClient(app)
    response = client.get(
        "/api/vendor/performance?as_of=2026-11-03",
        headers=headers(client),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    # The first lot is not overdue on Nov 3 because its expected return is Nov 4.
    assert body["summary"]["overdue_lots"] == 0
    assert body["summary"]["overdue_qty"] == 0.0
    assert body["summary"]["pending_qty"] == 130.0
