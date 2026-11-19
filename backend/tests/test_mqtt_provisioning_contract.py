from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[2] / "mqtt" / "provision_dynsec.py"
SPEC = importlib.util.spec_from_file_location("mqtt_provision_dynsec", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
provisioner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(provisioner)


def test_device_role_has_only_scoped_device_permissions():
    expected = {
        ("publishClientSend", "production/v1/devices/%u/heartbeat"),
        ("publishClientSend", "production/v1/devices/%u/telemetry"),
        ("subscribePattern", "production/v1/devices/%u/commands"),
        ("subscribePattern", "production/v1/devices/%u/acks"),
        ("publishClientReceive", "production/v1/devices/%u/commands"),
        ("publishClientReceive", "production/v1/devices/%u/acks"),
    }
    assert provisioner.desired_acl_map()[provisioner.DEVICE_ROLE] == expected


def test_backend_role_includes_ack_publish_and_limited_device_topics():
    expected = {
        ("subscribePattern", "production/v1/devices/+/heartbeat"),
        ("subscribePattern", "production/v1/devices/+/telemetry"),
        ("subscribePattern", "production/v1/devices/+/acks"),
        ("publishClientSend", "production/v1/devices/+/commands"),
        ("publishClientSend", "production/v1/devices/+/acks"),
    }
    assert provisioner.desired_acl_map()[provisioner.BACKEND_ROLE] == expected


def test_device_and_backend_roles_do_not_grant_wildcard_all_topics():
    for acl_set in provisioner.desired_acl_map().values():
        assert all(topic not in {"#", "+", "$SYS/#"} for _, topic in acl_set)
        assert all(topic.startswith("production/v1/devices/") for _, topic in acl_set)
