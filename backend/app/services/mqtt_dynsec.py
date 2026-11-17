"""Mosquitto Dynamic Security adapter for AFMS device provisioning."""
from __future__ import annotations

import json
import logging
import threading
import uuid

import paho.mqtt.client as mqtt

from ..config import get_settings

logger = logging.getLogger(__name__)
CONTROL_TOPIC = "$CONTROL/dynamic-security/v1"
RESPONSE_TOPIC = "$CONTROL/dynamic-security/v1/response"
DEVICE_ROLE = "afms-device-v1"


class MQTTProvisioningError(RuntimeError):
    pass


def _execute(command: dict) -> dict:
    settings = get_settings()
    if not settings.mqtt_enabled:
        return {"enabled": False, "synchronized": False}
    if not settings.mqtt_control_username or not settings.mqtt_control_password:
        raise MQTTProvisioningError("MQTT control credentials are not configured")

    connected, response_ready = threading.Event(), threading.Event()
    state = {"response": None, "error": None}
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id="prw-afms-" + uuid.uuid4().hex[:12],
        protocol=mqtt.MQTTv311,
    )
    client.username_pw_set(settings.mqtt_control_username, settings.mqtt_control_password)

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            state["error"] = "MQTT broker refused the control connection"
            connected.set()
            return
        rc, _ = client.subscribe(RESPONSE_TOPIC, qos=1)
        if rc != mqtt.MQTT_ERR_SUCCESS:
            state["error"] = "Could not subscribe to Dynamic Security responses"
        connected.set()

    def on_message(client, userdata, message):
        try:
            state["response"] = json.loads(message.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            state["error"] = "Invalid Dynamic Security response"
        response_ready.set()

    client.on_connect, client.on_message = on_connect, on_message
    try:
        client.connect(settings.mqtt_host, settings.mqtt_internal_port, keepalive=20)
        client.loop_start()
        if not connected.wait(settings.mqtt_timeout_seconds):
            raise MQTTProvisioningError("Timed out connecting to MQTT broker")
        if state["error"]:
            raise MQTTProvisioningError(state["error"])
        info = client.publish(CONTROL_TOPIC, json.dumps({"commands": [command]}), qos=1)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise MQTTProvisioningError("Could not publish Dynamic Security command")
        info.wait_for_publish(timeout=settings.mqtt_timeout_seconds)
        if not response_ready.wait(settings.mqtt_timeout_seconds):
            raise MQTTProvisioningError("Timed out waiting for broker confirmation")
        if state["error"]:
            raise MQTTProvisioningError(state["error"])
        responses = (state["response"] or {}).get("responses", [])
        if len(responses) != 1 or responses[0].get("command") != command["command"] or responses[0].get("error"):
            detail = responses[0].get("error", "Unexpected response") if responses else "Empty response"
            raise MQTTProvisioningError("Broker rejected command: " + detail)
        return {"enabled": True, "synchronized": True}
    except MQTTProvisioningError:
        raise
    except Exception as exc:
        logger.exception("AFMS MQTT provisioning failed")
        raise MQTTProvisioningError("Could not synchronize device with MQTT broker") from exc
    finally:
        try:
            client.disconnect()
            client.loop_stop()
        except Exception:
            logger.debug("MQTT client cleanup failed", exc_info=True)


def create_device_client(device_uid: str, password: str) -> dict:
    return _execute({
        "command": "createClient",
        "username": device_uid,
        "password": password,
        "textname": "AFMS device " + device_uid,
        "roles": [{"rolename": DEVICE_ROLE, "priority": 1}],
    })


def set_device_password(device_uid: str, password: str) -> dict:
    return _execute({"command": "setClientPassword", "username": device_uid, "password": password})


def enable_device_client(device_uid: str) -> dict:
    return _execute({"command": "enableClient", "username": device_uid})


def disable_device_client(device_uid: str) -> dict:
    return _execute({"command": "disableClient", "username": device_uid})
