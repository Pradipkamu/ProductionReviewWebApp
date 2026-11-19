import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import AFMSDevice, AFMSTelemetryEvent, Machine
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


def _telemetry(machine_id="MQTT-M01", machine_name="MQTT Test Machine", **changes):
    payload = {
        "schemaVersion": 1,
        "eventId": "MQTT-M01-0-1234-1",
        "eventType": "STATUS",
        "timestamp": "2026-11-19T10:00:00Z",
        "machineId": machine_id,
        "machineName": machine_name,
        "status": "SETUP",
        "productionCount": 0,
        "rejectCount": 0,
        "goodCount": 0,
        "unmatchedRejectPulses": 0,
        "cycleTimeMs": 0,
        "lossCode": 0,
        "lossName": "",
        "lossDurationSeconds": 0,
        "shiftId": 0,
        "operatorId": 0,
        "operatorName": "",
        "standardCycleMs": 0,
        "shiftDurationMin": 480,
        "plannedBreakMin": 0,
        "partCode": "",
        "partName": "",
        "alarmActive": False,
        "idleSeconds": 0,
        "runSeconds": 0,
        "downtimeSeconds": 0,
        "availabilityPermille": 0,
        "performancePermille": 0,
        "qualityPermille": 0,
        "oeePermille": 0,
        "wifiRssi": -55,
        "freeHeap": 180000,
        "firmwareVersion": "0.00.01",
        "sequence": 1,
    }
    payload.update(changes)
    return payload


class _Message:
    def __init__(self, uid, kind="heartbeat", payload=None):
        self.topic = f"production/v1/devices/{uid}/{kind}"
        self.payload = json.dumps(payload if payload is not None else {"status": "ok"}).encode()


class _AckClient:
    def __init__(self, rc=0):
        self.rc = rc
        self.published = []

    def publish(self, topic, body, qos):
        self.published.append((topic, json.loads(body), qos))
        return type("Info", (), {"rc": self.rc})()


def _assert_ack(client, status, code=None, event_id="MQTT-M01-0-1234-1"):
    assert client.published
    topic, body, qos = client.published[-1]
    assert topic == "production/v1/devices/ESP32-MQTT-TEST/acks"
    assert qos == 1
    assert body["eventId"] == event_id
    assert body["status"] == status
    if code is not None:
        assert body["code"] == code


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


def test_telemetry_persists_then_acknowledges_and_duplicate_is_idempotent():
    device_id = _device()
    payload = _telemetry()
    client = _AckClient()

    mqtt_service._handle_message(client, None, _Message("ESP32-MQTT-TEST", "telemetry", payload))
    with SessionLocal() as db:
        rows = db.scalars(select(AFMSTelemetryEvent)).all()
        assert len(rows) == 1
        assert rows[0].device_id == device_id
        assert rows[0].event_id == payload["eventId"]
        assert rows[0].event_type == "STATUS"
        assert rows[0].sequence == 1
        assert json.loads(rows[0].payload_json) == payload
        _assert_ack(client, "accepted", "stored")

    mqtt_service._handle_message(client, None, _Message("ESP32-MQTT-TEST", "telemetry", payload))
    with SessionLocal() as db:
        assert db.scalar(select(func.count(AFMSTelemetryEvent.id))) == 1
    _assert_ack(client, "duplicate", "already-stored")


def test_same_event_id_with_different_payload_is_rejected():
    _device()
    client = _AckClient()
    original = _telemetry()
    mqtt_service._handle_message(client, None, _Message("ESP32-MQTT-TEST", "telemetry", original))

    conflicting = _telemetry(
        productionCount=2, rejectCount=1, goodCount=1
    )
    mqtt_service._handle_message(client, None, _Message("ESP32-MQTT-TEST", "telemetry", conflicting))

    with SessionLocal() as db:
        assert db.scalar(select(func.count(AFMSTelemetryEvent.id))) == 1
    _assert_ack(client, "rejected", "invalid-payload")


def test_invalid_telemetry_with_event_id_gets_permanent_rejection_ack():
    _device()
    client = _AckClient()
    payload = _telemetry(eventType="UNKNOWN_EVENT")

    mqtt_service._handle_message(client, None, _Message("ESP32-MQTT-TEST", "telemetry", payload))

    with SessionLocal() as db:
        assert db.scalar(select(func.count(AFMSTelemetryEvent.id))) == 0
    _assert_ack(client, "rejected", "invalid-payload")


def test_telemetry_machine_identity_must_match_registered_mapping():
    _device()
    client = _AckClient()
    payload = _telemetry(machineId="OTHER-MACHINE")

    mqtt_service._handle_message(client, None, _Message("ESP32-MQTT-TEST", "telemetry", payload))

    with SessionLocal() as db:
        assert db.scalar(select(func.count(AFMSTelemetryEvent.id))) == 0
    _assert_ack(client, "rejected", "invalid-payload")


def test_non_string_event_type_is_rejected_with_invalid_payload_ack():
    _device()
    client = _AckClient()
    payload = _telemetry(eventType=["STATUS"])

    mqtt_service._handle_message(client, None, _Message("ESP32-MQTT-TEST", "telemetry", payload))

    with SessionLocal() as db:
        assert db.scalar(select(func.count(AFMSTelemetryEvent.id))) == 0
    _assert_ack(client, "rejected", "invalid-payload")


def test_telemetry_from_disabled_device_is_not_saved_or_acknowledged():
    _device(active=False)
    client = _AckClient()

    mqtt_service._handle_message(
        client, None, _Message("ESP32-MQTT-TEST", "telemetry", _telemetry())
    )

    with SessionLocal() as db:
        assert db.scalar(select(func.count(AFMSTelemetryEvent.id))) == 0
    assert client.published == []


def test_ack_publish_failure_keeps_committed_event_for_duplicate_retry():
    _device()
    payload = _telemetry()
    failed_client = _AckClient(rc=1)

    mqtt_service._handle_message(
        failed_client, None, _Message("ESP32-MQTT-TEST", "telemetry", payload)
    )
    with SessionLocal() as db:
        assert db.scalar(select(func.count(AFMSTelemetryEvent.id))) == 1

    retry_client = _AckClient()
    mqtt_service._handle_message(
        retry_client, None, _Message("ESP32-MQTT-TEST", "telemetry", payload)
    )
    _assert_ack(retry_client, "duplicate", "already-stored")


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
