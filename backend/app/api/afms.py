from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..enums import UserRole
from ..models import AFMSDevice, Machine, User
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
