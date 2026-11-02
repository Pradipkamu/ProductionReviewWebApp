from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import Customer, Product


def auth_headers(client: TestClient):
    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "ChangeMe123!"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_backdated_value_addition_can_be_corrected_and_keeps_audit_history():
    with SessionLocal() as db:
        customer = Customer(code="VA-C", name="Value Addition Customer")
        db.add(customer)
        db.flush()
        product = Product(
            code="VA-P",
            name="Value Addition Part",
            customer_id=customer.id,
            value_addition_per_piece=Decimal("10.000"),
        )
        db.add(product)
        db.commit()
        product_id = product.id

    client = TestClient(app)
    headers = auth_headers(client)
    effective_date = "2026-01-15"

    first = client.post(
        f"/api/masters/products/{product_id}/value-addition-revisions",
        headers=headers,
        json={
            "effective_from": effective_date,
            "value_addition_per_piece": "12.500",
            "reason": "Backdated value correction",
        },
    )
    assert first.status_code == 200, first.text

    correction = client.post(
        f"/api/masters/products/{product_id}/value-addition-revisions",
        headers=headers,
        json={
            "effective_from": effective_date,
            "value_addition_per_piece": "13.750",
            "reason": "Corrected approved value",
        },
    )
    assert correction.status_code == 200, correction.text

    history = client.get(
        f"/api/masters/products/{product_id}/value-addition-history",
        headers=headers,
    )
    assert history.status_code == 200, history.text
    rows = [row for row in history.json() if row["effective_from"] == effective_date]
    assert len(rows) == 2
    assert [row["value_addition_per_piece"] for row in rows] == [13.75, 12.5]

    with SessionLocal() as db:
        refreshed = db.get(Product, product_id)
        assert Decimal(str(refreshed.value_addition_per_piece)) == Decimal("13.750")
