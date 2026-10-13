"""Historical route operations remain queryable after dropdown deduplication."""
from datetime import date

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import Product, Operation, RouteVersion, RouteOperation, DailyRequirement
from app.enums import OperationType
from test_governance_security import headers


def test_capacity_exposes_route_revision_metadata_without_deleting_old_operations():
    with SessionLocal() as db:
        p = Product(code="ROUTE-DUP-P", name="Route Duplicate Part")
        operation = Operation(code="ROUTE-DUP-HONE", name="Hone", operation_type=OperationType.INTERNAL)
        db.add_all([p, operation])
        db.flush()
        old = RouteVersion(product_id=p.id, revision_no=1, effective_from=date(2026, 9, 1),
                           effective_to=date(2026, 9, 30), is_active=False)
        new = RouteVersion(product_id=p.id, revision_no=2, effective_from=date(2026, 10, 1),
                           is_active=True)
        db.add_all([old, new])
        db.flush()
        o1 = RouteOperation(route_version_id=old.id, operation_id=operation.id, sequence_no=70)
        o2 = RouteOperation(route_version_id=new.id, operation_id=operation.id, sequence_no=70)
        db.add_all([o1, o2])
        db.flush()
        db.add(DailyRequirement(req_date=date(2026, 10, 2), product_id=p.id,
                                route_operation_id=o1.id, revised_plan_qty=10))
        db.add(DailyRequirement(req_date=date(2026, 10, 3), product_id=p.id,
                                route_operation_id=o2.id, revised_plan_qty=20))
        product_id = p.id
        db.commit()
    client = TestClient(app)
    response = client.get(f"/api/capacity/plan?product_id={product_id}&month=2026-10-01",
                          headers=headers(client))
    assert response.status_code == 200, response.text
    rows = [o for o in response.json()["operations"] if o["operation"] == "Hone"]
    assert len(rows) == 2  # historical data preserved; client selects latest logical route
    assert {o["route_revision_no"] for o in rows} == {1, 2}
    assert sum(o["schedule_qty"] for o in rows) == 30
