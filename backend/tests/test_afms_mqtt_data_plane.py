import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import AFMSDevice, Machine
from app.services import mqtt_data_plane as mqtt_service


def _device(uid="ESP32-MQTT-TEST", *, active=True, machine_active=True):
    with SessionLocal() as db:
        machine = Machine(code="MQTT-M01", name="MQTT Test Machine", is_active=machine_active)
        db.add(machine)
        db.flush()
        device = AFMSDevice(
            machine_id=machine.id,
            device_uid=uid,
            credential_hash="a" * 64,
            is_active=active,
        )
        db.add(device)
        db.commit()
        return device.id


class _Message:
    def __init__(self, uid, kind="heartbeat", payload=None):
        self.topic = f"production/v1/devices/{uid}/{kind}"
        self.payload = json.dumps(payload or {"status": "ok"}).encode()


def test_heartbeat_updates_last_seen_for_active_mapped_device():
    device_id = _device()
    mqtt_service._handle_message(None, None, _Message("ESP32-MQTT-TEST"))
    with SessionLocal() as db:
        device = db.get(AFMSDevice, device_id)
        assert device.last_seen_at is not None
        assert datetime.utcnow() - device.last_seen_at < timedelta(seconds=10)


def test_heartbeat_does_not_update_disabled_device():
    device_id = _device(active=False)
    mqtt_service._handle_message(None, None, _Message("ESP32-MQTT-TEST"))
    with SessionLocal() as db:
        assert db.get(AFMSDevice, device_id).last_seen_at is None


def test_heartbeat_does_not_update_device_mapped_to_inactive_machine():
    device_id = _device(machine_active=False)
    mqtt_service._handle_message(None, None, _Message("ESP32-MQTT-TEST"))
    with SessionLocal() as db:
        assert db.get(AFMSDevice, device_id).last_seen_at is None


def test_command_publish_rejects_unregistered_or_disabled_device():
    _device(active=False)
    with pytest.raises(mqtt_service.MQTTDataPlaneError, match="unknown, disabled"):
        mqtt_service.publish_device_command("ESP32-MQTT-TEST", {"command": "PING"})


def test_command_publish_uses_device_specific_topic(monkeypatch):
    _device()

    class Info:
        rc = 0
        def wait_for_publish(self, timeout):
            return None
        def is_published(self):
            return True

    class Client:
        def is_connected(self):
            return True
        def publish(self, topic, body, qos):
            assert topic == "production/v1/devices/ESP32-MQTT-TEST/commands"
            assert json.loads(body) == {"command": "PING"}
            assert qos == 1
            return Info()

    monkeypatch.setattr(mqtt_service, "_client", Client())
    mqtt_service.publish_device_command("ESP32-MQTT-TEST", {"command": "PING"})
