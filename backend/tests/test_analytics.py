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


def test_forecast_uses_reported_working_days_and_plant_calendar():
    from app.models import WorkingCalendar

    with SessionLocal() as db:
        product = Product(code="FC-P1", name="Forecast Part", plant="Forecast Plant")
        db.add(product)
        db.flush()
        db.add(WorkingCalendar(
            work_date=date(2026, 5, 3), plant="Forecast Plant",
            is_working_day=False, holiday_name="Weekly off",
        ))
        db.add_all([
            DailyMIS(
                mis_date=date(2026, 5, 1), product_id=product.id,
                plan_qty=Decimal("100"), actual_qty=Decimal("50"),
                sales_price=Decimal("1"), plan_sales=Decimal("100"),
                actual_sales=Decimal("50"),
            ),
            DailyMIS(
                mis_date=date(2026, 5, 5), product_id=product.id,
                plan_qty=Decimal("100"), actual_qty=Decimal("70"),
                sales_price=Decimal("1"), plan_sales=Decimal("100"),
                actual_sales=Decimal("70"),
            ),
        ])
        db.add_all([
            DailyRequirement(
                req_date=date(2026, 5, 1), product_id=product.id,
                route_operation_id=None, baseline_plan_qty=Decimal("100"),
                revised_plan_qty=Decimal("100"),
            ),
            DailyRequirement(
                req_date=date(2026, 5, 5), product_id=product.id,
                route_operation_id=None, baseline_plan_qty=Decimal("100"),
                revised_plan_qty=Decimal("100"),
            ),
        ])
        db.commit()
        product_id = product.id

    client = TestClient(app)
    h = headers(client)
    response = client.get(
        f"/api/analytics/forecast?as_of=2026-05-05&product_id={product_id}",
        headers=h,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["summary"]["products"] == 1
    assert body["summary"]["products_with_actuals"] == 1
    item = body["products_detail"][0]
    assert item["actual_qty"] == 120.0
    assert item["reported_working_days"] == 2
    assert item["elapsed_working_days"] == 4
    assert item["coverage_pct"] == 50.0
    assert item["run_rate_per_reported_working_day"] == 60.0
    assert item["plan_qty"] == 200.0
    assert item["projected_month_end_qty"] == 1680.0
