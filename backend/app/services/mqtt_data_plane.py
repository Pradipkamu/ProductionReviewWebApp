"""AFMS MQTT data-plane client.

The privileged Dynamic Security control client remains isolated in mqtt_dynsec.py.
This client uses only the afms-backend-v1 role for device traffic.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import uuid
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..config import get_settings
from ..db import SessionLocal
from ..models import AFMSDevice, AFMSTelemetryEvent, Machine

logger = logging.getLogger(__name__)
TOPIC_ROOT = "production/v1/devices"
_DEVICE_TOPIC = re.compile(r"^production/v1/devices/([A-Za-z0-9._:-]+)/(heartbeat|telemetry|acks)$")
_client: mqtt.Client | None = None
_client_lock = threading.RLock()

_TELEMETRY_EVENT_TYPES = frozenset({
    "STATUS", "WIFI_CONNECTED", "WIFI_DISCONNECTED", "WIFI_PROFILE_CHANGED",
    "PRODUCTION_PULSE", "REJECT_PULSE", "CYCLE_END", "MACHINE_READY",
    "IDLE_STARTED", "IDLE_ENDED", "ALARM_ACTIVATED", "ALARM_CLEARED",
    "LOSS_SELECTED", "SHIFT_CHANGED", "OPERATOR_CHANGED", "PART_CHANGED",
})
_TELEMETRY_STATUSES = frozenset({
    "RUNNING", "IDLE", "BREAKDOWN", "STOPPED", "SETUP", "OFFLINE",
})
_TELEMETRY_INTEGER_FIELDS = (
    "sequence", "productionCount", "rejectCount", "goodCount",
    "unmatchedRejectPulses", "cycleTimeMs", "lossCode",
    "lossDurationSeconds", "shiftId", "operatorId", "standardCycleMs",
    "shiftDurationMin", "plannedBreakMin", "idleSeconds", "runSeconds",
    "downtimeSeconds", "availabilityPermille", "performancePermille",
    "qualityPermille", "oeePermille", "wifiRssi", "freeHeap",
)
_TELEMETRY_STRING_LIMITS = {
    "eventId": 180,
    "eventType": 40,
    "machineId": 100,
    "machineName": 180,
    "status": 20,
    "lossName": 180,
    "operatorName": 160,
    "partCode": 100,
    "partName": 180,
    "firmwareVersion": 80,
}


class MQTTDataPlaneError(RuntimeError):
    """Raised when the AFMS MQTT data-plane client cannot be used safely."""


def _registered_active_device(uid: str) -> bool:
    with SessionLocal() as db:
        row = db.scalar(
            select(AFMSDevice.id)
            .join(Machine, AFMSDevice.machine_id == Machine.id)
            .where(
                AFMSDevice.device_uid == uid,
                AFMSDevice.is_active.is_(True),
                Machine.is_active.is_(True),
            )
        )
        return row is not None


def _valid_event_id(value) -> bool:
    return isinstance(value, str) and 1 <= len(value) <= 180 and value.strip() == value


def _validate_telemetry_payload(payload: dict, machine: Machine) -> tuple[datetime, int]:
    """Validate the firmware schema and machine binding before persistence."""
    required = {
        "schemaVersion", "eventId", "eventType", "timestamp", "machineId",
        "machineName", "status", "productionCount", "rejectCount", "goodCount",
        "unmatchedRejectPulses", "cycleTimeMs", "lossCode", "lossName",
        "lossDurationSeconds", "shiftId", "operatorId", "operatorName",
        "standardCycleMs", "shiftDurationMin", "plannedBreakMin", "partCode",
        "partName", "alarmActive", "idleSeconds", "runSeconds",
        "downtimeSeconds", "availabilityPermille", "performancePermille",
        "qualityPermille", "oeePermille", "wifiRssi", "freeHeap",
        "firmwareVersion", "sequence",
    }
    allowed = required | set(_TELEMETRY_OPTIONAL_INTEGER_FIELDS) | {"partNumber"}
    missing = required.difference(payload)
    unexpected = set(payload).difference(allowed)
    if missing:
        raise ValueError("missing telemetry fields: " + ", ".join(sorted(missing)))
    if unexpected:
        raise ValueError("unexpected telemetry fields: " + ", ".join(sorted(unexpected)))

    if type(payload["schemaVersion"]) is not int or payload["schemaVersion"] != 1:
        raise ValueError("unsupported telemetry schemaVersion")
    if not _valid_event_id(payload["eventId"]):
        raise ValueError("invalid telemetry eventId")
    for field, limit in _TELEMETRY_STRING_LIMITS.items():
        value = payload.get(field)
        if not isinstance(value, str) or len(value) > limit:
            raise ValueError("invalid telemetry field: " + field)

    if payload["eventType"] not in _TELEMETRY_EVENT_TYPES:
        raise ValueError("unsupported telemetry eventType")
    if payload["status"] not in _TELEMETRY_STATUSES:
        raise ValueError("invalid telemetry machine status")

    # The registered machine code is the stable binding. The display name may
    # legitimately lag a master-data rename until device configuration syncs.
    if payload["machineId"] != machine.code:
        raise ValueError("telemetry machineId does not match the registered device mapping")

    if type(payload["alarmActive"]) is not bool:
        raise ValueError("invalid telemetry field: alarmActive")

    for field in _TELEMETRY_INTEGER_FIELDS:
        value = payload.get(field)
        if type(value) is not int:
            raise ValueError("invalid telemetry integer field: " + field)
        if field != "wifiRssi" and not 0 <= value <= 4294967295:
            raise ValueError("telemetry integer out of range: " + field)

    present_shift_metrics = [field for field in _TELEMETRY_OPTIONAL_INTEGER_FIELDS if field in payload]
    if present_shift_metrics and len(present_shift_metrics) != len(_TELEMETRY_OPTIONAL_INTEGER_FIELDS):
        raise ValueError("incomplete shift-scoped telemetry metrics")
    for field in present_shift_metrics:
        value = payload[field]
        if type(value) is not int or not 0 <= value <= 4294967295:
            raise ValueError("invalid telemetry integer field: " + field)
    if present_shift_metrics:
        if payload["shiftProductionCount"] != payload["shiftGoodCount"] + payload["shiftRejectCount"]:
            raise ValueError("shiftGoodCount plus shiftRejectCount must equal shiftProductionCount")
        if payload["shiftId"] == 0:
            raise ValueError("shift-scoped telemetry requires an active shift")

    if "partNumber" in payload:
        value = payload["partNumber"]
        if type(value) is not int or not 0 <= value <= 4294967295:
            raise ValueError("invalid telemetry field: partNumber")

    if payload["shiftId"] > 3:
        raise ValueError("invalid telemetry shiftId")
    if payload["rejectCount"] > payload["productionCount"]:
        raise ValueError("rejectCount cannot exceed productionCount")
    if payload["goodCount"] != payload["productionCount"] - payload["rejectCount"]:
        raise ValueError("goodCount does not match productionCount minus rejectCount")

    timestamp_value = payload["timestamp"]
    try:
        normalized = timestamp_value[:-1] + "+00:00" if timestamp_value.endswith("Z") else timestamp_value
        parsed = datetime.fromisoformat(normalized)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("invalid telemetry timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("telemetry timestamp must include a timezone")
    event_timestamp = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return event_timestamp, payload["sequence"]


def _publish_telemetry_ack(
    client, uid: str, event_id: str, status: str, code: str | None = None
) -> bool:
    """Queue an application ACK only after the event transaction is complete."""
    if client is None:
        logger.error("Cannot publish AFMS telemetry ACK without an MQTT client")
        return False
    body = {"eventId": event_id, "status": status}
    if code:
        body["code"] = code
    try:
        info = client.publish(
            f"{TOPIC_ROOT}/{uid}/acks",
            json.dumps(body, separators=(",", ":"), ensure_ascii=False),
            qos=1,
        )
    except Exception:
        logger.exception("Could not queue AFMS telemetry ACK for device %s", uid)
        return False
    if info.rc != mqtt.MQTT_ERR_SUCCESS:
        logger.error("Could not queue AFMS telemetry ACK for device %s (rc=%s)", uid, info.rc)
        return False
    logger.info("Queued AFMS telemetry ACK status=%s for device %s event %s", status, uid, event_id)
    return True


def _handle_telemetry(client, uid: str, payload: dict) -> None:
    event_id = payload.get("eventId")
    ackable = _valid_event_id(event_id)
    outcome = None
    ack_code = None

    try:
        with SessionLocal() as db:
            device = db.scalar(
                select(AFMSDevice)
                .join(Machine, AFMSDevice.machine_id == Machine.id)
                .where(
                    AFMSDevice.device_uid == uid,
                    AFMSDevice.is_active.is_(True),
                    Machine.is_active.is_(True),
                )
            )
            if device is None:
                logger.warning(
                    "Rejected MQTT telemetry from unknown, disabled or unmapped device %s", uid
                )
                return
            machine = db.get(Machine, device.machine_id)
            if machine is None or not machine.is_active:
                logger.warning("Rejected MQTT telemetry from inactive machine for device %s", uid)
                return

            try:
                event_timestamp, sequence = _validate_telemetry_payload(payload, machine)
            except ValueError as exc:
                logger.warning("Rejected invalid AFMS telemetry from device %s: %s", uid, exc)
                outcome = "rejected"
                ack_code = "invalid-payload"
            else:
                canonical_json = json.dumps(
                    payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                )
                payload_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
                existing = db.scalar(
                    select(AFMSTelemetryEvent).where(
                        AFMSTelemetryEvent.device_id == device.id,
                        AFMSTelemetryEvent.event_id == event_id,
                    )
                )
                if existing is not None:
                    outcome = "duplicate" if existing.payload_sha256 == payload_hash else "rejected"
                    if outcome == "rejected":
                        ack_code = "invalid-payload"
                        logger.error(
                            "AFMS telemetry event ID collision for device %s event %s",
                            uid, event_id,
                        )
                else:
                    db.add(AFMSTelemetryEvent(
                        device_id=device.id,
                        event_id=event_id,
                        event_type=payload["eventType"],
                        event_timestamp=event_timestamp,
                        sequence=sequence,
                        payload_sha256=payload_hash,
                        payload_json=canonical_json,
                    ))
                    try:
                        db.commit()
                        outcome = "accepted"
                    except IntegrityError:
                        # A concurrent delivery may have inserted the same event.
                        # Resolve the unique-key race and ACK only the committed row.
                        db.rollback()
                        existing = db.scalar(
                            select(AFMSTelemetryEvent).where(
                                AFMSTelemetryEvent.device_id == device.id,
                                AFMSTelemetryEvent.event_id == event_id,
                            )
                        )
                        if existing is None:
                            raise
                        outcome = "duplicate" if existing.payload_sha256 == payload_hash else "rejected"
                        if outcome == "rejected":
                            ack_code = "invalid-payload"
                            logger.error(
                                "AFMS telemetry event ID collision for device %s event %s",
                                uid, event_id,
                            )
    except Exception:
        # Do not ACK transient database/processing failures. The ESP32 will retry.
        logger.exception("AFMS telemetry processing failed for device %s event %s", uid, event_id)
        return

    if outcome == "rejected" and not ackable:
        logger.warning("Cannot ACK invalid AFMS telemetry without a valid eventId from device %s", uid)
        return
    if outcome in {"accepted", "duplicate", "rejected"} and ackable:
        _publish_telemetry_ack(
            client, uid, event_id, outcome, ack_code or (
                "stored" if outcome == "accepted" else
                "already-stored" if outcome == "duplicate" else None
            ),
        )
        if outcome == "accepted":
            logger.info("Accepted and stored AFMS MQTT telemetry from device %s event %s", uid, event_id)
        elif outcome == "duplicate":
            logger.info("Recognized duplicate AFMS MQTT telemetry from device %s event %s", uid, event_id)


def _handle_message(client, userdata, message) -> None:
    match = _DEVICE_TOPIC.fullmatch(message.topic)
    if not match:
        logger.warning("Ignoring MQTT message on an unexpected topic")
        return
    uid, message_type = match.groups()
    if len(message.payload) > 65536:
        logger.warning("Rejected oversized MQTT %s message from device %s", message_type, uid)
        return
    if not _registered_active_device(uid):
        logger.warning("Rejected MQTT %s message from unknown, disabled or unmapped device %s", message_type, uid)
        return
    try:
        payload = json.loads(message.payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        logger.warning("Rejected malformed MQTT %s JSON from device %s", message_type, uid)
        return
    if not isinstance(payload, dict):
        logger.warning("Rejected non-object MQTT %s payload from device %s", message_type, uid)
        return

    if message_type == "heartbeat":
        with SessionLocal() as db:
            device = db.scalar(
                select(AFMSDevice)
                .join(Machine, AFMSDevice.machine_id == Machine.id)
                .where(
                    AFMSDevice.device_uid == uid,
                    AFMSDevice.is_active.is_(True),
                    Machine.is_active.is_(True),
                )
            )
            if device is None:
                logger.warning("Device %s became inactive before heartbeat update", uid)
                return
            device.last_seen_at = datetime.utcnow()
            db.commit()
        logger.info("Accepted AFMS MQTT heartbeat from registered device %s", uid)
    elif message_type == "telemetry":
        _handle_telemetry(client, uid, payload)
    else:
        # Device acknowledgements are accepted as protocol messages but are not
        # applied to business data by this backend phase.
        logger.info("Accepted AFMS MQTT %s from registered device %s", message_type, uid)


def _on_connect(client, userdata, flags, reason_code, properties) -> None:
    if reason_code.is_failure:
        logger.error("AFMS MQTT data-plane connection refused (reason code %s)", reason_code)
        return
    topics = [
        (f"{TOPIC_ROOT}/+/heartbeat", 1),
        (f"{TOPIC_ROOT}/+/telemetry", 1),
        (f"{TOPIC_ROOT}/+/acks", 1),
    ]
    result, _ = client.subscribe(topics)
    if result != mqtt.MQTT_ERR_SUCCESS:
        logger.error("Could not subscribe to AFMS MQTT device topics (rc=%s)", result)
    else:
        logger.info("AFMS MQTT data-plane connected and subscriptions requested")


def start_mqtt_data_plane() -> None:
    """Start the reconnecting backend MQTT client when MQTT is enabled."""
    global _client
    settings = get_settings()
    if not settings.mqtt_enabled:
        return
    if not settings.mqtt_backend_username or not settings.mqtt_backend_password:
        raise MQTTDataPlaneError("MQTT backend data-plane credentials are not configured")

    with _client_lock:
        if _client is not None:
            return
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id="prw-afms-backend-" + uuid.uuid4().hex[:12],
            protocol=mqtt.MQTTv311,
        )
        client.username_pw_set(settings.mqtt_backend_username, settings.mqtt_backend_password)
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        client.on_connect = _on_connect
        client.on_message = _handle_message
        try:
            client.connect(settings.mqtt_host, settings.mqtt_internal_port, keepalive=30)
            client.loop_start()
        except Exception as exc:
            try:
                client.loop_stop()
            except Exception:
                pass
            raise MQTTDataPlaneError("Could not start the AFMS MQTT data-plane client") from exc
        _client = client


def stop_mqtt_data_plane() -> None:
    """Stop the backend MQTT client during application shutdown."""
    global _client
    with _client_lock:
        client, _client = _client, None
    if client is not None:
        try:
            client.disconnect()
        finally:
            client.loop_stop()


def publish_device_command(device_uid: str, payload: dict) -> None:
    """Publish a command only to a currently active, explicitly mapped device."""
    if not _registered_active_device(device_uid):
        raise MQTTDataPlaneError("AFMS device is unknown, disabled or not mapped to an active machine")
    if not isinstance(payload, dict):
        raise ValueError("AFMS command payload must be a JSON object")
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    if len(body.encode("utf-8")) > 65536:
        raise ValueError("AFMS command payload exceeds 64 KiB")
    with _client_lock:
        client = _client
    if client is None or not client.is_connected():
        raise MQTTDataPlaneError("AFMS MQTT data-plane is not connected")
    info = client.publish(f"{TOPIC_ROOT}/{device_uid}/commands", body, qos=1)
    if info.rc != mqtt.MQTT_ERR_SUCCESS:
        raise MQTTDataPlaneError("Could not queue AFMS command for publishing")
    info.wait_for_publish(timeout=get_settings().mqtt_timeout_seconds)
    if not info.is_published():
        raise MQTTDataPlaneError("Timed out publishing AFMS command")
