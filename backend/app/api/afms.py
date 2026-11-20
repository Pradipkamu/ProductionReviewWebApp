from __future__ import annotations

import hashlib
import json
import secrets
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..enums import UserRole
from ..models import (AFMSDevice, AFMSTelemetryEvent, Machine, User, Product, RouteOperation, RouteVersion, Operation, OperationMachineMap, StandardCycleTime, Personnel)
from ..services.oee import calculate_oee
from ..services.mqtt_dynsec import MQTTProvisioningError, create_device_client, set_device_password, enable_device_client, disable_device_client

router = APIRouter(prefix="/afms", tags=["AFMS"])

def _admin(user: User) -> None:
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Only ADMIN can manage AFMS devices")

def _device_status(device: AFMSDevice) -> str:
    if not device.is_active: return "DISABLED"
    if device.last_seen_at is None: return "NEVER_CONNECTED"
    if device.last_seen_at >= datetime.utcnow() - timedelta(minutes=2): return "ONLINE"
    return "OFFLINE"

def _device_out(device: AFMSDevice) -> dict:
    machine = device.machine
    return {
        "id": device.id, "machine_id": machine.id, "machine_number": machine.code,
        "machine_name": machine.name, "plant": machine.plant, "device_uid": device.device_uid,
        "device_name": device.device_name, "device_role": device.device_role,
        "hardware_model": device.hardware_model, "firmware_version": device.firmware_version,
        "protocol_version": device.protocol_version, "is_active": device.is_active,
        "status": _device_status(device), "last_seen_at": device.last_seen_at,
        "notes": device.notes, "created_at": device.created_at,
    }

class DeviceRegister(BaseModel):
    machine_id: int = Field(gt=0)
    device_uid: str = Field(min_length=3, max_length=100, pattern=r'^[A-Za-z0-9._:-]+$')
    device_name: Optional[str] = Field(default=None, max_length=120)
    device_role: str = Field(default="MAIN_CONTROLLER", min_length=2, max_length=40)
    hardware_model: Optional[str] = Field(default=None, max_length=120)
    firmware_version: Optional[str] = Field(default=None, max_length=80)
    protocol_version: str = Field(default="1.0", min_length=1, max_length=30)
    notes: Optional[str] = Field(default=None, max_length=500)

class DeviceUpdate(BaseModel):
    is_active: Optional[bool] = None
    device_name: Optional[str] = Field(default=None, max_length=120)
    device_role: Optional[str] = Field(default=None, min_length=2, max_length=40)
    hardware_model: Optional[str] = Field(default=None, max_length=120)
    firmware_version: Optional[str] = Field(default=None, max_length=80)
    protocol_version: Optional[str] = Field(default=None, min_length=1, max_length=30)
    notes: Optional[str] = Field(default=None, max_length=500)


_IST = ZoneInfo("Asia/Kolkata")
_SHIFT_IDS = {"A": 1, "B": 2, "C": 3}


def _resolve_afms_oee_context(db: Session, machine: Machine, payload: dict, production_date: date) -> dict:
    """Resolve telemetry part/operator context against active PRW masters."""
    result = {"product": None, "route": None, "operation": None, "cycle": None,
              "operator": None, "warnings": []}
    part_code = (payload.get("partCode") or "").strip()
    if not part_code:
        result["warnings"].append("Select a part on the ESP32/HMI before OEE can be calculated.")
        return result

    product = db.scalar(select(Product).where(
        Product.code == part_code, Product.is_active.is_(True)
    ))
    if not product:
        result["warnings"].append(f"Part code {part_code} is not mapped to an active PRW Product code.")
        return result
    result["product"] = product

    route_rows = db.execute(
        select(RouteOperation, RouteVersion, Operation)
        .join(RouteVersion, RouteVersion.id == RouteOperation.route_version_id)
        .join(Operation, Operation.id == RouteOperation.operation_id)
        .join(OperationMachineMap, OperationMachineMap.route_operation_id == RouteOperation.id)
        .where(
            RouteVersion.product_id == product.id,
            RouteVersion.is_active.is_(True),
            RouteVersion.effective_from <= production_date,
            (RouteVersion.effective_to.is_(None) | (RouteVersion.effective_to >= production_date)),
            RouteOperation.is_enabled.is_(True),
            Operation.is_active.is_(True),
            OperationMachineMap.machine_id == machine.id,
            OperationMachineMap.is_active.is_(True),
            OperationMachineMap.effective_from <= production_date,
            (OperationMachineMap.effective_to.is_(None) | (OperationMachineMap.effective_to >= production_date)),
        )
        .order_by(RouteOperation.id)
    ).all()
    unique_routes = {row[0].id: row for row in route_rows}
    if len(unique_routes) != 1:
        result["warnings"].append(
            "The selected part must have exactly one active operation mapped to this machine for the selected date."
        )
        return result
    route, version, operation = next(iter(unique_routes.values()))
    result["route"] = route
    result["operation"] = operation

    cycle = db.scalar(
        select(StandardCycleTime).where(
            StandardCycleTime.route_operation_id == route.id,
            ((StandardCycleTime.machine_id == machine.id) | StandardCycleTime.machine_id.is_(None)),
            StandardCycleTime.effective_from <= production_date,
            (StandardCycleTime.effective_to.is_(None) | (StandardCycleTime.effective_to >= production_date)),
        ).order_by(
            StandardCycleTime.machine_id.is_(None),
            StandardCycleTime.effective_from.desc(),
            StandardCycleTime.id.desc(),
        )
    )
    if not cycle or cycle.ideal_cycle_time_sec <= 0:
        result["warnings"].append("Effective ideal cycle time is missing in PRW Standard Cycle Time Master.")
    else:
        result["cycle"] = cycle

    operator_id = payload.get("operatorId")
    operator_name = (payload.get("operatorName") or "").strip()
    person = None
    if isinstance(operator_id, int) and operator_id > 0:
        person = db.get(Personnel, operator_id)
        if person and not person.is_active:
            person = None
    if person is None and operator_name:
        matches = db.scalars(select(Personnel).where(
            Personnel.is_active.is_(True),
            func.lower(func.trim(Personnel.full_name)) == operator_name.casefold(),
        )).all()
        if len(matches) == 1:
            person = matches[0]
        elif len(matches) > 1:
            result["warnings"].append("Operator name matches more than one active Personnel record.")
    if person is None:
        result["warnings"].append("Operator is not mapped to an active PRW Personnel record.")
    result["operator"] = person
    return result


@router.get("/oee/live")
def afms_live_oee(machine_id: int, production_date: date, shift: str,
                  db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Read-only live OEE preview from the latest shift-scoped AFMS telemetry snapshot.

    This endpoint deliberately does not create or update MachineShiftProduction.
    """
    normalized_shift = shift.strip().upper()
    shift_id = _SHIFT_IDS.get(normalized_shift)
    if not shift_id:
        raise HTTPException(status_code=422, detail="Shift must be A, B or C.")

    machine = db.get(Machine, machine_id)
    if not machine or not machine.is_active:
        raise HTTPException(status_code=404, detail="Active machine not found.")

    device = db.scalar(select(AFMSDevice).where(
        AFMSDevice.machine_id == machine_id,
        AFMSDevice.is_active.is_(True),
    ))
    if not device:
        return {"status": "DEVICE_NOT_REGISTERED", "machine_id": machine_id,
                "message": "No active AFMS device is mapped to this machine."}

    start_local = datetime.combine(production_date, time.min, tzinfo=_IST)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)
    events = db.scalars(
        select(AFMSTelemetryEvent).where(
            AFMSTelemetryEvent.device_id == device.id,
            AFMSTelemetryEvent.event_timestamp >= start_utc,
            AFMSTelemetryEvent.event_timestamp < end_utc,
        ).order_by(AFMSTelemetryEvent.event_timestamp.desc(), AFMSTelemetryEvent.id.desc()).limit(500)
    ).all()

    latest_any = None
    selected = None
    for event in events:
        try:
            payload = json.loads(event.payload_json)
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        if latest_any is None:
            latest_any = (event, payload)
        if payload.get("shiftId") == shift_id:
            selected = (event, payload)
            break

    if selected is None:
        latest_shift = latest_any[1].get("shiftId") if latest_any else None
        status = "NO_TELEMETRY" if latest_any is None else (
            "NO_SHIFT_CONTEXT" if latest_shift in (None, 0) else "NO_DATA_FOR_SHIFT"
        )
        return {"status": status, "machine_id": machine_id, "device_uid": device.device_uid,
                "production_date": production_date, "shift": normalized_shift,
                "latest_device_shift_id": latest_shift,
                "message": "No telemetry snapshot is available for this date and shift. Confirm the ESP32 shift is selected and MQTT is connected."}

    event, payload = selected
    required_shift_fields = (
        "shiftProductionCount", "shiftRejectCount", "shiftGoodCount",
        "shiftRunSeconds", "shiftIdleSeconds", "shiftDowntimeSeconds",
    )
    if not all(field in payload for field in required_shift_fields):
        return {"status": "FIRMWARE_UPDATE_REQUIRED", "machine_id": machine_id,
                "device_uid": device.device_uid, "production_date": production_date,
                "shift": normalized_shift, "event_timestamp": event.event_timestamp,
                "received_at": event.received_at,
                "message": "The device is still sending machine-wide counters. Install the AFMS firmware update that publishes shift-scoped counters before automatic OEE can be calculated."}

    total = int(payload["shiftProductionCount"])
    reject = int(payload["shiftRejectCount"])
    good = int(payload["shiftGoodCount"])
    run_seconds = int(payload["shiftRunSeconds"])
    idle_seconds = int(payload["shiftIdleSeconds"])
    downtime_seconds = int(payload["shiftDowntimeSeconds"])
    duration_min = int(payload.get("shiftDurationMin") or 0)
    break_min = int(payload.get("plannedBreakMin") or 0)
    if (duration_min <= 0 or duration_min > 1440 or break_min < 0 or break_min >= duration_min
            or good + reject != total):
        return {"status": "INVALID_SHIFT_METRICS", "machine_id": machine_id,
                "device_uid": device.device_uid, "production_date": production_date,
                "shift": normalized_shift,
                "message": "The device shift counters or shift-time configuration are inconsistent. OEE was not calculated."}

    context = _resolve_afms_oee_context(db, machine, payload, production_date)
    warnings = list(context["warnings"])
    cycle = context["cycle"]
    oee = None
    status = "READY"
    if context["product"] is None:
        status = "PART_NOT_MAPPED"
    elif context["route"] is None:
        status = "OPERATION_MAPPING_REQUIRED"
    elif cycle is None:
        status = "STANDARD_CYCLE_TIME_MISSING"
    else:
        planned_min = max(0.0, float(duration_min - break_min))
        # Use the device's measured breakdown time as availability downtime.
        # Idle time is retained separately and remains visible as an
        # unclassified performance loss until an operator classifies it.
        downtime_min = min(planned_min, downtime_seconds / 60.0)
        oee = calculate_oee(duration_min, break_min, downtime_min, total, good,
                            float(cycle.ideal_cycle_time_sec))
        if downtime_seconds / 60.0 > planned_min:
            warnings.append("Measured breakdown time exceeds planned production time; it was capped for OEE calculation.")
        tracked_state_seconds = run_seconds + idle_seconds + downtime_seconds
        if abs(tracked_state_seconds - planned_min * 60) > 120:
            warnings.append("AFMS shift run/idle/downtime counters do not reconcile to shift duration; verify shift start and session state.")
        device_cycle_ms = int(payload.get("standardCycleMs") or 0)
        master_cycle_ms = float(cycle.ideal_cycle_time_sec) * 1000.0
        if device_cycle_ms and abs(device_cycle_ms - master_cycle_ms) > 100:
            warnings.append("ESP32 cycle-time setting differs from the effective PRW master; the PRW master value was used.")

    now_utc = datetime.utcnow()
    is_current_date = production_date == datetime.now(_IST).date()
    age_seconds = max(0.0, (now_utc - event.received_at).total_seconds()) if event.received_at else None
    is_live = is_current_date and age_seconds is not None and age_seconds <= 300
    if is_current_date and not is_live:
        warnings.append("Latest AFMS snapshot is older than five minutes; values may be stale.")

    person = context["operator"]
    return {
        "status": status, "is_live": is_live, "machine_id": machine.id,
        "machine_code": machine.code, "machine_name": machine.name,
        "device_uid": device.device_uid, "event_id": event.event_id,
        "event_type": event.event_type, "event_timestamp": event.event_timestamp,
        "received_at": event.received_at, "production_date": production_date,
        "shift": normalized_shift, "part_code": payload.get("partCode") or "",
        "part_name": payload.get("partName") or "",
        "product_id": context["product"].id if context["product"] else None,
        "product_name": context["product"].name if context["product"] else None,
        "route_operation_id": context["route"].id if context["route"] else None,
        "operation_name": context["operation"].name if context["operation"] else None,
        "operator_id": person.id if person else None,
        "operator_name": person.full_name if person else (payload.get("operatorName") or None),
        "shift_duration_min": duration_min, "planned_break_min": break_min,
        "total_count": total, "good_count": good, "reject_count": reject,
        "run_seconds": run_seconds, "idle_seconds": idle_seconds,
        "downtime_seconds": downtime_seconds,
        "oee_downtime_min": min(max(0.0, float(duration_min - break_min)), downtime_seconds / 60.0),
        "unclassified_idle_min": idle_seconds / 60.0,
        "ideal_cycle_time_sec": float(cycle.ideal_cycle_time_sec) if cycle else None,
        "observed_cycle_time_ms": int(payload.get("cycleTimeMs") or 0),
        "oee": oee, "warnings": warnings,
        "collection_mode": "LIVE_PREVIEW_ONLY",
    }


@router.get("/overview")
def overview(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    total = db.scalar(select(func.count(Machine.id))) or 0
    active = db.scalar(select(func.count(Machine.id)).where(Machine.is_active.is_(True))) or 0
    registered = db.scalar(select(func.count(AFMSDevice.id))) or 0
    enabled = db.scalar(select(func.count(AFMSDevice.id)).where(AFMSDevice.is_active.is_(True))) or 0
    online = db.scalar(select(func.count(AFMSDevice.id)).where(AFMSDevice.is_active.is_(True), AFMSDevice.last_seen_at >= datetime.utcnow() - timedelta(minutes=2))) or 0
    return {"module":"AFMS","status":"INITIALIZED","integration_status":"DEVICE_REGISTRY_READY",
            "machine_master":{"total":total,"active":active},
            "devices":{"registered":registered,"enabled":enabled,"online":online},
            "telemetry":{"status":"NOT_CONNECTED","last_received_at":None},
            "next_phase":"Secure device authentication and MQTT cycle-event ingestion"}

@router.get("/machines")
def afms_machines(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rows = db.scalars(select(Machine).order_by(Machine.plant, Machine.code)).all()
    mapped = set(db.scalars(select(AFMSDevice.machine_id).where(AFMSDevice.is_active.is_(True))).all())
    return [{"id":r.id,"machine_id":r.id,"machine_number":r.code,"code":r.code,"machine_name":r.name,"name":r.name,"plant":r.plant,"department":r.department,"machine_type":r.machine_type,"is_active":r.is_active,"device_registered":r.id in mapped} for r in rows]

@router.get("/devices")
def list_devices(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rows = db.scalars(select(AFMSDevice).join(Machine).order_by(Machine.plant, Machine.code, AFMSDevice.device_uid)).all()
    return [_device_out(row) for row in rows]

@router.post("/devices", status_code=201)
def register_device(payload: DeviceRegister, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _admin(user)
    machine = db.get(Machine, payload.machine_id)
    if not machine or not machine.is_active: raise HTTPException(status_code=422, detail="Select an active machine from the PRW Machine Master")
    uid = payload.device_uid.strip()
    if db.scalar(select(AFMSDevice.id).where(AFMSDevice.device_uid == uid)): raise HTTPException(status_code=409, detail="This device UID is already registered")
    existing = db.scalar(select(AFMSDevice.id).where(AFMSDevice.machine_id == machine.id, AFMSDevice.is_active.is_(True)))
    if existing: raise HTTPException(status_code=409, detail="An active AFMS device is already mapped to this machine. Deactivate it before registering a replacement.")
    secret = "afms_" + secrets.token_urlsafe(32)
    try:
        create_device_client(uid, secret)
    except MQTTProvisioningError as exc:
        raise HTTPException(status_code=503, detail=f"MQTT broker provisioning failed: {exc}") from exc
    row = AFMSDevice(machine_id=machine.id, device_uid=uid, device_name=payload.device_name.strip() if payload.device_name else None,
        device_role=payload.device_role.strip().upper(), hardware_model=payload.hardware_model.strip() if payload.hardware_model else None,
        firmware_version=payload.firmware_version.strip() if payload.firmware_version else None, protocol_version=payload.protocol_version.strip(),
        credential_hash=hashlib.sha256(secret.encode("utf-8")).hexdigest(), registered_by_id=user.id,
        notes=payload.notes.strip() if payload.notes else None)
    db.add(row)
    try:
        db.commit()
        db.refresh(row)
    except Exception:
        db.rollback()
        try:
            disable_device_client(uid)
        except MQTTProvisioningError:
            pass
        raise
    return {"device":_device_out(row),"provisioning_secret":secret,"secret_notice":"Copy this credential now. It is shown only once and cannot be retrieved later."}

@router.patch("/devices/{device_id}")
def update_device(device_id: int, payload: DeviceUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _admin(user)
    row = db.get(AFMSDevice, device_id)
    if not row: raise HTTPException(status_code=404, detail="AFMS device not found")
    changes = payload.model_dump(exclude_unset=True)
    if "is_active" in changes and changes["is_active"] != row.is_active:
        try:
            (enable_device_client if changes["is_active"] else disable_device_client)(row.device_uid)
        except MQTTProvisioningError as exc:
            raise HTTPException(status_code=503, detail=f"MQTT broker status could not be updated: {exc}") from exc
    for field, value in changes.items():
        if isinstance(value, str): value = value.strip()
        if field == 'device_role' and value: value = value.upper()
        setattr(row, field, value)
    try:
        db.commit()
        db.refresh(row)
    except Exception:
        db.rollback()
        if "is_active" in changes and changes["is_active"] != row.is_active:
            try:
                (disable_device_client if changes["is_active"] else enable_device_client)(row.device_uid)
            except MQTTProvisioningError:
                pass
        raise
    return _device_out(row)

@router.post("/devices/{device_id}/rotate-credential")
def rotate_device_credential(device_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _admin(user)
    row = db.get(AFMSDevice, device_id)
    if not row: raise HTTPException(status_code=404, detail="AFMS device not found")
    secret = "afms_" + secrets.token_urlsafe(32)
    try:
        # Password rotation must not re-enable a device that an administrator
        # intentionally disabled. setClientPassword preserves its enabled state.
        set_device_password(row.device_uid, secret)
    except MQTTProvisioningError as exc:
        raise HTTPException(status_code=503, detail=f"MQTT credential rotation failed: {exc}") from exc
    row.credential_hash = hashlib.sha256(secret.encode("utf-8")).hexdigest()
    try:
        db.commit()
    except Exception:
        db.rollback()
        try:
            disable_device_client(row.device_uid)
        except MQTTProvisioningError:
            pass
        raise
    return {"device_id":row.id,"device_uid":row.device_uid,"provisioning_secret":secret,"secret_notice":"Previous credential is invalid immediately. Copy this new credential now; it is shown only once."}
