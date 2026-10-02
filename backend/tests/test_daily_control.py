from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.enums import OperationType, SourceType
from app.main import app
from app.models import (
    DailyMIS, DailyRequirement, Operation, ProcessDailySummary, ProcessFlowStage,
    ProcessFlowVersion, Product, RouteOperation, RouteVersion,
)


def _headers(client: TestClient) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"username": "admin", "password": "ChangeMe123!"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _seed_planned_product() -> tuple[int, int]:
    with SessionLocal() as db:
        product = Product(code="CTRL-P1", name="Control Product", plant="Plant 1", product_group="Machining")
        operation = Operation(code="CTRL-OP10", name="Machining OP10", operation_type=OperationType.INTERNAL)
        db.add_all([product, operation]); db.flush()
        route = RouteVersion(product_id=product.id, revision_no=1, effective_from=date(2026, 10, 1), is_active=True)
        db.add(route); db.flush()
        route_operation = RouteOperation(route_version_id=route.id, operation_id=operation.id, sequence_no=10)
        db.add(route_operation); db.flush()
        flow = ProcessFlowVersion(
            product_id=product.id, route_version_id=route.id, effective_from=date(2026, 10, 1),
            revision_no=1, definition_sha256="a" * 64, source_document="test.xlsx", reason="Test flow",
        )
        db.add(flow); db.flush()
        db.add(ProcessFlowStage(
            flow_id=flow.id, code="OP10", name="Machining OP10", route_operation_id=route_operation.id,
            source_column="AA", role="INTERNAL", branch="MAIN", variant="", vendor_name="",
            predecessors_json="[]", alias_of="", is_active=True, parent_dispatch=False, sequence_no=10,
        ))
        db.add_all([
            DailyRequirement(req_date=date(2026, 10, 2), product_id=product.id, route_operation_id=None,
                             baseline_plan_qty=Decimal("100"), revised_plan_qty=Decimal("100")),
            DailyRequirement(req_date=date(2026, 10, 2), product_id=product.id, route_operation_id=route_operation.id,
                             baseline_plan_qty=Decimal("120"), revised_plan_qty=Decimal("120")),
        ])
        db.commit()
        return product.id, route_operation.id


def test_daily_control_separates_missing_upload_from_reported_zero():
    product_id, route_operation_id = _seed_planned_product()
    client = TestClient(app)
    headers = _headers(client)

    missing = client.get("/api/dashboard/daily-control?as_of=2026-10-02", headers=headers)
    assert missing.status_code == 200, missing.text
    body = missing.json()
    assert body["workflow"]["schedule"]["status"] == "READY"
    assert body["workflow"]["upload"]["status"] == "NOT STARTED"
    assert body["workflow"]["upload"]["expected_rows"] == 2
    assert {x["kind"] for x in body["alerts"]} >= {"missing_dispatch_actual", "missing_stage_actual"}

    with SessionLocal() as db:
        db.add(DailyMIS(
            mis_date=date(2026, 10, 2), product_id=product_id, plan_qty=Decimal("100"),
            actual_qty=Decimal("0"), sales_price=Decimal("0"), plan_sales=Decimal("0"),
            actual_sales=Decimal("0"), source=SourceType.EXCEL,
        ))
        db.add(ProcessDailySummary(
            summary_date=date(2026, 10, 2), product_id=product_id, route_operation_id=route_operation_id,
            plan_qty=Decimal("120"), actual_qty=Decimal("0"), source=SourceType.EXCEL,
        ))
        db.commit()

    reported = client.get("/api/dashboard/daily-control?as_of=2026-10-02", headers=headers).json()
    assert reported["workflow"]["upload"]["status"] == "COMPLETE"
    kinds = {x["kind"] for x in reported["alerts"]}
    assert "missing_dispatch_actual" not in kinds
    assert "missing_stage_actual" not in kinds
    assert {"zero_dispatch_actual", "zero_stage_actual", "price_missing"} <= kinds


def test_daily_control_reports_missing_process_flow_as_readiness_blocker():
    with SessionLocal() as db:
        product = Product(code="NO-FLOW", name="No Flow Product", plant="Plant 1")
        db.add(product); db.flush()
        db.add(DailyRequirement(
            req_date=date(2026, 10, 2), product_id=product.id, route_operation_id=None,
            baseline_plan_qty=Decimal("50"), revised_plan_qty=Decimal("50"),
        ))
        db.commit()

    client = TestClient(app)
    body = client.get("/api/dashboard/daily-control?as_of=2026-10-02", headers=_headers(client)).json()
    assert body["workflow"]["schedule"]["status"] == "ATTENTION"
    assert any(x["kind"] == "process_flow_missing" and x["product"] == "No Flow Product" for x in body["alerts"])
