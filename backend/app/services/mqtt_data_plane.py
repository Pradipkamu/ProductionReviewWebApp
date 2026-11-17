"""AFMS MQTT data-plane client.

The privileged Dynamic Security control client remains isolated in mqtt_dynsec.py.
This client uses only the afms-backend-v1 role for device traffic.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import uuid
from datetime import datetime

import paho.mqtt.client as mqtt
from sqlalchemy import select

from ..config import get_settings
from ..db import SessionLocal
from ..models import AFMSDevice, Machine

logger = logging.getLogger(__name__)
TOPIC_ROOT = "production/v1/devices"
_DEVICE_TOPIC = re.compile(r"^production/v1/devices/([A-Za-z0-9._:-]+)/(heartbeat|telemetry|acks)$")
_client: mqtt.Client | None = None
_client_lock = threading.RLock()


class MQTTDataPlaneError(RuntimeError):
    """Raised when the AFMS data-plane client cannot be used safely."""


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
    # Telemetry and acknowledgements are authenticated and validated here.
    # Persistence and business-event mapping are deliberately a separate phase.
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
