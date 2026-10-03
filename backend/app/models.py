from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, Enum as SAEnum, ForeignKey, Integer, Numeric,
    String, Text, UniqueConstraint, Index
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .enums import (
    ActionStatus, MonthState, OEEComponent, OperationType,
    Priority, SourceType, UserRole,
)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    full_name: Mapped[str] = mapped_column(String(160))
    role: Mapped[UserRole] = mapped_column(SAEnum(UserRole), default=UserRole.VIEW_ONLY)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class Customer(Base, TimestampMixin):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    products: Mapped[list[Product]] = relationship(back_populates="customer")


class Product(Base, TimestampMixin):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(180), index=True)
    customer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("customers.id"), nullable=True)
    actual_measure: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Product-level reporting attributes. These remain on the master so the
    # same Plant / Group filters work across MIS, process, actions and reports.
    plant: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    product_group: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    finish_weight_kg: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)

    sort_order: Mapped[int] = mapped_column(Integer, default=999)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    customer: Mapped[Optional[Customer]] = relationship(back_populates="products")


class Vendor(Base, TimestampMixin):
    __tablename__ = "vendors"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(180))
    contact_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Operation(Base, TimestampMixin):
    __tablename__ = "operations"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(180))
    operation_type: Mapped[OperationType] = mapped_column(SAEnum(OperationType), default=OperationType.INTERNAL)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Machine(Base, TimestampMixin):
    __tablename__ = "machines"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    machine_type: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    plant: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    department: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    cost_center: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    manufacturer: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    model_number: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    serial_number: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    commissioned_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    pm_done_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    pm_frequency_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    default_manpower_required: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 3), nullable=True)
    rated_power_kw: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 3), nullable=True)
    power_load_factor: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 5), nullable=True)
    air_consumption_cfm: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 3), nullable=True)
    labor_rate_per_operator_hour: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 3), nullable=True)
    electricity_rate_per_kwh: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 3), nullable=True)
    compressed_air_rate_per_1000_cuft: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 3), nullable=True)
    maintenance_cost_per_hour: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 3), nullable=True)
    consumables_cost_per_hour: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 3), nullable=True)
    depreciation_cost_per_hour: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 3), nullable=True)
    other_overhead_cost_per_hour: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 3), nullable=True)
    remarks: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    capacity_per_shift: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 3), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class MachineMasterHistory(Base, TimestampMixin):
    __tablename__ = "machine_master_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id"), index=True)
    change_type: Mapped[str] = mapped_column(String(20))
    snapshot_json: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(String(500))
    changed_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)


class LossCategory(Base, TimestampMixin):
    __tablename__ = "loss_categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(180))
    oee_component: Mapped[OEEComponent] = mapped_column(SAEnum(OEEComponent))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class WorkingCalendar(Base, TimestampMixin):
    __tablename__ = "working_calendar"
    id: Mapped[int] = mapped_column(primary_key=True)
    work_date: Mapped[date] = mapped_column(Date, index=True)
    plant: Mapped[str] = mapped_column(String(120), default="Main Plant")
    is_working_day: Mapped[bool] = mapped_column(Boolean, default=True)
    holiday_name: Mapped[Optional[str]] = mapped_column(String(180), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(String(250), nullable=True)
    __table_args__ = (UniqueConstraint("work_date", "plant", name="uq_work_calendar_date_plant"),)


class WorkingCalendarChangeLog(Base):
    __tablename__ = "working_calendar_change_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    work_date: Mapped[date] = mapped_column(Date, index=True)
    plant: Mapped[str] = mapped_column(String(120), index=True)
    old_is_working_day: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    new_is_working_day: Mapped[bool] = mapped_column(Boolean)
    old_holiday_name: Mapped[Optional[str]] = mapped_column(String(180), nullable=True)
    new_holiday_name: Mapped[Optional[str]] = mapped_column(String(180), nullable=True)
    old_reason: Mapped[Optional[str]] = mapped_column(String(250), nullable=True)
    new_reason: Mapped[Optional[str]] = mapped_column(String(250), nullable=True)
    changed_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class SalesPriceHistory(Base, TimestampMixin):
    __tablename__ = "sales_price_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    effective_from: Mapped[date] = mapped_column(Date, index=True)
    effective_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    reason: Mapped[Optional[str]] = mapped_column(String(250), nullable=True)
    revision_reference: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    source_document: Mapped[Optional[str]] = mapped_column(String(260), nullable=True)
    source: Mapped[str] = mapped_column(String(30), default="MANUAL", nullable=False)
    entered_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    product: Mapped[Product] = relationship()
    __table_args__ = (Index("ix_price_product_effective", "product_id", "effective_from"),)


class RouteVersion(Base, TimestampMixin):
    __tablename__ = "route_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    revision_no: Mapped[int] = mapped_column(Integer, default=0)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String(250), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    product: Mapped[Product] = relationship()
    operations: Mapped[list[RouteOperation]] = relationship(back_populates="route_version", cascade="all, delete-orphan", order_by="RouteOperation.sequence_no")
    __table_args__ = (UniqueConstraint("product_id", "revision_no", name="uq_route_product_revision"),)


class RouteOperation(Base, TimestampMixin):
    __tablename__ = "route_operations"
    id: Mapped[int] = mapped_column(primary_key=True)
    route_version_id: Mapped[int] = mapped_column(ForeignKey("route_versions.id", ondelete="CASCADE"), index=True)
    operation_id: Mapped[int] = mapped_column(ForeignKey("operations.id"), index=True)
    sequence_no: Mapped[int] = mapped_column(Integer)
    source_label: Mapped[Optional[str]] = mapped_column(String(180), nullable=True)
    vendor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("vendors.id"), nullable=True)
    standard_yield: Mapped[Decimal] = mapped_column(Numeric(8, 5), default=Decimal("1"))
    standard_lead_time_days: Mapped[int] = mapped_column(Integer, default=0)
    buffer_qty: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=Decimal("0"))
    is_dispatch: Mapped[bool] = mapped_column(Boolean, default=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    route_version: Mapped[RouteVersion] = relationship(back_populates="operations")
    operation: Mapped[Operation] = relationship()
    vendor: Mapped[Optional[Vendor]] = relationship()
    __table_args__ = (UniqueConstraint("route_version_id", "sequence_no", name="uq_route_sequence"),)


class OperationMachineMap(Base, TimestampMixin):
    __tablename__ = "operation_machine_map"
    id: Mapped[int] = mapped_column(primary_key=True)
    route_operation_id: Mapped[int] = mapped_column(ForeignKey("route_operations.id"), index=True)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id"), index=True)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    reason: Mapped[Optional[str]] = mapped_column(String(250), nullable=True)
    entered_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    route_operation: Mapped[RouteOperation] = relationship()
    machine: Mapped[Machine] = relationship()


class StandardCycleTime(Base, TimestampMixin):
    __tablename__ = "standard_cycle_times"
    id: Mapped[int] = mapped_column(primary_key=True)
    route_operation_id: Mapped[int] = mapped_column(ForeignKey("route_operations.id"), index=True)
    machine_id: Mapped[Optional[int]] = mapped_column(ForeignKey("machines.id"), nullable=True, index=True)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    ideal_cycle_time_sec: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    standard_cycle_time_sec: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 3), nullable=True)
    cavities: Mapped[int] = mapped_column(Integer, default=1)
    pieces_per_cycle: Mapped[int] = mapped_column(Integer, default=1)
    remark: Mapped[Optional[str]] = mapped_column(String(250), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(String(250), nullable=True)
    entered_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)


class OperatorRequirementHistory(Base, TimestampMixin):
    __tablename__ = "operator_requirement_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    route_operation_id: Mapped[int] = mapped_column(ForeignKey("route_operations.id"), index=True)
    machine_id: Mapped[Optional[int]] = mapped_column(ForeignKey("machines.id"), nullable=True, index=True)
    effective_from: Mapped[date] = mapped_column(Date, index=True)
    effective_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    operators_per_machine: Mapped[Decimal] = mapped_column(Numeric(8, 3))
    reason: Mapped[str] = mapped_column(String(250))
    entered_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)


class MachineCapacitySetting(Base, TimestampMixin):
    __tablename__ = "machine_capacity_settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id"), index=True)
    effective_from: Mapped[date] = mapped_column(Date, index=True)
    effective_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    shifts_per_day: Mapped[int] = mapped_column(Integer)
    shift_minutes: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    planned_break_minutes: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0"))
    planning_efficiency: Mapped[Decimal] = mapped_column(Numeric(8, 5), default=Decimal("0.85"))
    reason: Mapped[str] = mapped_column(String(250))
    entered_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)


class MachineMonthlyAllocation(Base, TimestampMixin):
    __tablename__ = "machine_monthly_allocations"
    id: Mapped[int] = mapped_column(primary_key=True)
    month: Mapped[date] = mapped_column(Date, index=True)
    effective_from: Mapped[date] = mapped_column(Date, index=True)
    revision_no: Mapped[int] = mapped_column(Integer)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    route_operation_id: Mapped[int] = mapped_column(ForeignKey("route_operations.id"), index=True)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id"), index=True)
    allocated_qty: Mapped[Decimal] = mapped_column(Numeric(16, 3))
    schedule_qty_snapshot: Mapped[Decimal] = mapped_column(Numeric(16, 3))
    capacity_qty_snapshot: Mapped[Decimal] = mapped_column(Numeric(16, 3))
    planning_cycle_time_sec: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    operators_per_machine_snapshot: Mapped[Decimal] = mapped_column(Numeric(8, 3))
    estimated_hourly_cost_snapshot: Mapped[Optional[Decimal]] = mapped_column(Numeric(16, 3), nullable=True)
    estimated_cost_per_piece_snapshot: Mapped[Optional[Decimal]] = mapped_column(Numeric(16, 6), nullable=True)
    reason: Mapped[str] = mapped_column(Text)
    entered_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    __table_args__ = (
        UniqueConstraint("product_id", "route_operation_id", "month", "revision_no", "machine_id", name="uq_machine_monthly_allocation"),
    )


class ScheduleRevision(Base, TimestampMixin):
    __tablename__ = "schedule_revisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    month: Mapped[date] = mapped_column(Date, index=True)  # first day of month
    revision_no: Mapped[int] = mapped_column(Integer)
    effective_from: Mapped[date] = mapped_column(Date, index=True)
    monthly_target_qty: Mapped[Decimal] = mapped_column(Numeric(16, 3))
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    entered_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    product: Mapped[Product] = relationship()
    __table_args__ = (UniqueConstraint("product_id", "month", "revision_no", name="uq_schedule_product_month_revision"),)


class DailyRequirement(Base, TimestampMixin):
    __tablename__ = "daily_requirements"
    id: Mapped[int] = mapped_column(primary_key=True)
    req_date: Mapped[date] = mapped_column(Date, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    route_operation_id: Mapped[Optional[int]] = mapped_column(ForeignKey("route_operations.id"), nullable=True, index=True)
    schedule_revision_id: Mapped[Optional[int]] = mapped_column(ForeignKey("schedule_revisions.id"), nullable=True)
    baseline_plan_qty: Mapped[Decimal] = mapped_column(Numeric(16, 3), default=Decimal("0"))
    revised_plan_qty: Mapped[Decimal] = mapped_column(Numeric(16, 3), default=Decimal("0"))
    is_frozen: Mapped[bool] = mapped_column(Boolean, default=False)
    product: Mapped[Product] = relationship()
    __table_args__ = (UniqueConstraint("req_date", "product_id", "route_operation_id", name="uq_daily_requirement_context"),)


class DailyMIS(Base, TimestampMixin):
    __tablename__ = "daily_mis"
    id: Mapped[int] = mapped_column(primary_key=True)
    mis_date: Mapped[date] = mapped_column(Date, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    plan_qty: Mapped[Decimal] = mapped_column(Numeric(16, 3), default=Decimal("0"))
    actual_qty: Mapped[Decimal] = mapped_column(Numeric(16, 3), default=Decimal("0"))
    sales_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("0"))
    plan_sales: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    actual_sales: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    schedule_revision_id: Mapped[Optional[int]] = mapped_column(ForeignKey("schedule_revisions.id"), nullable=True)
    source: Mapped[SourceType] = mapped_column(SAEnum(SourceType), default=SourceType.MANUAL)
    remark: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    product: Mapped[Product] = relationship()
    __table_args__ = (UniqueConstraint("mis_date", "product_id", name="uq_daily_mis_date_product"),)


class MISChangeLog(Base):
    __tablename__ = "mis_change_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    mis_id: Mapped[int] = mapped_column(ForeignKey("daily_mis.id"), index=True)
    field_name: Mapped[str] = mapped_column(String(80))
    old_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    new_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reason: Mapped[str] = mapped_column(Text)
    changed_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ProcessDailySummary(Base, TimestampMixin):
    __tablename__ = "process_daily_summary"
    id: Mapped[int] = mapped_column(primary_key=True)
    summary_date: Mapped[date] = mapped_column(Date, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    route_operation_id: Mapped[int] = mapped_column(ForeignKey("route_operations.id"), index=True)
    plan_qty: Mapped[Decimal] = mapped_column(Numeric(16, 3), default=Decimal("0"))
    actual_qty: Mapped[Decimal] = mapped_column(Numeric(16, 3), default=Decimal("0"))
    good_qty: Mapped[Decimal] = mapped_column(Numeric(16, 3), default=Decimal("0"))
    reject_qty: Mapped[Decimal] = mapped_column(Numeric(16, 3), default=Decimal("0"))
    opening_wip: Mapped[Decimal] = mapped_column(Numeric(16, 3), default=Decimal("0"))
    closing_wip: Mapped[Decimal] = mapped_column(Numeric(16, 3), default=Decimal("0"))
    source: Mapped[SourceType] = mapped_column(SAEnum(SourceType), default=SourceType.MANUAL)
    remarks: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    route_operation: Mapped[RouteOperation] = relationship()
    __table_args__ = (UniqueConstraint("summary_date", "product_id", "route_operation_id", name="uq_process_daily_context"),)


class VendorMovement(Base, TimestampMixin):
    __tablename__ = "vendor_movements"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    route_operation_id: Mapped[int] = mapped_column(ForeignKey("route_operations.id"), index=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), index=True)
    outward_date: Mapped[date] = mapped_column(Date, index=True)
    outward_qty: Mapped[Decimal] = mapped_column(Numeric(16, 3))
    challan_no: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    expected_return_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    receipt_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    receipt_qty: Mapped[Decimal] = mapped_column(Numeric(16, 3), default=Decimal("0"))
    reject_qty: Mapped[Decimal] = mapped_column(Numeric(16, 3), default=Decimal("0"))
    remarks: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    __table_args__ = (Index("ix_vendor_product_expected_return", "product_id", "expected_return_date"),)


class MachineShiftProduction(Base, TimestampMixin):
    __tablename__ = "machine_shift_production"
    id: Mapped[int] = mapped_column(primary_key=True)
    production_date: Mapped[date] = mapped_column(Date, index=True)
    shift: Mapped[str] = mapped_column(String(30), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    route_operation_id: Mapped[int] = mapped_column(ForeignKey("route_operations.id"), index=True)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id"), index=True)
    shift_duration_min: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("480"))
    planned_break_min: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    downtime_min: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    total_count: Mapped[Decimal] = mapped_column(Numeric(16, 3), default=Decimal("0"))
    good_count: Mapped[Decimal] = mapped_column(Numeric(16, 3), default=Decimal("0"))
    reject_count: Mapped[Decimal] = mapped_column(Numeric(16, 3), default=Decimal("0"))
    ideal_cycle_time_sec: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=Decimal("0"))
    source: Mapped[SourceType] = mapped_column(SAEnum(SourceType), default=SourceType.MANUAL)
    remarks: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    __table_args__ = (Index("ix_machine_shift_date_machine_product", "production_date", "machine_id", "product_id"),)


class MachineLossEvent(Base, TimestampMixin):
    __tablename__ = "machine_loss_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    loss_date: Mapped[date] = mapped_column(Date, index=True)
    shift: Mapped[str] = mapped_column(String(30), index=True)
    product_id: Mapped[Optional[int]] = mapped_column(ForeignKey("products.id"), nullable=True, index=True)
    route_operation_id: Mapped[Optional[int]] = mapped_column(ForeignKey("route_operations.id"), nullable=True, index=True)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id"), index=True)
    loss_category_id: Mapped[int] = mapped_column(ForeignKey("loss_categories.id"), index=True)
    start_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    duration_min: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    qty_loss: Mapped[Decimal] = mapped_column(Numeric(16, 3), default=Decimal("0"))
    remark: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[SourceType] = mapped_column(SAEnum(SourceType), default=SourceType.MANUAL)
    loss_category: Mapped[LossCategory] = relationship()
    __table_args__ = (Index("ix_machine_loss_date_machine_product", "loss_date", "machine_id", "product_id"),)




class QualityPhenomenon(Base, TimestampMixin):
    __tablename__ = "quality_rejection_phenomena"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(220), index=True)
    normalized_name: Mapped[str] = mapped_column(String(220), unique=True, index=True)
    phenomenon_group: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    default_responsible_team: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    criticality: Mapped[str] = mapped_column(String(40), default="NORMAL", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class QualityRejectionImportBatch(Base, TimestampMixin):
    __tablename__ = "quality_rejection_import_batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    file_name: Mapped[str] = mapped_column(String(260))
    file_sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    import_type: Mapped[str] = mapped_column(String(40), default="DAILY")
    status: Mapped[str] = mapped_column(String(40), default="COMPLETED")
    stats_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    imported_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)


class QualityRejectionDaily(Base, TimestampMixin):
    __tablename__ = "quality_rejection_daily"
    id: Mapped[int] = mapped_column(primary_key=True)
    record_key: Mapped[str] = mapped_column(String(500), unique=True, index=True)
    rejection_date: Mapped[date] = mapped_column(Date, index=True)
    shift: Mapped[str] = mapped_column(String(40), default="General", index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    plant: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    detection_route_operation_id: Mapped[Optional[int]] = mapped_column(ForeignKey("route_operations.id"), nullable=True, index=True)
    responsible_route_operation_id: Mapped[Optional[int]] = mapped_column(ForeignKey("route_operations.id"), nullable=True, index=True)
    responsible_team: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    machine_id: Mapped[Optional[int]] = mapped_column(ForeignKey("machines.id"), nullable=True, index=True)
    phenomenon_id: Mapped[int] = mapped_column(ForeignKey("quality_rejection_phenomena.id"), index=True)
    reject_qty: Mapped[Decimal] = mapped_column(Numeric(16, 3), default=Decimal("0"))
    rework_qty: Mapped[Decimal] = mapped_column(Numeric(16, 3), default=Decimal("0"))
    scrap_qty: Mapped[Decimal] = mapped_column(Numeric(16, 3), default=Decimal("0"))
    denominator_source: Mapped[str] = mapped_column(String(80), default="DISP_DONE")
    denominator_qty: Mapped[Optional[Decimal]] = mapped_column(Numeric(16, 3), nullable=True)
    ppm: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 3), nullable=True)
    remark: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(40), default="EXCEL")
    action_required: Mapped[bool] = mapped_column(Boolean, default=False)
    import_batch_id: Mapped[Optional[int]] = mapped_column(ForeignKey("quality_rejection_import_batches.id"), nullable=True, index=True)
    entered_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    __table_args__ = (
        Index("ix_quality_daily_date_product", "rejection_date", "product_id"),
        Index("ix_quality_daily_date_phenomenon", "rejection_date", "phenomenon_id"),
    )


class QualityRejectionMonthlyHistory(Base, TimestampMixin):
    __tablename__ = "quality_rejection_monthly_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    record_key: Mapped[str] = mapped_column(String(500), unique=True, index=True)
    month: Mapped[date] = mapped_column(Date, index=True)
    source: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    source_sheet: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    record_scope: Mapped[str] = mapped_column(String(60), default="PRODUCT_TOTAL", index=True)
    include_in_aggregate: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    plant: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    detection_operation: Mapped[Optional[str]] = mapped_column(String(180), nullable=True)
    responsible_team: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    responsible_operation: Mapped[Optional[str]] = mapped_column(String(180), nullable=True)
    machine: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    phenomenon_id: Mapped[int] = mapped_column(ForeignKey("quality_rejection_phenomena.id"), index=True)
    reject_qty: Mapped[Decimal] = mapped_column(Numeric(16, 3), default=Decimal("0"))
    denominator_source: Mapped[str] = mapped_column(String(80), default="DISP_DONE")
    dispatch_qty: Mapped[Optional[Decimal]] = mapped_column(Numeric(16, 3), nullable=True)
    ppm: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 3), nullable=True)
    source_production_qty: Mapped[Optional[Decimal]] = mapped_column(Numeric(16, 3), nullable=True)
    source_inspection_qty: Mapped[Optional[Decimal]] = mapped_column(Numeric(16, 3), nullable=True)
    source_total_reject_qty: Mapped[Optional[Decimal]] = mapped_column(Numeric(16, 3), nullable=True)
    phenomenon_sum_reject_qty: Mapped[Optional[Decimal]] = mapped_column(Numeric(16, 3), nullable=True)
    source_reported_ppm: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 3), nullable=True)
    data_quality_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    import_batch_id: Mapped[Optional[int]] = mapped_column(ForeignKey("quality_rejection_import_batches.id"), nullable=True, index=True)
    __table_args__ = (Index("ix_quality_history_month_product_phenomenon", "month", "product_id", "phenomenon_id"),)


class QualityActionLink(Base):
    __tablename__ = "quality_action_links"
    id: Mapped[int] = mapped_column(primary_key=True)
    action_id: Mapped[int] = mapped_column(ForeignKey("actions.id", ondelete="CASCADE"), index=True)
    daily_rejection_id: Mapped[Optional[int]] = mapped_column(ForeignKey("quality_rejection_daily.id", ondelete="CASCADE"), nullable=True, index=True)
    monthly_history_id: Mapped[Optional[int]] = mapped_column(ForeignKey("quality_rejection_monthly_history.id", ondelete="CASCADE"), nullable=True, index=True)
    __table_args__ = (UniqueConstraint("action_id", "daily_rejection_id", "monthly_history_id", name="uq_quality_action_link"),)


class Action(Base, TimestampMixin):
    __tablename__ = "actions"
    id: Mapped[int] = mapped_column(primary_key=True)
    action_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    raised_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    reference_date: Mapped[date] = mapped_column(Date, index=True)
    problem_category: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    problem_description: Mapped[str] = mapped_column(Text)
    action_description: Mapped[str] = mapped_column(Text)
    owner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    priority: Mapped[Priority] = mapped_column(SAEnum(Priority), default=Priority.MEDIUM)
    status: Mapped[ActionStatus] = mapped_column(SAEnum(ActionStatus), default=ActionStatus.OPEN, index=True)
    kpi_type: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    kpi_value_when_raised: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), nullable=True)
    gap_when_raised: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    closure_remark: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    effectiveness_status: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    contexts: Mapped[list[ActionContext]] = relationship(back_populates="action", cascade="all, delete-orphan")
    history: Mapped[list[ActionHistory]] = relationship(back_populates="action", cascade="all, delete-orphan")


class ActionWhyWhy(Base, TimestampMixin):
    __tablename__ = "action_whywhy"
    id: Mapped[int] = mapped_column(primary_key=True)
    action_id: Mapped[int] = mapped_column(ForeignKey("actions.id", ondelete="CASCADE"), unique=True, index=True)
    containment_action: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    why1: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    why2: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    why3: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    why4: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    why5: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    root_cause: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    corrective_action: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    preventive_action: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    verification_method: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    verification_result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    effectiveness_check_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    effectiveness_result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    lessons_learned: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[Action] = relationship()


class ActionAttachment(Base, TimestampMixin):
    __tablename__ = "action_attachments"
    id: Mapped[int] = mapped_column(primary_key=True)
    action_id: Mapped[int] = mapped_column(ForeignKey("actions.id", ondelete="CASCADE"), index=True)
    file_name: Mapped[str] = mapped_column(String(260))
    stored_name: Mapped[str] = mapped_column(String(260))
    relative_path: Mapped[str] = mapped_column(String(500))
    mime_type: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    caption: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    uploaded_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[Action] = relationship()


class ActionContext(Base):
    __tablename__ = "action_contexts"
    id: Mapped[int] = mapped_column(primary_key=True)
    action_id: Mapped[int] = mapped_column(ForeignKey("actions.id", ondelete="CASCADE"), index=True)
    context_date: Mapped[date] = mapped_column(Date, index=True)
    product_id: Mapped[Optional[int]] = mapped_column(ForeignKey("products.id"), nullable=True, index=True)
    route_operation_id: Mapped[Optional[int]] = mapped_column(ForeignKey("route_operations.id"), nullable=True, index=True)
    machine_id: Mapped[Optional[int]] = mapped_column(ForeignKey("machines.id"), nullable=True, index=True)
    loss_event_id: Mapped[Optional[int]] = mapped_column(ForeignKey("machine_loss_events.id"), nullable=True)
    vendor_movement_id: Mapped[Optional[int]] = mapped_column(ForeignKey("vendor_movements.id"), nullable=True)
    action: Mapped[Action] = relationship(back_populates="contexts")


class ActionHistory(Base):
    __tablename__ = "action_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    action_id: Mapped[int] = mapped_column(ForeignKey("actions.id", ondelete="CASCADE"), index=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    changed_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    old_status: Mapped[Optional[ActionStatus]] = mapped_column(SAEnum(ActionStatus), nullable=True)
    new_status: Mapped[Optional[ActionStatus]] = mapped_column(SAEnum(ActionStatus), nullable=True)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    kpi_value_at_followup: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), nullable=True)
    gap_at_followup: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), nullable=True)
    attachment_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    action: Mapped[Action] = relationship(back_populates="history")


class ReviewSession(Base, TimestampMixin):
    __tablename__ = "review_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    review_date: Mapped[date] = mapped_column(Date, index=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    participants: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    total_sales_gap: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    comments: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class ReviewActionLink(Base):
    __tablename__ = "review_action_links"
    id: Mapped[int] = mapped_column(primary_key=True)
    review_session_id: Mapped[int] = mapped_column(ForeignKey("review_sessions.id", ondelete="CASCADE"), index=True)
    action_id: Mapped[int] = mapped_column(ForeignKey("actions.id", ondelete="CASCADE"), index=True)
    __table_args__ = (UniqueConstraint("review_session_id", "action_id", name="uq_review_action"),)


class MonthStatus(Base, TimestampMixin):
    __tablename__ = "month_status"
    id: Mapped[int] = mapped_column(primary_key=True)
    month: Mapped[date] = mapped_column(Date, unique=True, index=True)
    status: Mapped[MonthState] = mapped_column(SAEnum(MonthState), default=MonthState.OPEN)
    closed_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    remark: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

class ImportBatch(Base, TimestampMixin):
    __tablename__ = "import_batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    file_name: Mapped[str] = mapped_column(String(260))
    file_sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    imported_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="COMPLETED")
    stats_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class GovernanceAudit(Base):
    __tablename__ = "governance_audit"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    event: Mapped[str] = mapped_column(String(80), index=True)
    entity: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    month: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    reason: Mapped[str] = mapped_column(Text)
    before_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    after_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class HistoricalCorrectionGrant(Base):
    __tablename__ = "historical_correction_grants"
    id: Mapped[int] = mapped_column(primary_key=True)
    month: Mapped[date] = mapped_column(Date, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    approved_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class VendorReceipt(Base, TimestampMixin):
    __tablename__ = 'vendor_receipts'
    id: Mapped[int] = mapped_column(primary_key=True)
    movement_id: Mapped[int] = mapped_column(ForeignKey('vendor_movements.id'), index=True)
    receipt_date: Mapped[date] = mapped_column(Date)
    receipt_qty: Mapped[Decimal] = mapped_column(Numeric(16, 3))
    reject_qty: Mapped[Decimal] = mapped_column(Numeric(16, 3), default=Decimal('0'))
    reference: Mapped[str] = mapped_column(String(160))
    entered_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey('users.id'), nullable=True)
    remarks: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    __table_args__ = (UniqueConstraint('movement_id', 'reference', name='uq_vendor_receipt_reference'),)


class ActionReminder(Base):
    __tablename__ = 'action_reminders'
    id: Mapped[int] = mapped_column(primary_key=True)
    action_id: Mapped[int] = mapped_column(ForeignKey('actions.id'), index=True)
    reminder_date: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(60))
    level: Mapped[str] = mapped_column(String(60))
    message: Mapped[str] = mapped_column(Text)
    acknowledged_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey('users.id'), nullable=True)
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    __table_args__ = (UniqueConstraint('action_id', 'reminder_date', 'kind', name='uq_action_reminder_day'),)


class ProcessFlowVersion(Base, TimestampMixin):
    __tablename__ = 'process_flow_versions'
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey('products.id'))
    route_version_id: Mapped[int] = mapped_column(ForeignKey('route_versions.id'), unique=True)
    effective_from: Mapped[date] = mapped_column(Date)
    revision_no: Mapped[int] = mapped_column(Integer)
    company: Mapped[Optional[str]] = mapped_column(String(180), nullable=True)
    definition_sha256: Mapped[str] = mapped_column(String(64))
    source_document: Mapped[str] = mapped_column(String(260))
    reason: Mapped[str] = mapped_column(Text)
    __table_args__ = (UniqueConstraint('product_id','revision_no',name='uq_flow_product_revision'),)


class ProcessFlowStage(Base, TimestampMixin):
    __tablename__ = 'process_flow_stages'
    id: Mapped[int] = mapped_column(primary_key=True)
    flow_id: Mapped[int] = mapped_column(ForeignKey('process_flow_versions.id'))
    code: Mapped[str] = mapped_column(String(180))
    name: Mapped[str] = mapped_column(String(180))
    route_operation_id: Mapped[Optional[int]] = mapped_column(ForeignKey('route_operations.id'), nullable=True, unique=True)
    source_column: Mapped[str] = mapped_column(String(10))
    role: Mapped[str] = mapped_column(String(40))
    branch: Mapped[str] = mapped_column(String(180))
    variant: Mapped[str] = mapped_column(String(120))
    vendor_name: Mapped[str] = mapped_column(String(180))
    predecessors_json: Mapped[str] = mapped_column(Text)
    alias_of: Mapped[str] = mapped_column(String(180))
    is_active: Mapped[bool] = mapped_column(Boolean)
    parent_dispatch: Mapped[bool] = mapped_column(Boolean)
    sequence_no: Mapped[int] = mapped_column(Integer)
    __table_args__ = (UniqueConstraint('flow_id','code',name='uq_flow_stage_code'),)


class StageScheduleAllocation(Base, TimestampMixin):
    __tablename__ = 'stage_schedule_allocations'
    id: Mapped[int] = mapped_column(primary_key=True)
    stage_id: Mapped[int] = mapped_column(ForeignKey('process_flow_stages.id'))
    month: Mapped[date] = mapped_column(Date)
    effective_from: Mapped[date] = mapped_column(Date)
    revision_no: Mapped[int] = mapped_column(Integer)
    allocated_qty: Mapped[Decimal] = mapped_column(Numeric(16, 3))
    working_dates_json: Mapped[str] = mapped_column(Text)
    distribution_json: Mapped[str] = mapped_column(Text)
    reference: Mapped[str] = mapped_column(String(160))
    reason: Mapped[str] = mapped_column(Text)
    __table_args__ = (UniqueConstraint('stage_id','month','revision_no',name='uq_stage_schedule_revision'),)


class ShopCapture(Base, TimestampMixin):
    __tablename__ = 'shop_captures'
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    file_sha256: Mapped[str] = mapped_column(String(64))
    source_name: Mapped[str] = mapped_column(String(260))
    image_path: Mapped[str] = mapped_column(String(260))
    original_text: Mapped[str] = mapped_column(Text)
    draft_json: Mapped[str] = mapped_column(Text)
    history_json: Mapped[str] = mapped_column(Text, default='[]')
    receipt_json: Mapped[str] = mapped_column(Text, default='[]')
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(30), default='draft')
    __table_args__ = (UniqueConstraint('owner_id', 'file_sha256', name='uq_capture_owner_hash'),)


class BusinessDataRevision(Base):
    __tablename__ = 'business_data_revision'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
