"""Atomic machine/operation setup with field-level revision detection."""
from datetime import date
from decimal import Decimal

from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Machine, RouteOperation, OperationMachineMap, StandardCycleTime,
    OperatorRequirementHistory, MachineCapacitySetting,
)
from .capacity import close_previous_revision


class CompleteMachineSetup(BaseModel):
    route_operation_id: int
    machine_id: int
    effective_from: date
    priority: int = Field(ge=1)
    ideal_cycle_time_sec: Decimal = Field(gt=0)
    standard_cycle_time_sec: Decimal | None = Field(default=None, gt=0)
    pieces_per_cycle: int = Field(ge=1)
    operators_per_machine: Decimal = Field(gt=0, le=100)
    shifts_per_day: int = Field(ge=1, le=6)
    shift_minutes: Decimal = Field(gt=0, le=1440)
    planned_break_minutes: Decimal = Field(ge=0, le=1440)
    planning_efficiency: Decimal = Field(gt=0, le=1)
    reason: str = Field(min_length=2, max_length=250)

    @model_validator(mode="after")
    def valid_shift(self):
        if self.planned_break_minutes >= self.shift_minutes:
            raise ValueError("Break minutes must be less than shift minutes")
        return self


GROUPS = (
    ("mapping", OperationMachineMap, ("route_operation_id", "machine_id"), ("priority",)),
    ("cycle", StandardCycleTime, ("route_operation_id", "machine_id"),
     ("ideal_cycle_time_sec", "standard_cycle_time_sec", "pieces_per_cycle")),
    ("operator", OperatorRequirementHistory, ("route_operation_id", "machine_id"),
     ("operators_per_machine",)),
    ("capacity", MachineCapacitySetting, ("machine_id",),
     ("shifts_per_day", "shift_minutes", "planned_break_minutes", "planning_efficiency")),
)


def _current(db: Session, model, filters: dict, effective_from: date):
    return db.scalar(select(model).where(
        *(getattr(model, field) == value for field, value in filters.items()),
        model.effective_from <= effective_from,
        (model.effective_to.is_(None) | (model.effective_to >= effective_from)),
    ).order_by(model.effective_from.desc(), model.id.desc()).limit(1))


def complete_setup(db: Session, payload: CompleteMachineSetup, user_id: int):
    if not db.get(Machine, payload.machine_id) or not db.get(RouteOperation, payload.route_operation_id):
        raise HTTPException(404, "Machine or product operation not found")
    # Serialize saves to the same machine, including two sessions editing different operations.
    db.execute(select(Machine.id).where(Machine.id == payload.machine_id).with_for_update()).all()
    changed, unchanged = [], []
    # Validate every proposed revision before modifying any history.
    plans = []
    for name, model, keys, fields in GROUPS:
        filters = {field: getattr(payload, field) for field in keys}
        latest = db.scalar(select(model).where(
            *(getattr(model, field) == value for field, value in filters.items())
        ).order_by(model.effective_from.desc(), model.id.desc()).limit(1))
        current = _current(db, model, filters, payload.effective_from)
        values = {field: getattr(payload, field) for field in fields}
        different = current is None or any(
            (Decimal(str(getattr(current, field))) != Decimal(str(value))
             if value is not None and getattr(current, field) is not None
             and isinstance(value, (int, Decimal))
             else getattr(current, field) != value)
            for field, value in values.items()
        )
        # An earlier date must never rewrite or fork an effective-dated master.
        if different and latest and latest.effective_from >= payload.effective_from:
            raise HTTPException(409, f"{name.title()} has a revision on or after the selected effective date; choose a later date")
        plans.append((name, model, filters, values, different))
    for name, model, filters, values, different in plans:
        if not different:
            unchanged.append(name)
            continue
        close_previous_revision(
            db, model, payload.effective_from,
            *(getattr(model, field) == value for field, value in filters.items()),
        )
        db.add(model(**filters, **values, effective_from=payload.effective_from,
                     reason=payload.reason, entered_by_id=user_id))
        changed.append(name)
    db.flush()
    return {"changed": changed, "unchanged": unchanged, "no_changes": not changed}
