from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.services import mqtt_dynsec


class FakePublishInfo:
    rc = 0

    def __init__(self, published=True):
        self.published = published

    def wait_for_publish(self, timeout=None):
        return None

    def is_published(self):
        return self.published


class FakeReasonCode:
    is_failure = False


class FakeMQTTClient:
    instances = []
    published_payload = None
    response_command = None
    publish_complete = True

    def __init__(self, **kwargs):
        self.on_connect = None
        self.on_message = None
        self.username = None
        self.password = None
        self.subscriptions = []
        self.disconnected = False
        self.loop_stopped = False
        self.__class__.instances.append(self)

    def username_pw_set(self, username, password):
        self.username, self.password = username, password

    def connect(self, host, port, keepalive):
        self.host, self.port = host, port

    def loop_start(self):
        self.on_connect(self, None, None, FakeReasonCode(), None)

    def subscribe(self, topic, qos):
        self.subscriptions.append((topic, qos))
        return 0, 1

    def publish(self, topic, payload, qos):
        self.__class__.published_payload = json.loads(payload)
        command = self.__class__.published_payload["commands"][0]
        correlation_id = command["correlationData"]
        # A delayed response for another request must be ignored.
        stale = {"responses": [{
            "command": command["command"],
            "correlationData": "not-this-request",
        }]}
        self.on_message(self, None, SimpleNamespace(payload=json.dumps(stale).encode()))
        response = {"responses": [{
            "command": self.__class__.response_command or command["command"],
            "correlationData": correlation_id,
        }]}
        self.on_message(self, None, SimpleNamespace(payload=json.dumps(response).encode()))
        return FakePublishInfo(self.__class__.publish_complete)

    def disconnect(self):
        self.disconnected = True

    def loop_stop(self):
        self.loop_stopped = True


@pytest.fixture(autouse=True)
def reset_fake_client(monkeypatch):
    FakeMQTTClient.instances = []
    FakeMQTTClient.published_payload = None
    FakeMQTTClient.response_command = None
    FakeMQTTClient.publish_complete = True
    monkeypatch.setattr(mqtt_dynsec.mqtt, "Client", FakeMQTTClient)
    monkeypatch.setattr(
        mqtt_dynsec,
        "get_settings",
        lambda: SimpleNamespace(
            mqtt_enabled=True,
            mqtt_control_username="test-control",
            mqtt_control_password="test-password",
            mqtt_host="mqtt",
            mqtt_internal_port=1883,
            mqtt_timeout_seconds=0.05,
        ),
    )


def test_disabled_mode_does_not_connect_to_broker(monkeypatch):
    monkeypatch.setattr(
        mqtt_dynsec,
        "get_settings",
        lambda: SimpleNamespace(mqtt_enabled=False),
    )

    assert mqtt_dynsec.enable_device_client("device-01") == {
        "enabled": False,
        "synchronized": False,
    }
    assert FakeMQTTClient.instances == []


def test_execute_correlates_response_and_ignores_stale_messages():
    result = mqtt_dynsec.enable_device_client("device-01")

    command = FakeMQTTClient.published_payload["commands"][0]
    assert result == {"enabled": True, "synchronized": True}
    assert command["command"] == "enableClient"
    assert command["username"] == "device-01"
    assert command["correlationData"]
    client = FakeMQTTClient.instances[0]
    assert (mqtt_dynsec.RESPONSE_TOPIC, 1) in client.subscriptions
    assert client.disconnected and client.loop_stopped


def test_execute_rejects_response_for_different_command():
    FakeMQTTClient.response_command = "disableClient"

    with pytest.raises(mqtt_dynsec.MQTTProvisioningError, match="Unexpected broker response"):
        mqtt_dynsec.enable_device_client("device-01")


def test_execute_rejects_unpublished_command():
    FakeMQTTClient.publish_complete = False

    with pytest.raises(mqtt_dynsec.MQTTProvisioningError, match="Timed out publishing"):
        mqtt_dynsec.enable_device_client("device-01")


def test_enabled_mode_requires_control_credentials(monkeypatch):
    monkeypatch.setattr(
        mqtt_dynsec,
        "get_settings",
        lambda: SimpleNamespace(
            mqtt_enabled=True,
            mqtt_control_username="",
            mqtt_control_password="",
        ),
    )

    with pytest.raises(mqtt_dynsec.MQTTProvisioningError, match="credentials are not configured"):
        mqtt_dynsec.enable_device_client("device-01")
