from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import ActionStatus, OperationType, Priority, SourceType


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict[str, Any]


class LoginRequest(BaseModel):
    username: str
    password: str


class ProductOut(ORMModel):
    id: int
    code: str
    name: str
    customer_id: Optional[int]
    actual_measure: Optional[str]
    plant: Optional[str]
    product_group: Optional[str]
    finish_weight_kg: Optional[Decimal]
    sort_order: int
    is_active: bool


class ProductMasterUpdate(BaseModel):
    plant: Optional[str] = None
    product_group: Optional[str] = None
    finish_weight_kg: Optional[Decimal] = Field(default=None, ge=0)


class MasterCreate(BaseModel):
    code: str
    name: str


class ScheduleRevisionCreate(BaseModel):
    product_id: int
    month: date
    effective_from: date
    monthly_target_qty: Decimal = Field(gt=0)
    reason: Optional[str] = None
    correct_imported_plans: bool = False


class SchedulePreviewRequest(BaseModel):
    product_id: int
    effective_from: date
    monthly_target_qty: Decimal = Field(gt=0)
    correct_imported_plans: bool = False




class SalesPriceRevisionCreate(BaseModel):
    product_id: int
    effective_from: date
    price: Decimal = Field(gt=0)
    reason: str = Field(min_length=2)


class CalendarBulkUpdate(BaseModel):
    plant: str = "Main Plant"
    start_date: date
    end_date: date
    mode: str = Field(pattern="^(SUNDAYS_OFF|SET_OFF|SET_WORKING)$")
    holiday_name: Optional[str] = None
    reason: str = Field(min_length=2)


class MISEdit(BaseModel):
    actual_qty: Decimal = Field(ge=0)
    reason: str = Field(min_length=2)
    remark: Optional[str] = None


class ProcessEntry(BaseModel):
    summary_date: date
    product_id: int
    route_operation_id: int
    plan_qty: Decimal = Decimal("0")
    actual_qty: Decimal = Decimal("0")
    good_qty: Decimal = Decimal("0")
    reject_qty: Decimal = Decimal("0")
    opening_wip: Decimal = Decimal("0")
    closing_wip: Decimal = Decimal("0")
    remarks: Optional[str] = None
    source: SourceType = SourceType.MANUAL


class ActionContextIn(BaseModel):
    context_date: date
    product_id: Optional[int] = None
    route_operation_id: Optional[int] = None
    machine_id: Optional[int] = None
    loss_event_id: Optional[int] = None
    vendor_movement_id: Optional[int] = None


class ActionCreate(BaseModel):
    reference_date: date
    problem_category: Optional[str] = None
    problem_description: str
    action_description: str
    owner_id: Optional[int] = None
    due_at: Optional[datetime] = None
    priority: Priority = Priority.MEDIUM
    kpi_type: Optional[str] = None
    kpi_value_when_raised: Optional[Decimal] = None
    gap_when_raised: Optional[Decimal] = None
    contexts: list[ActionContextIn] = []


class ActionUpdate(BaseModel):
    status: Optional[ActionStatus] = None
    action_description: Optional[str] = None
    owner_id: Optional[int] = None
    due_at: Optional[datetime] = None
    priority: Optional[Priority] = None
    comment: Optional[str] = None
    closure_remark: Optional[str] = None
    effectiveness_status: Optional[str] = None
    kpi_value_at_followup: Optional[Decimal] = None
    gap_at_followup: Optional[Decimal] = None


class ActionWhyWhyUpdate(BaseModel):
    containment_action: Optional[str] = None
    why1: Optional[str] = None
    why2: Optional[str] = None
    why3: Optional[str] = None
    why4: Optional[str] = None
    why5: Optional[str] = None
    root_cause: Optional[str] = None
    corrective_action: Optional[str] = None
    preventive_action: Optional[str] = None
    verification_method: Optional[str] = None
    verification_result: Optional[str] = None
    effectiveness_check_date: Optional[date] = None
    effectiveness_result: Optional[str] = None
    lessons_learned: Optional[str] = None



class MachineEntryCreate(BaseModel):
    production_date: date
    shift: str = Field(min_length=1, max_length=30)
    product_id: int
    route_operation_id: int
    machine_id: int
    shift_duration_min: Decimal = Field(default=Decimal("480"), gt=0)
    planned_break_min: Decimal = Field(default=Decimal("0"), ge=0)
    downtime_min: Decimal = Field(default=Decimal("0"), ge=0)
    total_count: Decimal = Field(default=Decimal("0"), ge=0)
    good_count: Decimal = Field(default=Decimal("0"), ge=0)
    reject_count: Decimal = Field(default=Decimal("0"), ge=0)
    # Zero means "resolve the effective standard from the master". The API never
    # persists zero, so OEE cannot silently calculate with a missing cycle time.
    ideal_cycle_time_sec: Decimal = Field(default=Decimal("0"), ge=0)
    remarks: Optional[str] = None

    @model_validator(mode="after")
    def validate_counts_and_time(self):
        planned = self.shift_duration_min - self.planned_break_min
        if planned <= 0:
            raise ValueError("Planned break must be less than shift duration")
        if self.downtime_min > planned:
            raise ValueError("Downtime cannot exceed planned production time")
        if self.good_count > self.total_count:
            raise ValueError("Good count cannot exceed total count")
        if self.reject_count > self.total_count:
            raise ValueError("Reject count cannot exceed total count")
        if self.good_count + self.reject_count > self.total_count:
            raise ValueError("Good count plus reject count cannot exceed total count")
        self.shift = self.shift.strip().upper()
        return self


class LossEventCreate(BaseModel):
    loss_date: date
    shift: str = Field(min_length=1, max_length=30)
    product_id: Optional[int] = None
    route_operation_id: Optional[int] = None
    machine_id: int
    loss_category_id: int
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_min: Decimal = Field(gt=0)
    qty_loss: Decimal = Field(default=Decimal("0"), ge=0)
    remark: Optional[str] = None

    @model_validator(mode="after")
    def validate_times(self):
        if self.start_time and self.end_time and self.end_time <= self.start_time:
            raise ValueError("Loss end time must be after start time")
        self.shift = self.shift.strip().upper()
        return self

class VendorMovementCreate(BaseModel):
    product_id: int
    route_operation_id: int
    vendor_id: int
    outward_date: date
    outward_qty: Decimal = Field(gt=0)
    challan_no: Optional[str] = None
    expected_return_date: Optional[date] = None
    receipt_date: Optional[date] = None
    receipt_qty: Decimal = Decimal("0")
    reject_qty: Decimal = Decimal("0")
    remarks: Optional[str] = None


class RouteOperationCreate(BaseModel):
    operation_id: int
    sequence_no: int
    vendor_id: Optional[int] = None
    standard_yield: Decimal = Field(default=Decimal("1"), gt=0, le=1)
    standard_lead_time_days: int = Field(default=0, ge=0)
    buffer_qty: Decimal = Decimal("0")
    is_dispatch: bool = False


class RouteVersionCreate(BaseModel):
    effective_from: date
    description: Optional[str] = None
    operations: list[RouteOperationCreate]


class MachineMapCreate(BaseModel):
    route_operation_id: int
    machine_id: int
    effective_from: date
    effective_to: Optional[date] = None
    priority: int = 1


class CycleTimeCreate(BaseModel):
    route_operation_id: int
    machine_id: Optional[int] = None
    effective_from: date
    effective_to: Optional[date] = None
    ideal_cycle_time_sec: Decimal = Field(gt=0)
    standard_cycle_time_sec: Optional[Decimal] = None
    cavities: int = Field(default=1, ge=1)
    pieces_per_cycle: int = Field(default=1, ge=1)
    remark: Optional[str] = None


class CalendarUpsert(BaseModel):
    work_date: date
    plant: str = "Main Plant"
    is_working_day: bool
    holiday_name: Optional[str] = None
    reason: Optional[str] = None


class ReviewStart(BaseModel):
    review_date: date
    participants: Optional[str] = None
    comments: Optional[str] = None


class ReviewClose(BaseModel):
    comments: Optional[str] = None

class UserCreate(BaseModel):
    username: str = Field(min_length=2)
    full_name: str = Field(min_length=2)
    password: str = Field(min_length=8)
    role: str = "VIEW_ONLY"
