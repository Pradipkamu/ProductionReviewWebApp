from __future__ import annotations

import calendar
import math
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import (
    DailyMIS, DailyRequirement, Product, RouteOperation, RouteVersion,
    ScheduleRevision, WorkingCalendar,
)


ZERO = Decimal("0")


def month_bounds(month: date) -> tuple[date, date]:
    first = month.replace(day=1)
    last = date(first.year, first.month, calendar.monthrange(first.year, first.month)[1])
    return first, last


def is_working_day(db: Session, d: date, plant: str | None = None) -> bool:
    plant = plant or get_settings().plant_name
    row = db.scalar(select(WorkingCalendar).where(WorkingCalendar.work_date == d, WorkingCalendar.plant == plant))
    if row is not None:
        return bool(row.is_working_day)
    # Default only when no calendar row exists. This is intentionally conservative:
    # Sunday off; Mon-Sat working. Plant calendar can override any date.
    return d.weekday() != 6


def working_days(db: Session, start: date, end: date, plant: str | None = None) -> list[date]:
    days: list[date] = []
    d = start
    while d <= end:
        if is_working_day(db, d, plant):
            days.append(d)
        d += timedelta(days=1)
    return days


def product_plant(db: Session, product_id: int) -> str:
    plant = db.scalar(select(Product.plant).where(Product.id == product_id))
    return str(plant) if plant else get_settings().plant_name


def split_integer_quantity(total: Decimal, days: list[date]) -> dict[date, Decimal]:
    if not days:
        return {}
    # Production schedules are normally pieces. Keep an exact integer total while
    # distributing the remainder to the earliest working days.
    total_i = max(0, int(round(float(total))))
    q, r = divmod(total_i, len(days))
    return {d: Decimal(q + (1 if i < r else 0)) for i, d in enumerate(days)}


def actual_before(db: Session, product_id: int, d: date) -> Decimal:
    val = db.scalar(
        select(func.coalesce(func.sum(DailyMIS.actual_qty), 0)).where(
            DailyMIS.product_id == product_id,
            DailyMIS.mis_date < d,
            DailyMIS.mis_date >= d.replace(day=1),
        )
    )
    return Decimal(str(val or 0))


def active_schedule_revision(db: Session, product_id: int, d: date) -> ScheduleRevision | None:
    month = d.replace(day=1)
    return db.scalar(
        select(ScheduleRevision)
        .where(
            ScheduleRevision.product_id == product_id,
            ScheduleRevision.month == month,
            ScheduleRevision.effective_from <= d,
        )
        .order_by(ScheduleRevision.effective_from.desc(), ScheduleRevision.revision_no.desc())
        .limit(1)
    )


def next_revision_no(db: Session, product_id: int, month: date) -> int:
    month = month.replace(day=1)
    max_rev = db.scalar(
        select(func.coalesce(func.max(ScheduleRevision.revision_no), -1)).where(
            ScheduleRevision.product_id == product_id,
            ScheduleRevision.month == month,
        )
    )
    return int(max_rev) + 1


def preview_revision(db: Session, product_id: int, effective_from: date, monthly_target_qty: Decimal) -> dict:
    first, last = month_bounds(effective_from)
    completed = actual_before(db, product_id, effective_from)
    balance = max(ZERO, Decimal(str(monthly_target_qty)) - completed)
    remaining_days = working_days(db, effective_from, last, product_plant(db, product_id))
    dist = split_integer_quantity(balance, remaining_days)
    current = active_schedule_revision(db, product_id, effective_from)
    return {
        "month": first.isoformat(),
        "effective_from": effective_from.isoformat(),
        "current_target": float(current.monthly_target_qty) if current else None,
        "new_target": float(monthly_target_qty),
        "actual_before_effective_date": float(completed),
        "balance_requirement": float(balance),
        "remaining_working_days": len(remaining_days),
        "average_daily_requirement": float(balance / len(remaining_days)) if remaining_days else 0,
        "preview": [{"date": d.isoformat(), "qty": float(q)} for d, q in dist.items()],
    }


def apply_schedule_revision(
    db: Session,
    revision: ScheduleRevision,
    preserve_before: date | None = None,
) -> None:
    """Apply a schedule revision from its effective date forward only.

    Baseline plan is never overwritten. Existing revised plans before the revision
    effective date remain untouched. This is the core versioning rule requested
    for historical review integrity.
    """
    _, last = month_bounds(revision.month)
    start = max(revision.effective_from, preserve_before or revision.effective_from)
    completed = actual_before(db, revision.product_id, revision.effective_from)
    balance = max(ZERO, Decimal(str(revision.monthly_target_qty)) - completed)
    days = working_days(db, revision.effective_from, last, product_plant(db, revision.product_id))
    distribution = split_integer_quantity(balance, days)

    # Dispatch-level requirement: route_operation_id = NULL.
    rows = db.scalars(
        select(DailyRequirement).where(
            DailyRequirement.product_id == revision.product_id,
            DailyRequirement.req_date >= start,
            DailyRequirement.req_date <= last,
            DailyRequirement.route_operation_id.is_(None),
        )
    ).all()
    existing = {r.req_date: r for r in rows}

    d = start
    while d <= last:
        row = existing.get(d)
        qty = distribution.get(d, ZERO)
        if row is None:
            # If no imported baseline exists, baseline starts as zero. This keeps
            # "original plan" and "revised requirement" conceptually separate.
            row = DailyRequirement(
                req_date=d,
                product_id=revision.product_id,
                route_operation_id=None,
                baseline_plan_qty=ZERO,
                revised_plan_qty=qty,
                schedule_revision_id=revision.id,
            )
            db.add(row)
        elif not row.is_frozen:
            row.revised_plan_qty = qty
            row.schedule_revision_id = revision.id
        d += timedelta(days=1)

    db.flush()
    rebuild_process_requirements(db, revision.product_id, revision.month, start_date=start)


def get_active_route(db: Session, product_id: int, d: date) -> RouteVersion | None:
    return db.scalar(
        select(RouteVersion)
        .where(
            RouteVersion.product_id == product_id,
            RouteVersion.effective_from <= d,
            or_(RouteVersion.effective_to.is_(None), RouteVersion.effective_to >= d),
            RouteVersion.is_active.is_(True),
        )
        .order_by(RouteVersion.revision_no.desc())
        .limit(1)
    )


def subtract_working_days(db: Session, d: date, n: int, plant: str | None = None) -> date:
    cur = d
    remaining = max(0, n)
    while remaining > 0:
        cur -= timedelta(days=1)
        if is_working_day(db, cur, plant):
            remaining -= 1
    return cur


def rebuild_process_requirements(db: Session, product_id: int, month: date, start_date: date | None = None) -> None:
    """Propagate dispatch requirement backwards through the route.

    Yield and lead-time fields are optional masters. With default yield=1 and
    lead time=0 the process plan mirrors dispatch. As masters mature, this same
    engine automatically creates upstream requirements.
    """
    first, last = month_bounds(month)
    start = max(first, start_date or first)
    dispatch_rows = db.scalars(
        select(DailyRequirement).where(
            DailyRequirement.product_id == product_id,
            DailyRequirement.req_date >= start,
            DailyRequirement.req_date <= last,
            DailyRequirement.route_operation_id.is_(None),
        )
    ).all()
    if not dispatch_rows:
        return

    # Delete only non-frozen process calculations from the recalculation window.
    obsolete = db.scalars(
        select(DailyRequirement).where(
            DailyRequirement.product_id == product_id,
            DailyRequirement.req_date >= start,
            DailyRequirement.req_date <= last,
            DailyRequirement.route_operation_id.is_not(None),
            DailyRequirement.is_frozen.is_(False),
        )
    ).all()
    for requirement in obsolete:
        db.delete(requirement)
    db.flush()

    bucket: dict[tuple[date, int], Decimal] = defaultdict(lambda: ZERO)
    plant = product_plant(db, product_id)
    for dr in dispatch_rows:
        route = get_active_route(db, product_id, dr.req_date)
        if not route:
            continue
        ops = db.scalars(
            select(RouteOperation)
            .where(RouteOperation.route_version_id == route.id, RouteOperation.is_enabled.is_(True))
            .order_by(RouteOperation.sequence_no)
        ).all()
        if not ops:
            continue
        downstream_qty = Decimal(str(dr.revised_plan_qty))
        cumulative_lead = 0
        for op in reversed(ops):
            y = Decimal(str(op.standard_yield or 1))
            if y <= 0 or y > 1:
                y = Decimal("1")
            required = Decimal(math.ceil(float(downstream_qty / y)))
            due_date = subtract_working_days(db, dr.req_date, cumulative_lead, plant)
            if first <= due_date <= last:
                bucket[(due_date, op.id)] += required
            downstream_qty = required
            cumulative_lead += max(0, int(op.standard_lead_time_days or 0))

    for (req_date, op_id), qty in bucket.items():
        db.add(DailyRequirement(
            req_date=req_date,
            product_id=product_id,
            route_operation_id=op_id,
            baseline_plan_qty=ZERO,
            revised_plan_qty=qty,
            schedule_revision_id=active_schedule_revision(db, product_id, req_date).id if active_schedule_revision(db, product_id, req_date) else None,
        ))
    db.flush()


def recovery_required_per_day(db: Session, product_id: int, as_of: date) -> Decimal:
    revision = active_schedule_revision(db, product_id, as_of)
    if not revision:
        return ZERO
    actual_to_date = db.scalar(
        select(func.coalesce(func.sum(DailyMIS.actual_qty), 0)).where(
            DailyMIS.product_id == product_id,
            DailyMIS.mis_date >= as_of.replace(day=1),
            DailyMIS.mis_date <= as_of,
        )
    )
    balance = max(ZERO, Decimal(str(revision.monthly_target_qty)) - Decimal(str(actual_to_date or 0)))
    _, last = month_bounds(as_of)
    days = working_days(db, as_of + timedelta(days=1), last, product_plant(db, product_id))
    return balance / len(days) if days else ZERO
