from datetime import date, datetime
import json
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import hash_password
from app.db import SessionLocal
from app.enums import UserRole
from app.main import app
from app.models import (AFMSDevice, AFMSTelemetryEvent, Machine, User, Product, RouteVersion, RouteOperation, Operation, OperationMachineMap, StandardCycleTime, Personnel)
from test_governance_security import headers


def test_afms_device_registration_is_bound_to_prw_machine_and_secret_is_one_time():
    with SessionLocal() as db:
        machine = Machine(code='AFMS-M01', name='AFMS Test Machine', plant='Plant 2020', is_active=True)
        db.add(machine); db.commit(); machine_id = machine.id
    client = TestClient(app)
    admin_headers = headers(client)
    payload = {'machine_id': machine_id, 'device_uid': 'ESP32-AFMS-0001', 'device_name': 'M01 Controller', 'device_role': 'MAIN_CONTROLLER', 'hardware_model': 'ESP32-S3', 'firmware_version': '1.0.0', 'protocol_version': '1.0'}
    created = client.post('/api/afms/devices', headers=admin_headers, json=payload)
    assert created.status_code == 201, created.text
    result = created.json()
    assert result['device']['machine_id'] == machine_id
    assert result['device']['machine_number'] == 'AFMS-M01'
    assert result['device']['machine_name'] == 'AFMS Test Machine'
    secret = result['provisioning_secret']
    assert secret.startswith('afms_')
    assert 'credential_hash' not in result['device']
    listed = client.get('/api/afms/devices', headers=admin_headers)
    assert listed.status_code == 200
    assert listed.json()[0]['device_uid'] == payload['device_uid']
    assert secret not in listed.text
    duplicate_uid = client.post('/api/afms/devices', headers=admin_headers, json={**payload, 'machine_id': machine_id, 'device_uid': 'ESP32-AFMS-0001'})
    assert duplicate_uid.status_code == 409
    duplicate_machine = client.post('/api/afms/devices', headers=admin_headers, json={**payload, 'device_uid': 'ESP32-AFMS-0002'})
    assert duplicate_machine.status_code == 409
    with SessionLocal() as db:
        device = db.scalar(select(AFMSDevice).where(AFMSDevice.device_uid == payload['device_uid']))
        assert device is not None
        assert device.credential_hash != secret
        assert len(device.credential_hash) == 64


def test_non_admin_cannot_register_afms_device():
    with SessionLocal() as db:
        machine = Machine(code='AFMS-M02', name='AFMS Restricted Machine', is_active=True)
        db.add(machine)
        db.add(User(username='afms_viewer', full_name='AFMS Viewer', role=UserRole.VIEW_ONLY, password_hash=hash_password('ViewerPass123!'), must_change_password=False))
        db.commit(); machine_id = machine.id
    client = TestClient(app)
    viewer_headers = headers(client, 'afms_viewer', 'ViewerPass123!')
    response = client.post('/api/afms/devices', headers=viewer_headers, json={'machine_id': machine_id, 'device_uid': 'ESP32-AFMS-VIEW-01'})
    assert response.status_code == 403



def test_afms_live_oee_uses_shift_counters_and_prw_cycle_master():
    with SessionLocal() as db:
        machine = Machine(code="AFMS-OEE-M01", name="AFMS OEE Test Machine", is_active=True)
        db.add(machine)
        db.flush()
        device = AFMSDevice(
            machine_id=machine.id, device_uid="ESP32-AFMS-OEE-01",
            credential_hash="b" * 64, is_active=True,
        )
        product = Product(code="AFMS-PART-01", name="AFMS Test Part", is_active=True)
        person = Personnel(
            first_name="OEE", last_name="Operator", full_name="OEE Operator",
            normalized_name="oee operator", is_active=True,
        )
        operation = Operation(code="AFMS-OP-01", name="AFMS Test Operation", is_active=True)
        db.add_all([device, product, person, operation])
        db.flush()
        route_version = RouteVersion(
            product_id=product.id, revision_no=1, effective_from=date(2026, 1, 1),
            is_active=True,
        )
        db.add(route_version)
        db.flush()
        route = RouteOperation(
            route_version_id=route_version.id, operation_id=operation.id,
            sequence_no=1, is_enabled=True,
        )
        db.add(route)
        db.flush()
        db.add(OperationMachineMap(
            route_operation_id=route.id, machine_id=machine.id,
            effective_from=date(2026, 1, 1), is_active=True,
        ))
        db.add(StandardCycleTime(
            route_operation_id=route.id, machine_id=machine.id,
            effective_from=date(2026, 1, 1), ideal_cycle_time_sec=Decimal("240"),
            cavities=1, pieces_per_cycle=1,
        ))
        payload = {
            "shiftId": 1, "partCode": product.code, "partName": product.name,
            "operatorId": person.id, "operatorName": person.full_name,
            "shiftDurationMin": 480, "plannedBreakMin": 30,
            "shiftProductionCount": 100, "shiftRejectCount": 5,
            "shiftGoodCount": 95, "shiftRunSeconds": 420 * 60,
            "shiftIdleSeconds": 0, "shiftDowntimeSeconds": 30 * 60,
            "standardCycleMs": 240000, "cycleTimeMs": 240000,
        }
        db.add(AFMSTelemetryEvent(
            device_id=device.id, event_id="AFMS-OEE-TELEMETRY-1",
            event_type="STATUS", event_timestamp=datetime(2026, 11, 20, 10, 0, 0),
            sequence=1, payload_sha256="c" * 64, payload_json=json.dumps(payload),
        ))
        db.commit()
        machine_id = machine.id

    client = TestClient(app)
    response = client.get(
        "/api/afms/oee/live",
        params={"machine_id": machine_id, "production_date": "2026-11-20", "shift": "A"},
        headers=headers(client),
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "READY"
    assert result["total_count"] == 100
    assert result["good_count"] == 95
    assert result["reject_count"] == 5
    assert result["operator_name"] == "OEE Operator"
    assert result["ideal_cycle_time_sec"] == 240.0
    assert round(result["oee"]["availability"], 4) == round(420 / 450, 4)
    assert round(result["oee"]["quality"], 4) == round(95 / 100, 4)
    assert result["collection_mode"] == "LIVE_PREVIEW_ONLY"


def test_afms_live_oee_requires_shift_scoped_firmware_metrics():
    with SessionLocal() as db:
        machine = Machine(code="AFMS-OEE-M02", name="AFMS OEE Legacy Machine", is_active=True)
        db.add(machine)
        db.flush()
        device = AFMSDevice(
            machine_id=machine.id, device_uid="ESP32-AFMS-OEE-02",
            credential_hash="d" * 64, is_active=True,
        )
        db.add(device)
        db.flush()
        db.add(AFMSTelemetryEvent(
            device_id=device.id, event_id="AFMS-OEE-LEGACY-1",
            event_type="STATUS", event_timestamp=datetime(2026, 11, 20, 10, 0, 0),
            sequence=1, payload_sha256="e" * 64, payload_json=json.dumps({"shiftId": 1}),
        ))
        db.commit()
        machine_id = machine.id

    client = TestClient(app)
    response = client.get(
        "/api/afms/oee/live",
        params={"machine_id": machine_id, "production_date": "2026-11-20", "shift": "A"},
        headers=headers(client),
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "FIRMWARE_UPDATE_REQUIRED"
