"""Reliable AFMS MQTT ingestion and application acknowledgements.

Device telemetry is committed to the durable event ledger before an application
ACK is sent. Repeated QoS-1 deliveries are idempotent by (device_id, event_id).
"""
from __future__ import annotations

import json
import logging
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import paho.mqtt.client as mqtt
from sqlalchemy import func, select

from ..config import get_settings
from ..db import SessionLocal
from ..enums import SourceType
from ..models import (
    AFMSDevice, AFMSTelemetryEvent, Machine, MachineShiftProduction,
    MachineLossEvent, Product, RouteOperation, RouteVersion,
    OperationMachineMap, StandardCycleTime, Personnel, LossCategory,
)
from ..time_utils import ist_date

logger = logging.getLogger(__name__)
TOPIC_ROOT = "production/v1/devices"
_DEVICE_TOPIC = re.compile(r"^production/v1/devices/([A-Za-z0-9._:-]+)/(heartbeat|telemetry)$")
_client: mqtt.Client | None = None
_client_lock = threading.RLock()
_ALLOWED_EVENT_TYPES = {
    "STATUS", "WIFI_CONNECTED", "WIFI_DISCONNECTED", "WIFI_PROFILE_CHANGED",
    "PRODUCTION_PULSE", "REJECT_PULSE", "CYCLE_END", "MACHINE_READY",
    "IDLE_STARTED", "IDLE_ENDED", "ALARM_ACTIVATED", "ALARM_CLEARED",
    "LOSS_SELECTED", "SHIFT_CHANGED", "OPERATOR_CHANGED", "PART_CHANGED",
}


class MQTTDataPlaneError(RuntimeError):
    """Raised when the AFMS MQTT data-plane client cannot be used safely."""


def _registered_active_device(uid: str) -> bool:
    with SessionLocal() as db:
        row = db.scalar(
            select(AFMSDevice.id)
            .join(Machine, AFMSDevice.machine_id == Machine.id)
            .where(AFMSDevice.device_uid == uid, AFMSDevice.is_active.is_(True),
                   Machine.is_active.is_(True))
        )
        return row is not None


def _parse_timestamp(value) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp is required")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp must be ISO-8601") from exc
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _integer(payload: dict, key: str, default: int = 0) -> int:
    value = payload.get(key, default)
    if isinstance(value, bool):
        raise ValueError(f"{key} must be an integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be an integer") from exc
    if number < 0 or number > 2**63 - 1:
        raise ValueError(f"{key} is outside the supported range")
    return number


def _decimal(value, field: str, default: str = "0") -> Decimal:
    try:
        result = Decimal(str(default if value is None else value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not result.is_finite() or result < 0:
        raise ValueError(f"{field} must be a non-negative finite number")
    return result


def _resolve_production_context(db, device: AFMSDevice, payload: dict, occurred_at: datetime):
    part_code = str(payload.get("partCode") or "").strip()
    shift_id = _integer(payload, "shiftId")
    shift = {1: "A", 2: "B", 3: "C"}.get(shift_id)
    if not part_code or not shift:
        return None, "Missing partCode or valid shiftId (1, 2 or 3)"
    production_date = ist_date(occurred_at)
    product = db.scalar(select(Product).where(Product.code == part_code, Product.is_active.is_(True)))
    if product is None:
        return None, f"Active PRW product code {part_code!r} was not found"

    mappings = db.execute(
        select(OperationMachineMap, RouteOperation, RouteVersion)
        .join(RouteOperation, RouteOperation.id == OperationMachineMap.route_operation_id)
        .join(RouteVersion, RouteVersion.id == RouteOperation.route_version_id)
        .where(
            OperationMachineMap.machine_id == device.machine_id,
            OperationMachineMap.is_active.is_(True),
            OperationMachineMap.effective_from <= production_date,
            (OperationMachineMap.effective_to.is_(None) | (OperationMachineMap.effective_to >= production_date)),
            RouteOperation.is_enabled.is_(True),
            RouteVersion.product_id == product.id,
            RouteVersion.is_active.is_(True),
            RouteVersion.effective_from <= production_date,
            (RouteVersion.effective_to.is_(None) | (RouteVersion.effective_to >= production_date)),
        )
        .order_by(OperationMachineMap.priority, RouteVersion.effective_from.desc(), RouteOperation.id)
    ).all()
    if not mappings:
        return None, f"No effective PRW operation/machine mapping for product {part_code!r}"
    if len(mappings) > 1 and mappings[0][0].priority == mappings[1][0].priority:
        return None, f"Multiple equally ranked PRW operations map product {part_code!r} to this machine"
    mapping, route_operation, route_version = mappings[0]

    cycle = db.scalar(
        select(StandardCycleTime).where(
            StandardCycleTime.route_operation_id == route_operation.id,
            ((StandardCycleTime.machine_id == device.machine_id) | (StandardCycleTime.machine_id.is_(None))),
            StandardCycleTime.effective_from <= production_date,
            (StandardCycleTime.effective_to.is_(None) | (StandardCycleTime.effective_to >= production_date)),
        ).order_by(StandardCycleTime.machine_id.is_(None), StandardCycleTime.effective_from.desc(),
                   StandardCycleTime.id.desc())
    )
    if cycle is None or Decimal(cycle.ideal_cycle_time_sec or 0) <= 0:
        return None, f"Effective ideal cycle time is missing for product {part_code!r}"
    return {
        "product": product, "shift": shift, "production_date": production_date,
        "route_operation": route_operation, "cycle": cycle,
    }, None


def _sync_production_snapshot(db, device: AFMSDevice, payload: dict, occurred_at: datetime, event_id: str):
    context, error = _resolve_production_context(db, device, payload, occurred_at)
    if error:
        return "PENDING_MAPPING", error
    total = _integer(payload, "productionCount")
    rejected = _integer(payload, "rejectCount")
    good = _integer(payload, "goodCount")
    if rejected > total or good > total or good + rejected > total:
        return "PENDING_VALIDATION", "Good/reject counts are inconsistent with productionCount"
    shift_minutes = _decimal(payload.get("shiftDurationMin"), "shiftDurationMin", "480")
    break_minutes = _decimal(payload.get("plannedBreakMin"), "plannedBreakMin", "0")
    downtime_minutes = _decimal(_integer(payload, "downtimeSeconds") / 60, "downtimeMin")
    if shift_minutes <= 0 or break_minutes >= shift_minutes or downtime_minutes > shift_minutes - break_minutes:
        return "PENDING_VALIDATION", "Shift, planned-break or downtime minutes are inconsistent"

    operator_name = str(payload.get("operatorName") or "").strip()
    operator = None
    if operator_name:
        operator = db.scalar(select(Personnel).where(
            func.lower(Personnel.full_name) == operator_name.casefold(),
            Personnel.is_active.is_(True),
        ))

    row = db.scalar(
        select(MachineShiftProduction).where(
            MachineShiftProduction.production_date == context["production_date"],
            MachineShiftProduction.shift == context["shift"],
            MachineShiftProduction.machine_id == device.machine_id,
            MachineShiftProduction.product_id == context["product"].id,
            MachineShiftProduction.route_operation_id == context["route_operation"].id,
            MachineShiftProduction.source == SourceType.AFMS,
        ).order_by(MachineShiftProduction.id.desc()).limit(1)
    )
    if row is None:
        # Do not silently overwrite a manually entered OEE record.
        manual = db.scalar(select(MachineShiftProduction.id).where(
            MachineShiftProduction.production_date == context["production_date"],
            MachineShiftProduction.shift == context["shift"],
            MachineShiftProduction.machine_id == device.machine_id,
            MachineShiftProduction.product_id == context["product"].id,
            MachineShiftProduction.route_operation_id == context["route_operation"].id,
            MachineShiftProduction.source != SourceType.AFMS,
        ).limit(1))
        if manual is not None:
            return "PENDING_CONFLICT", "A non-AFMS OEE entry already exists for this machine/product/shift/date"
        row = MachineShiftProduction(
            production_date=context["production_date"], shift=context["shift"],
            product_id=context["product"].id, route_operation_id=context["route_operation"].id,
            machine_id=device.machine_id, source=SourceType.AFMS,
        )
        db.add(row)

    row.operator_id = operator.id if operator else None
    row.shift_duration_min = shift_minutes
    row.planned_break_min = break_minutes
    row.downtime_min = downtime_minutes
    row.total_count = Decimal(total)
    row.good_count = Decimal(good)
    row.reject_count = Decimal(rejected)
    row.ideal_cycle_time_sec = Decimal(context["cycle"].ideal_cycle_time_sec)
    row.remarks = f"AFMS event {event_id}"
    return "PROCESSED", None


def _sync_loss_event(db, device: AFMSDevice, payload: dict, occurred_at: datetime):
    if str(payload.get("eventType", "")).upper() != "LOSS_SELECTED":
        return None
    duration_seconds = _integer(payload, "lossDurationSeconds")
    if duration_seconds <= 0:
        return "Loss selection did not include a completed loss duration"
    code = str(payload.get("lossCode") or "").strip()
    name = str(payload.get("lossName") or "").strip()
    category = db.scalar(select(LossCategory).where(
        LossCategory.is_active.is_(True),
        ((LossCategory.code == code) | (func.lower(LossCategory.name) == name.casefold())),
    ))
    if category is None:
        return f"PRW loss category could not be matched (code={code!r}, name={name!r})"
    context, error = _resolve_production_context(db, device, payload, occurred_at)
    if error:
        return error
    end_time = occurred_at
    start_time = end_time - timedelta(seconds=duration_seconds)
    db.add(MachineLossEvent(
        loss_date=context["production_date"], shift=context["shift"],
        product_id=context["product"].id, route_operation_id=context["route_operation"].id,
        machine_id=device.machine_id, loss_category_id=category.id,
        start_time=start_time, end_time=end_time,
        duration_min=(Decimal(duration_seconds) / Decimal(60)),
        qty_loss=Decimal(0), remark=f"AFMS event lossCode={code}",
        source=SourceType.AFMS,
    ))
    return None


def _publish_application_ack(uid: str, event_id: str, status: str, code: str | None = None) -> None:
    with _client_lock:
        client = _client
    if client is None or not client.is_connected():
        return
    body = {"eventId": event_id, "status": status, "receivedAt": datetime.utcnow().isoformat() + "Z"}
    if code:
        body["code"] = code
    info = client.publish(f"{TOPIC_ROOT}/{uid}/acks", json.dumps(body, separators=(",", ":")), qos=1)
    if info.rc != mqtt.MQTT_ERR_SUCCESS:
        logger.warning("Could not queue AFMS application ACK for device %s", uid)
        return
    # Paho invokes this from its network callback. Do not wait here: blocking
    # the network loop would prevent the broker PUBACK from being processed.


def _handle_message(client, userdata, message) -> None:
    match = _DEVICE_TOPIC.fullmatch(message.topic)
    if not match:
        logger.warning("Ignoring MQTT message on an unexpected topic")
        return
    uid, message_type = match.groups()
    if len(message.payload) > 65536:
        logger.warning("Rejected oversized MQTT %s message from device %s", message_type, uid)
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
            device = db.scalar(select(AFMSDevice).join(Machine).where(
                AFMSDevice.device_uid == uid, AFMSDevice.is_active.is_(True), Machine.is_active.is_(True)))
            if device is None:
                logger.warning("Rejected heartbeat from unknown, disabled or unmapped device %s", uid)
                return
            device.last_seen_at = datetime.utcnow()
            if payload.get("firmwareVersion"):
                device.firmware_version = str(payload["firmwareVersion"])[:80]
            db.commit()
        return

    event_id = str(payload.get("eventId") or "").strip()
    if not event_id or len(event_id) > 128:
        logger.warning("Rejected AFMS telemetry without a valid eventId from %s", uid)
        return
    try:
        event_type = str(payload.get("eventType") or "").strip().upper()
        if event_type not in _ALLOWED_EVENT_TYPES:
            raise ValueError("eventType is not supported")
        occurred_at = _parse_timestamp(payload.get("timestamp"))
        sequence = _integer(payload, "sequence")
        if _integer(payload, "schemaVersion") != 1:
            raise ValueError("unsupported schemaVersion")
    except ValueError as exc:
        _publish_application_ack(uid, event_id, "rejected", "invalid-payload")
        logger.warning("Rejected invalid AFMS telemetry from %s: %s", uid, exc)
        return

    with SessionLocal() as db:
        device = db.scalar(select(AFMSDevice).join(Machine).where(
            AFMSDevice.device_uid == uid, AFMSDevice.is_active.is_(True), Machine.is_active.is_(True)))
        if device is None:
            logger.warning("Rejected telemetry from unknown, disabled or unmapped device %s", uid)
            return
        existing = db.scalar(select(AFMSTelemetryEvent).where(
            AFMSTelemetryEvent.device_id == device.id, AFMSTelemetryEvent.event_id == event_id))
        if existing is not None:
            duplicate = True
        else:
            duplicate = False
            raw_json = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
            row = AFMSTelemetryEvent(
                device_id=device.id, event_id=event_id, event_type=event_type,
                sequence=sequence, occurred_at=occurred_at, received_at=datetime.utcnow(),
                processing_status="RECEIVED", payload_json=raw_json,
            )
            db.add(row)
            try:
                if event_type in {"STATUS", "PRODUCTION_PULSE", "REJECT_PULSE", "CYCLE_END",
                                  "SHIFT_CHANGED", "PART_CHANGED", "OPERATOR_CHANGED", "LOSS_SELECTED",
                                  "ALARM_CLEARED", "ALARM_ACTIVATED"} and payload.get("partCode"):
                    status, error = _sync_production_snapshot(db, device, payload, occurred_at, event_id)
                    row.processing_status = status
                    row.processing_error = error
                else:
                    row.processing_status = "RECEIVED"
                loss_error = _sync_loss_event(db, device, payload, occurred_at)
                if loss_error:
                    row.processing_status = "PENDING_MAPPING"
                    row.processing_error = loss_error
                db.commit()
            except Exception:
                db.rollback()
                logger.exception("AFMS telemetry transaction failed for device %s event %s", uid, event_id)
                return
    _publish_application_ack(uid, event_id, "duplicate" if duplicate else "accepted")


def _on_connect(client, userdata, flags, reason_code, properties) -> None:
    if reason_code.is_failure:
        logger.error("AFMS MQTT data-plane connection refused (reason code %s)", reason_code)
        return
    topics = [(f"{TOPIC_ROOT}/+/heartbeat", 1), (f"{TOPIC_ROOT}/+/telemetry", 1)]
    result, _ = client.subscribe(topics)
    if result != mqtt.MQTT_ERR_SUCCESS:
        logger.error("Could not subscribe to AFMS MQTT device topics (rc=%s)", result)
    else:
        logger.info("AFMS MQTT data-plane connected and telemetry subscriptions requested")


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
        client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                             client_id="prw-afms-backend-" + uuid.uuid4().hex[:12],
                             protocol=mqtt.MQTTv311)
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
