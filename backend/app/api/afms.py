
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..models import Machine, User

router = APIRouter(prefix="/afms", tags=["AFMS"])


@router.get("/overview")
def overview(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Initial AFMS module endpoint; reports existing machine-master readiness only."""
    total = db.scalar(select(func.count(Machine.id))) or 0
    active = db.scalar(select(func.count(Machine.id)).where(Machine.is_active.is_(True))) or 0
    return {
        "module": "AFMS",
        "status": "INITIALIZED",
        "integration_status": "NOT_CONNECTED",
        "machine_master": {"total": total, "active": active},
        "devices": {"registered": 0, "online": 0},
        "telemetry": {"status": "NOT_CONNECTED", "last_received_at": None},
        "next_phase": "Device registry and secure device authentication",
    }


@router.get("/machines")
def afms_machines(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Read-only view of PRW machines for the AFMS integration workspace."""
    rows = db.scalars(select(Machine).order_by(Machine.plant, Machine.code)).all()
    return [
        {
            "id": row.id,
            "code": row.code,
            "name": row.name,
            "plant": row.plant,
            "department": row.department,
            "machine_type": row.machine_type,
            "is_active": row.is_active,
            "device_status": "NOT_REGISTERED",
        }
        for row in rows
    ]
