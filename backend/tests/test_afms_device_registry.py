from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import hash_password
from app.db import SessionLocal
from app.enums import UserRole
from app.main import app
from app.models import AFMSDevice, Machine, User
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
