#!/usr/bin/env python3
"""Idempotently provision least-privilege AFMS MQTT Dynamic Security roles.

This runs only in the one-shot mqtt-provision Compose service.
It intentionally never prints credentials and never changes MQTT_ENABLED.
"""
from __future__ import annotations

import json
import os
import threading
import uuid

import paho.mqtt.client as mqtt

CONTROL_TOPIC = "$CONTROL/dynamic-security/v1"
RESPONSE_TOPIC = "$CONTROL/dynamic-security/v1/response"
TIMEOUT = max(5, int(os.getenv("MQTT_TIMEOUT_SECONDS", "8")))

DEVICE_ROLE = "afms-device-v1"
BACKEND_ROLE = "afms-backend-v1"
CONTROL_USERNAME = os.getenv("MQTT_CONTROL_USERNAME", "prw-afms-control")
BACKEND_USERNAME = os.getenv("MQTT_BACKEND_USERNAME", "prw-afms-backend")

DEVICE_ACLS = (
    ("publishClientSend", "production/v1/devices/%u/heartbeat"),
    ("publishClientSend", "production/v1/devices/%u/telemetry"),
    ("subscribePattern", "production/v1/devices/%u/commands"),
    ("subscribePattern", "production/v1/devices/%u/acks"),
    ("publishClientReceive", "production/v1/devices/%u/commands"),
    ("publishClientReceive", "production/v1/devices/%u/acks"),
)
BACKEND_ACLS = (
    ("subscribePattern", "production/v1/devices/+/heartbeat"),
    ("subscribePattern", "production/v1/devices/+/telemetry"),
    ("subscribePattern", "production/v1/devices/+/acks"),
    ("publishClientSend", "production/v1/devices/+/commands"),
    ("publishClientSend", "production/v1/devices/+/acks"),
)

def desired_acl_map() -> dict[str, frozenset[tuple[str, str]]]:
    """Pure contract helper: exact allowed ACLs for the two least-privilege roles."""
    return {
        DEVICE_ROLE: frozenset(DEVICE_ACLS),
        BACKEND_ROLE: frozenset(BACKEND_ACLS),
    }


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value or "CHANGE_THIS" in value.upper() or "PLACEHOLDER" in value.upper():
        raise RuntimeError(f"Required environment setting {name} is empty or a placeholder")
    return value


class DynsecAPI:
    def __init__(self, username: str, password: str, host: str, port: int):
        self.username = username
        self.password = password
        self.host = host
        self.port = port
        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id="prw-mqtt-provision-" + uuid.uuid4().hex[:10],
            protocol=mqtt.MQTTv311,
        )
        self.connected = threading.Event()
        self.subscribed = threading.Event()
        self.connect_error: str | None = None
        self.subscribe_error: str | None = None
        self.pending: dict[str, tuple[threading.Event, dict | None]] = {}
        self.pending_lock = threading.Lock()
        self.client.username_pw_set(username, password)
        self.client.on_connect = self._on_connect
        self.client.on_subscribe = self._on_subscribe
        self.client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            self.connect_error = f"broker refused MQTT login ({reason_code})"
            self.connected.set()
            return
        result, _ = client.subscribe(RESPONSE_TOPIC, qos=1)
        if result != mqtt.MQTT_ERR_SUCCESS:
            self.subscribe_error = f"could not subscribe to Dynamic Security responses (rc={result})"
            self.subscribed.set()
        self.connected.set()

    def _on_subscribe(self, client, userdata, mid, reason_codes, properties):
        if any(getattr(code, "is_failure", False) for code in reason_codes):
            self.subscribe_error = "broker refused Dynamic Security response subscription"
        self.subscribed.set()

    def _on_message(self, client, userdata, message):
        try:
            payload = json.loads(message.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        for response in payload.get("responses", []):
            correlation = response.get("correlationData")
            if not correlation:
                continue
            with self.pending_lock:
                pending = self.pending.get(correlation)
                if pending:
                    event, _ = pending
                    self.pending[correlation] = (event, response)
                    event.set()

    def start(self):
        self.client.connect(self.host, self.port, keepalive=30)
        self.client.loop_start()
        if not self.connected.wait(TIMEOUT):
            self.close()
            raise RuntimeError(f"timed out connecting to MQTT broker as {self.username}")
        if self.connect_error:
            error = self.connect_error
            self.close()
            raise RuntimeError(error)
        if not self.subscribed.wait(TIMEOUT):
            self.close()
            raise RuntimeError("timed out subscribing to Dynamic Security responses")
        if self.subscribe_error:
            error = self.subscribe_error
            self.close()
            raise RuntimeError(error)
        return self

    def request(self, command: dict) -> dict:
        correlation = uuid.uuid4().hex
        request = {**command, "correlationData": correlation}
        event = threading.Event()
        with self.pending_lock:
            self.pending[correlation] = (event, None)
        try:
            info = self.client.publish(
                CONTROL_TOPIC,
                json.dumps({"commands": [request]}, separators=(",", ":")),
                qos=1,
            )
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                raise RuntimeError(f"could not publish Dynamic Security command {command['command']}")
            info.wait_for_publish(timeout=TIMEOUT)
            if not info.is_published():
                raise RuntimeError(f"timed out publishing Dynamic Security command {command['command']}")
            if not event.wait(TIMEOUT):
                raise RuntimeError(f"timed out waiting for Dynamic Security command {command['command']}")
            with self.pending_lock:
                response = self.pending[correlation][1]
            if not isinstance(response, dict):
                raise RuntimeError("Dynamic Security broker returned an invalid response")
            return response
        finally:
            with self.pending_lock:
                self.pending.pop(correlation, None)

    def close(self):
        try:
            self.client.disconnect()
        except Exception:
            pass
        try:
            self.client.loop_stop()
        except Exception:
            pass


def _response_data(response: dict, key: str, command: str) -> dict:
    error = response.get("error")
    if error:
        raise RuntimeError(f"Dynamic Security {command} failed: {error}")
    value = response.get("data", {}).get(key)
    if not isinstance(value, dict):
        raise RuntimeError(f"Dynamic Security {command} response did not include {key}")
    return value


def get_role(api: DynsecAPI, role_name: str) -> dict | None:
    response = api.request({"command": "getRole", "rolename": role_name})
    if response.get("error") == "Role not found":
        return None
    return _response_data(response, "role", "getRole")


def ensure_role(
    api: DynsecAPI,
    role_name: str,
    description: str,
    allow_wildcard_subs: bool,
) -> dict:
    role = get_role(api, role_name)
    if role is None:
        response = api.request({
            "command": "createRole",
            "rolename": role_name,
            "textname": role_name,
            "textdescription": description,
            "allowwildcardsubs": allow_wildcard_subs,
        })
        if response.get("error") and response.get("error") != "Role already exists":
            raise RuntimeError(f"Could not create role {role_name}: {response['error']}")
        role = get_role(api, role_name)
    if role is None:
        raise RuntimeError(f"Role {role_name} was not created")
    if role.get("allowwildcardsubs") is not allow_wildcard_subs:
        response = api.request({
            "command": "modifyRole",
            "rolename": role_name,
            "allowwildcardsubs": allow_wildcard_subs,
        })
        if response.get("error"):
            raise RuntimeError(
                f"Could not set wildcard subscription policy for {role_name}: {response['error']}"
            )
        role = get_role(api, role_name)
    if role is None or role.get("allowwildcardsubs") is not allow_wildcard_subs:
        raise RuntimeError(f"Role {role_name} wildcard subscription policy did not verify")
    return role


def ensure_role_acls(api: DynsecAPI, role_name: str, expected: frozenset[tuple[str, str]]):
    allow_wildcard_subs = role_name == BACKEND_ROLE
    role = ensure_role(
        api,
        role_name,
        f"ProductionReviewWebApp AFMS {role_name} permissions",
        allow_wildcard_subs,
    )
    acls = role.get("acls", [])
    actual_keys = {(item.get("acltype"), item.get("topic")) for item in acls}
    unexpected = actual_keys - set(expected)
    if unexpected:
        details = ", ".join(f"{kind}:{topic}" for kind, topic in sorted(unexpected))
        raise RuntimeError(
            f"Role {role_name} has ACLs outside the approved installation policy ({details}). "
            "Review them manually; the provisioner will not silently remove permissions."
        )

    for acl_type, topic in sorted(expected):
        existing = [
            item for item in acls
            if item.get("acltype") == acl_type and item.get("topic") == topic
        ]
        if existing and all(item.get("allow") is True and item.get("priority", 100) == 100 for item in existing):
            continue
        if existing:
            response = api.request({
                "command": "removeRoleACL",
                "rolename": role_name,
                "acltype": acl_type,
                "topic": topic,
            })
            if response.get("error") and response.get("error") != "ACL not found":
                raise RuntimeError(f"Could not replace ACL on {role_name}: {response['error']}")
        response = api.request({
            "command": "addRoleACL",
            "rolename": role_name,
            "acltype": acl_type,
            "topic": topic,
            "allow": True,
            "priority": 100,
        })
        if response.get("error"):
            refreshed = get_role(api, role_name) or {}
            refreshed_acls = refreshed.get("acls", [])
            if not any(
                item.get("acltype") == acl_type
                and item.get("topic") == topic
                and item.get("allow") is True
                for item in refreshed_acls
            ):
                raise RuntimeError(f"Could not add ACL to {role_name}: {response['error']}")

    refreshed = get_role(api, role_name) or {}
    refreshed_acls = refreshed.get("acls", [])
    actual = {
        (item.get("acltype"), item.get("topic"))
        for item in refreshed_acls
        if item.get("allow") is True and item.get("priority", 100) == 100
    }
    unexpected_after = {
        (item.get("acltype"), item.get("topic"))
        for item in refreshed_acls
    } - set(expected)
    bad = [
        item for item in refreshed_acls
        if item.get("allow") is not True or item.get("priority", 100) != 100
    ]
    if actual != set(expected) or unexpected_after or bad:
        raise RuntimeError(f"Role {role_name} ACL verification did not match the approved policy")


def get_client(api: DynsecAPI, username: str) -> dict | None:
    response = api.request({"command": "getClient", "username": username})
    if response.get("error") == "Client not found":
        return None
    return _response_data(response, "client", "getClient")


def ensure_client(api: DynsecAPI, username: str, password: str, role_name: str, text_name: str):
    client = get_client(api, username)
    if client is None:
        response = api.request({
            "command": "createClient",
            "username": username,
            "password": password,
            "textname": text_name,
            "roles": [{"rolename": role_name, "priority": 100}],
        })
        if response.get("error") and response.get("error") != "Client already exists":
            raise RuntimeError(f"Could not create MQTT client {username}: {response['error']}")
        client = get_client(api, username)
    if client is None:
        raise RuntimeError(f"MQTT client {username} was not created")
    if client.get("disabled") is True:
        raise RuntimeError(f"MQTT client {username} is disabled; enable it deliberately before provisioning")
    roles = client.get("roles", [])
    actual_roles = {item.get("rolename") for item in roles}
    if actual_roles - {role_name}:
        raise RuntimeError(
            f"MQTT client {username} has unexpected roles {sorted(actual_roles - {role_name})}; "
            "review manually instead of silently broadening permissions."
        )
    if role_name not in actual_roles:
        response = api.request({
            "command": "addClientRole",
            "username": username,
            "rolename": role_name,
            "priority": 100,
        })
        if response.get("error"):
            raise RuntimeError(f"Could not assign role {role_name} to {username}: {response['error']}")
    verified = get_client(api, username)
    if verified is None or verified.get("disabled") is True:
        raise RuntimeError(f"MQTT client verification failed for {username}")
    if role_name not in {item.get("rolename") for item in verified.get("roles", [])}:
        raise RuntimeError(f"MQTT client {username} is missing role {role_name}")


def remove_demo_client(api: DynsecAPI):
    demo = get_client(api, "democlient")
    if demo is None:
        print("Default democlient: absent")
        return
    response = api.request({"command": "deleteClient", "username": "democlient"})
    if response.get("error"):
        raise RuntimeError(f"Could not remove the broad default democlient: {response['error']}")
    print("Default democlient: removed")


def connect_plain_client(username: str, password: str, client_id: str):
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=client_id,
        protocol=mqtt.MQTTv311,
    )
    connected = threading.Event()
    state = {"error": None}

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            state["error"] = str(reason_code)
        connected.set()

    client.username_pw_set(username, password)
    client.on_connect = on_connect
    client.connect(os.getenv("MQTT_HOST", "mqtt"), int(os.getenv("MQTT_INTERNAL_PORT", "1883")), keepalive=20)
    client.loop_start()
    if not connected.wait(TIMEOUT):
        client.disconnect()
        client.loop_stop()
        raise RuntimeError(f"timed out authenticating MQTT client {username}")
    if state["error"]:
        client.disconnect()
        client.loop_stop()
        raise RuntimeError(f"MQTT client {username} authentication failed: {state['error']}")
    return client


def wait_for_suback(client, topics):
    event = threading.Event()
    result = {"error": None}

    def on_subscribe(client, userdata, mid, reason_codes, properties):
        if any(getattr(code, "is_failure", False) for code in reason_codes):
            result["error"] = "broker rejected one or more required subscriptions"
        event.set()

    client.on_subscribe = on_subscribe
    rc, _ = client.subscribe([(topic, 1) for topic in topics])
    if rc != mqtt.MQTT_ERR_SUCCESS:
        raise RuntimeError(f"could not queue MQTT subscription (rc={rc})")
    if not event.wait(TIMEOUT):
        raise RuntimeError("timed out waiting for MQTT SUBACK")
    if result["error"]:
        raise RuntimeError(result["error"])


def wait_for_messages(event: threading.Event, expected: set[str], received: set[str], timeout=TIMEOUT):
    if not event.wait(timeout):
        raise RuntimeError("timed out waiting for MQTT ACL round-trip probe")
    if not expected.issubset(received):
        raise RuntimeError("MQTT ACL round-trip probe did not receive all expected topics")


def verify_acl_round_trip(api: DynsecAPI, backend_password: str):
    """Exercise both roles on harmless temporary topics; no application is enabled here."""
    probe_uid = "PRW-PROVISION-" + uuid.uuid4().hex[:8].upper()
    probe_password = uuid.uuid4().hex + uuid.uuid4().hex
    response = api.request({
        "command": "createClient",
        "username": probe_uid,
        "password": probe_password,
        "textname": "Temporary AFMS broker ACL verification client",
        "roles": [{"rolename": DEVICE_ROLE, "priority": 100}],
    })
    if response.get("error"):
        raise RuntimeError(f"Could not create temporary ACL probe client: {response['error']}")

    device_client = None
    backend_client = None
    backend_received: set[str] = set()
    device_received: set[str] = set()
    backend_event = threading.Event()
    device_event = threading.Event()
    lock = threading.Lock()
    try:
        device_client = connect_plain_client(
            probe_uid,
            probe_password,
            "prw-afms-device-check-" + uuid.uuid4().hex[:8],
        )
        backend_client = connect_plain_client(
            BACKEND_USERNAME,
            backend_password,
            "prw-afms-backend-check-" + uuid.uuid4().hex[:8],
        )

        def on_backend_message(client, userdata, message):
            with lock:
                backend_received.add(message.topic)
                if {
                    f"production/v1/devices/{probe_uid}/heartbeat",
                    f"production/v1/devices/{probe_uid}/telemetry",
                }.issubset(backend_received):
                    backend_event.set()

        def on_device_message(client, userdata, message):
            with lock:
                device_received.add(message.topic)
                if {
                    f"production/v1/devices/{probe_uid}/commands",
                    f"production/v1/devices/{probe_uid}/acks",
                }.issubset(device_received):
                    device_event.set()

        backend_client.on_message = on_backend_message
        device_client.on_message = on_device_message

        wait_for_suback(
            device_client,
            [
                f"production/v1/devices/{probe_uid}/commands",
                f"production/v1/devices/{probe_uid}/acks",
            ],
        )
        wait_for_suback(
            backend_client,
            [
                "production/v1/devices/+/heartbeat",
                "production/v1/devices/+/telemetry",
                "production/v1/devices/+/acks",
            ],
        )

        for kind in ("heartbeat", "telemetry"):
            info = device_client.publish(
                f"production/v1/devices/{probe_uid}/{kind}",
                json.dumps({"provisionProbe": True, "kind": kind}),
                qos=1,
            )
            info.wait_for_publish(timeout=TIMEOUT)
            if not info.is_published():
                raise RuntimeError(f"device ACL probe publish failed for {kind}")

        wait_for_messages(
            backend_event,
            {
                f"production/v1/devices/{probe_uid}/heartbeat",
                f"production/v1/devices/{probe_uid}/telemetry",
            },
            backend_received,
        )

        for kind in ("commands", "acks"):
            info = backend_client.publish(
                f"production/v1/devices/{probe_uid}/{kind}",
                json.dumps({"provisionProbe": True, "kind": kind}),
                qos=1,
            )
            info.wait_for_publish(timeout=TIMEOUT)
            if not info.is_published():
                raise RuntimeError(f"backend ACL probe publish failed for {kind}")

        wait_for_messages(
            device_event,
            {
                f"production/v1/devices/{probe_uid}/commands",
                f"production/v1/devices/{probe_uid}/acks",
            },
            device_received,
        )
        print("MQTT ACL round-trip probe: device and backend permissions passed")
    finally:
        for client in (device_client, backend_client):
            if client is not None:
                try:
                    client.disconnect()
                    client.loop_stop()
                except Exception:
                    pass
        cleanup = api.request({"command": "deleteClient", "username": probe_uid})
        if cleanup.get("error") and cleanup.get("error") != "Client not found":
            raise RuntimeError(f"Could not remove temporary ACL probe client: {cleanup['error']}")


def main():
    host = os.getenv("MQTT_HOST", "mqtt")
    port = int(os.getenv("MQTT_INTERNAL_PORT", "1883"))
    dynsec_password = required_env("MQTT_DYNSEC_PASSWORD")
    control_password = required_env("MQTT_CONTROL_PASSWORD")
    backend_password = required_env("MQTT_BACKEND_PASSWORD")
    control_username = required_env("MQTT_CONTROL_USERNAME")
    backend_username = required_env("MQTT_BACKEND_USERNAME")

    if os.getenv("MQTT_ENABLED", "false").strip().lower() == "true":
        raise RuntimeError(
            "First-time MQTT provisioning requires MQTT_ENABLED=false. "
            "The backend must remain disabled until the telemetry database migration is approved."
        )

    admin_api = None
    try:
        try:
            admin_api = DynsecAPI("admin", dynsec_password, host, port).start()
            print("Connected to broker with initial bootstrap administrator.")
        except Exception as admin_error:
            print(f"Initial administrator login unavailable; trying the dedicated control client ({admin_error}).")
            admin_api = DynsecAPI(control_username, control_password, host, port).start()
            print("Connected using the existing dedicated control client.")

        if get_role(admin_api, "dynsec-admin") is None:
            raise RuntimeError("Broker does not contain the required dynsec-admin role")

        ensure_role_acls(admin_api, DEVICE_ROLE, frozenset(DEVICE_ACLS))
        print("Device role and six scoped ACLs: verified")
        ensure_role_acls(admin_api, BACKEND_ROLE, frozenset(BACKEND_ACLS))
        print("Backend role and five scoped ACLs (including /acks publish): verified")

        ensure_client(
            admin_api,
            control_username,
            control_password,
            "dynsec-admin",
            "ProductionReviewWebApp Dynamic Security control client",
        )
        print("Dedicated control client: verified")
        ensure_client(
            admin_api,
            backend_username,
            backend_password,
            BACKEND_ROLE,
            "ProductionReviewWebApp AFMS data-plane client",
        )
        print("Backend data-plane client: verified")

        remove_demo_client(admin_api)
        admin_api.close()
        admin_api = None

        # Verify the dedicated control credential before disabling bootstrap admin.
        control_api = DynsecAPI(control_username, control_password, host, port).start()
        try:
            if get_role(control_api, DEVICE_ROLE) is None:
                raise RuntimeError("Dedicated control client failed Dynamic Security verification")

            verify_acl_round_trip(control_api, backend_password)

            bootstrap_admin = get_client(control_api, "admin")
            if bootstrap_admin is not None and bootstrap_admin.get("disabled") is not True:
                response = control_api.request({"command": "disableClient", "username": "admin"})
                if response.get("error"):
                    raise RuntimeError(f"Could not disable bootstrap admin: {response['error']}")
            print("Bootstrap admin: disabled; dedicated control client remains available")
        finally:
            control_api.close()

        print("MQTT Dynamic Security provisioning and verification completed.")
        print("MQTT_ENABLED remains false; backend/database activation is a separate approved step.")
    finally:
        if admin_api is not None:
            admin_api.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Do not include environment values or passwords in failure output.
        print(f"MQTT provisioning failed: {exc}")
        raise SystemExit(1)
