from datetime import date
from decimal import Decimal
from pathlib import Path
import struct
import zlib
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.enums import OperationType
from app.models import (
    Customer, Operation, Product, QualityRejectionDaily, RouteOperation, RouteVersion,
)
from app.services.quality_import import upsert_phenomenon


def _png_1x1(red: int, green: int, blue: int) -> bytes:
    signature = b"\x89PNG\r\n\x1a\n"

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    pixels = zlib.compress(bytes((0, red, green, blue)))
    return signature + chunk(b"IHDR", header) + chunk(b"IDAT", pixels) + chunk(b"IEND", b"")


def _photo_rejection_id() -> int:
    with SessionLocal() as db:
        customer = Customer(code="PHOTO-C", name="Photo Customer")
        db.add(customer)
        db.flush()
        product = Product(code="PHOTO-P", name="Photo Test Part", customer_id=customer.id, plant="2020")
        db.add(product)
        db.flush()
        operation = Operation(code="PHOTO-OP", name="Photo Inspection", operation_type=OperationType.INTERNAL)
        db.add(operation)
        db.flush()
        route = RouteVersion(product_id=product.id, revision_no=0, effective_from=date(2026, 1, 1), is_active=True)
        db.add(route)
        db.flush()
        route_operation = RouteOperation(
            route_version_id=route.id, operation_id=operation.id, sequence_no=10,
            standard_yield=Decimal("1"),
        )
        db.add(route_operation)
        db.flush()
        phenomenon = upsert_phenomenon(db, "PHOTO DEFECT", default_team="Quality")
        rejection = QualityRejectionDaily(
            record_key="photo-attachment-test",
            rejection_date=date(2026, 9, 30),
            shift="A",
            product_id=product.id,
            plant="2020",
            detection_route_operation_id=route_operation.id,
            phenomenon_id=phenomenon.id,
            reject_qty=Decimal("1"),
            denominator_source="DISP_DONE",
            source="MANUAL",
        )
        db.add(rejection)
        db.commit()
        return rejection.id


def test_rejection_photos_are_authenticated_listed_downloaded_and_limited(tmp_path, monkeypatch):
    from app.api import quality as quality_api
    from app.main import app

    monkeypatch.setattr(
        quality_api,
        "get_settings",
        lambda: SimpleNamespace(attachments_dir=str(tmp_path), office_max_uncompressed_mb=128),
    )
    rejection_id = _photo_rejection_id()
    client = TestClient(app)
    login = client.post("/api/auth/login", json={"username": "admin", "password": "ChangeMe123!"})
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    uploaded = []
    for index in range(5):
        response = client.post(
            f"/api/quality/daily/{rejection_id}/attachments",
            headers=headers,
            files={"file": (f"defect-{index}.png", _png_1x1(index * 40, 20, 10), "image/png")},
        )
        assert response.status_code == 200, response.text
        uploaded.append(response.json())

    sixth = client.post(
        f"/api/quality/daily/{rejection_id}/attachments",
        headers=headers,
        files={"file": ("defect-six.png", _png_1x1(255, 255, 255), "image/png")},
    )
    assert sixth.status_code == 409

    listing = client.get(f"/api/quality/daily/{rejection_id}/attachments", headers=headers)
    assert listing.status_code == 200
    assert len(listing.json()) == 5

    download = client.get(
        f"/api/quality/daily/{rejection_id}/attachments/{uploaded[0]['id']}",
        headers=headers,
    )
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("image/png")
    assert download.content == _png_1x1(0, 20, 10)

    unauthorized = client.get(f"/api/quality/daily/{rejection_id}/attachments")
    assert unauthorized.status_code == 401
