from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import Customer, DailyMIS, DailyRequirement, Product
from test_governance_security import headers


def test_monthly_analytics_uses_revised_dispatch_requirement_for_plan():
    with SessionLocal() as db:
        customer = Customer(code="HMCL_TEST", name="HMCL")
        db.add(customer); db.flush()
        revised = Product(code="HMCL_REVISED", name="HMCL Revised Part", customer_id=customer.id)
        baseline = Product(code="HMCL_BASELINE", name="HMCL Baseline Part", customer_id=customer.id)
        db.add_all([revised, baseline]); db.flush()

        db.add_all([
            DailyMIS(
                mis_date=date(2026, 5, 2), product_id=revised.id,
                plan_qty=Decimal("0"), actual_qty=Decimal("80"),
                sales_price=Decimal("10"), plan_sales=Decimal("0"),
                actual_sales=Decimal("800"),
            ),
            DailyMIS(
                mis_date=date(2026, 5, 2), product_id=baseline.id,
                plan_qty=Decimal("20"), actual_qty=Decimal("15"),
                sales_price=Decimal("5"), plan_sales=Decimal("100"),
                actual_sales=Decimal("75"),
            ),
            DailyRequirement(
                req_date=date(2026, 5, 2), product_id=revised.id,
                route_operation_id=None,
                baseline_plan_qty=Decimal("0"),
                revised_plan_qty=Decimal("100"),
                is_frozen=True,
            ),
        ])
        db.commit()
        customer_id = customer.id

    client = TestClient(app)
    h = headers(client)
    response = client.get(
        f"/api/analytics/monthly?end_month=2026-05-01&months=1&customer_id={customer_id}",
        headers=h,
    )
    assert response.status_code == 200, response.text
    rows = response.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["month"] == "2026-05"
    assert row["plan_qty"] == 120
    assert row["actual_qty"] == 95
    assert row["plan_sales"] == 1100
    assert row["actual_sales"] == 875
    assert row["sales_gap"] == -225
    assert row["achievement"] == 875 / 1100
