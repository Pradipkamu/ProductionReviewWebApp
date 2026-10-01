from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..models import (
    DailyRequirement,
    ProcessFlowStage,
    ProcessFlowVersion,
    Product,
    ScheduleRevision,
    StageScheduleAllocation,
    User,
)
from ..schemas import SchedulePreviewRequest, ScheduleRevisionCreate
from ..services.planning import (
    ZERO,
    apply_schedule_revision,
    month_bounds,
    next_revision_no,
    product_plant,
    split_integer_quantity,
    working_days,
)

router = APIRouter(prefix="/schedules", tags=["schedules"])


def _parent_dispatch_stage(db: Session, product_id: int, d: date) -> ProcessFlowStage | None:
    """Return the active explicit parent-dispatch stage (normally Disp_Done)."""
    flow = db.scalar(
        select(ProcessFlowVersion)
        .where(
            ProcessFlowVersion.product_id == product_id,
            ProcessFlowVersion.effective_from <= d,
        )
        .order_by(ProcessFlowVersion.effective_from.desc(), ProcessFlowVersion.revision_no.desc())
        .limit(1)
    )
    if not flow:
        return None
    return db.scalar(
        select(ProcessFlowStage).where(
            ProcessFlowStage.flow_id == flow.id,
            ProcessFlowStage.parent_dispatch.is_(True),
            ProcessFlowStage.is_active.is_(True),
            ProcessFlowStage.route_operation_id.is_not(None),
        )
    )


def _parent_dispatch_stage_ids(db: Session, product_id: int) -> list[int]:
    return list(
        db.scalars(
            select(ProcessFlowStage.id)
            .join(ProcessFlowVersion, ProcessFlowVersion.id == ProcessFlowStage.flow_id)
            .where(
                ProcessFlowVersion.product_id == product_id,
                ProcessFlowStage.parent_dispatch.is_(True),
                ProcessFlowStage.is_active.is_(True),
            )
        ).all()
    )


def _issued_dispatch_plan_before(db: Session, product_id: int, start: date, end_exclusive: date) -> Decimal:
    total = ZERO
    d = start
    while d < end_exclusive:
        stage = _parent_dispatch_stage(db, product_id, d)
        if stage and stage.route_operation_id:
            qty = db.scalar(
                select(DailyRequirement.revised_plan_qty).where(
                    DailyRequirement.route_operation_id == stage.route_operation_id,
                    DailyRequirement.req_date == d,
                )
            )
            total += Decimal(str(qty or 0))
        d = date.fromordinal(d.toordinal() + 1)
    return total


def _stage_schedule_history(db: Session, product_id: int, month: date) -> list[dict]:
    stage_ids = _parent_dispatch_stage_ids(db, product_id)
    if not stage_ids:
        return []
    rows = db.execute(
        select(StageScheduleAllocation, ProcessFlowStage)
        .join(ProcessFlowStage, ProcessFlowStage.id == StageScheduleAllocation.stage_id)
        .where(
            StageScheduleAllocation.stage_id.in_(stage_ids),
            StageScheduleAllocation.month == month,
        )
        .order_by(StageScheduleAllocation.effective_from, StageScheduleAllocation.revision_no)
    ).all()
    return [
        {
            "id": alloc.id,
            "revision_no": alloc.revision_no,
            "effective_from": alloc.effective_from,
            "target": float(alloc.allocated_qty),
            "reason": alloc.reason,
            "created_at": alloc.created_at,
            "source": "Stage Schedule / Disp_Done",
            "reference": alloc.reference,
            "stage_code": stage.code,
            "stage_name": stage.name,
        }
        for alloc, stage in rows
    ]


def _preview_parent_dispatch(
    db: Session,
    product_id: int,
    effective_from: date,
    monthly_target_qty: Decimal,
    correct_imported_plans: bool = False,
) -> dict:
    stage = _parent_dispatch_stage(db, product_id, effective_from)
    if not stage or not stage.route_operation_id:
        raise HTTPException(409, "No active parent dispatch / Disp_Done stage is effective on this date")

    first, last = month_bounds(effective_from)
    issued_before = _issued_dispatch_plan_before(db, product_id, first, effective_from)
    balance = max(ZERO, Decimal(str(monthly_target_qty)) - issued_before)
    remaining_days = working_days(db, effective_from, last, product_plant(db, product_id))
    dist = split_integer_quantity(balance, remaining_days)
    existing = {
        r.req_date: r
        for r in db.scalars(
            select(DailyRequirement).where(
                DailyRequirement.route_operation_id == stage.route_operation_id,
                DailyRequirement.req_date >= effective_from,
                DailyRequirement.req_date <= last,
            )
        )
    }
    frozen = sum(bool(r.is_frozen) for r in existing.values())
    preview_rows = []
    d = effective_from
    while d <= last:
        row = existing.get(d)
        protected = bool(row and row.is_frozen and not correct_imported_plans)
        old = Decimal(str(row.revised_plan_qty)) if row else ZERO
        proposed = dist.get(d, ZERO)
        preview_rows.append(
            {
                "date": d.isoformat(),
                "qty": float(proposed),
                "current_qty": float(old),
                "result_qty": float(old if protected else proposed),
                "protected": protected,
            }
        )
        d = date.fromordinal(d.toordinal() + 1)

    current_rows = _stage_schedule_history(db, product_id, first)
    current = None
    for row in current_rows:
        if row["effective_from"] <= effective_from:
            current = row

    return {
        "month": first.isoformat(),
        "effective_from": effective_from.isoformat(),
        "current_target": current["target"] if current else None,
        "new_target": float(monthly_target_qty),
        "actual_before_effective_date": float(issued_before),
        "plan_before_effective_date": float(issued_before),
        "balance_requirement": float(balance),
        "remaining_working_days": len(remaining_days),
        "average_daily_requirement": float(balance / len(remaining_days)) if remaining_days else 0,
        "frozen_days": frozen,
        "protected_days": 0 if correct_imported_plans else frozen,
        "result_plan_qty": sum(r["result_qty"] for r in preview_rows),
        "preview": preview_rows,
        "source": "Stage Schedule / Disp_Done",
        "stage_code": stage.code,
        "stage_name": stage.name,
    }


def _apply_parent_dispatch_revision(
    db: Session,
    payload: ScheduleRevisionCreate,
    user: User,
) -> dict:
    month = payload.month.replace(day=1)
    stage = _parent_dispatch_stage(db, payload.product_id, payload.effective_from)
    if not stage or not stage.route_operation_id:
        raise HTTPException(409, "No active parent dispatch / Disp_Done stage is effective on this date")

    stage_ids = _parent_dispatch_stage_ids(db, payload.product_id)
    previous = []
    if stage_ids:
        previous = db.scalars(
            select(StageScheduleAllocation)
            .where(
                StageScheduleAllocation.stage_id.in_(stage_ids),
                StageScheduleAllocation.month == month,
            )
            .order_by(StageScheduleAllocation.effective_from.desc(), StageScheduleAllocation.revision_no.desc())
        ).all()
    if previous and payload.effective_from < previous[0].effective_from:
        raise HTTPException(400, "Schedule revisions must follow the latest effective date")

    first, last = month_bounds(month)
    issued_before = _issued_dispatch_plan_before(db, payload.product_id, first, payload.effective_from)
    target = Decimal(str(payload.monthly_target_qty))
    balance = target - issued_before
    if balance < 0:
        raise HTTPException(400, "New schedule is below the Disp_Done plan already issued before the effective date")

    days = working_days(db, payload.effective_from, last, product_plant(db, payload.product_id))
    if not days and balance:
        raise HTTPException(400, "No remaining working days in the Plant calendar")
    distribution = split_integer_quantity(balance, days)

    existing = {
        r.req_date: r
        for r in db.scalars(
            select(DailyRequirement).where(
                DailyRequirement.route_operation_id == stage.route_operation_id,
                DailyRequirement.req_date >= payload.effective_from,
                DailyRequirement.req_date <= last,
            )
        )
    }
    protected = [r for r in existing.values() if r.is_frozen]
    if protected and not payload.correct_imported_plans:
        raise HTTPException(409, "Imported plans are protected. Preview with 'Correct imported historical plans' selected to apply this schedule.")

    max_rev = max((x.revision_no for x in previous), default=0)
    reference = f"WEB-SCHEDULE-{payload.product_id}-{month:%Y%m}-{max_rev + 1:03d}-{datetime.utcnow():%Y%m%dT%H%M%SZ}"
    alloc = StageScheduleAllocation(
        stage_id=stage.id,
        month=month,
        effective_from=payload.effective_from,
        revision_no=max_rev + 1,
        allocated_qty=target,
        working_dates_json=__import__("json").dumps([d.isoformat() for d in days]),
        distribution_json=__import__("json").dumps({d.isoformat(): int(q) for d, q in distribution.items()}),
        reference=reference,
        reason=(payload.reason or "Customer schedule revision").strip(),
    )
    db.add(alloc)
    db.flush()

    applied = 0
    corrected = 0
    d = payload.effective_from
    while d <= last:
        row = existing.get(d)
        qty = distribution.get(d, ZERO)
        if row is None:
            db.add(
                DailyRequirement(
                    req_date=d,
                    product_id=payload.product_id,
                    route_operation_id=stage.route_operation_id,
                    baseline_plan_qty=ZERO,
                    revised_plan_qty=qty,
                    is_frozen=False,
                )
            )
            applied += 1
        elif not row.is_frozen or payload.correct_imported_plans:
            row.revised_plan_qty = qty
            corrected += int(bool(row.is_frozen))
            applied += 1
        d = date.fromordinal(d.toordinal() + 1)

    db.commit()
    db.refresh(alloc)
    return {
        "id": alloc.id,
        "revision_no": alloc.revision_no,
        "applied_days": applied,
        "corrected_imported_days": corrected,
        "protected_days": 0,
        "source": "Stage Schedule / Disp_Done",
        "reference": reference,
        "entered_by": user.username,
    }


@router.get("")
def list_schedules(product_id: int, month: date, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    first = month.replace(day=1)

    # Explicit Stage Schedule is now the authoritative customer schedule source.
    # The one stage marked parent_dispatch (normally Disp_Done) is the product's
    # monthly schedule shown on this page.
    stage_rows = _stage_schedule_history(db, product_id, first)
    if stage_rows:
        return stage_rows

    # Backward-compatible fallback for databases created before Stage Schedule.
    rows = db.scalars(
        select(ScheduleRevision)
        .where(
            ScheduleRevision.product_id == product_id,
            ScheduleRevision.month == first,
        )
        .order_by(ScheduleRevision.revision_no)
    ).all()
    return [
        {
            "id": x.id,
            "revision_no": x.revision_no,
            "effective_from": x.effective_from,
            "target": float(x.monthly_target_qty),
            "reason": x.reason,
            "created_at": x.created_at,
            "source": "Legacy schedule revision",
            "reference": None,
        }
        for x in rows
    ]


@router.post("/preview")
def preview(payload: SchedulePreviewRequest, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    if not db.get(Product, payload.product_id):
        raise HTTPException(404, "Product not found")
    if _parent_dispatch_stage(db, payload.product_id, payload.effective_from):
        return _preview_parent_dispatch(
            db,
            payload.product_id,
            payload.effective_from,
            payload.monthly_target_qty,
            payload.correct_imported_plans,
        )

    # Backward compatibility for products not yet migrated to explicit flows.
    from ..services.planning import preview_revision
    return preview_revision(
        db,
        payload.product_id,
        payload.effective_from,
        payload.monthly_target_qty,
        payload.correct_imported_plans,
    )


@router.post("")
def create_revision(payload: ScheduleRevisionCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    month = payload.month.replace(day=1)
    if payload.effective_from.replace(day=1) != month:
        raise HTTPException(400, "Effective date must be inside the selected month")
    if not db.get(Product, payload.product_id):
        raise HTTPException(404, "Product not found")
    if payload.correct_imported_plans and not (payload.reason or "").strip():
        raise HTTPException(422, "Historical schedule correction requires a reason")

    if _parent_dispatch_stage(db, payload.product_id, payload.effective_from):
        return _apply_parent_dispatch_revision(db, payload, user)

    # Backward compatibility for products not yet migrated to explicit flows.
    from ..services.planning import preview_revision
    impact = preview_revision(
        db,
        payload.product_id,
        payload.effective_from,
        payload.monthly_target_qty,
        payload.correct_imported_plans,
    )
    if impact["protected_days"]:
        raise HTTPException(409, "Imported daily plans are protected. Preview with 'Correct imported historical plans' selected to apply this schedule.")
    if payload.reason and payload.reason.strip():
        db.info["reason"] = payload.reason.strip()
    rev = ScheduleRevision(
        product_id=payload.product_id,
        month=month,
        revision_no=next_revision_no(db, payload.product_id, month),
        effective_from=payload.effective_from,
        monthly_target_qty=payload.monthly_target_qty,
        reason=payload.reason,
        entered_by_id=user.id,
    )
    db.add(rev)
    db.flush()
    result = apply_schedule_revision(db, rev, correct_imported_plans=payload.correct_imported_plans)
    db.commit()
    db.refresh(rev)
    return {"id": rev.id, "revision_no": rev.revision_no, **result, "source": "Legacy schedule revision"}


@router.post("/recalculate-month")
def recalculate_month(month: date, from_date: date, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    first, last = month_bounds(month)
    if from_date < first or from_date > last:
        raise HTTPException(400, "Recalculation date must be inside the selected month")

    count = 0
    # Recalculate explicit parent-dispatch schedules first.
    product_ids = db.scalars(
        select(ProcessFlowVersion.product_id)
        .join(ProcessFlowStage, ProcessFlowStage.flow_id == ProcessFlowVersion.id)
        .join(StageScheduleAllocation, StageScheduleAllocation.stage_id == ProcessFlowStage.id)
        .where(
            ProcessFlowStage.parent_dispatch.is_(True),
            StageScheduleAllocation.month == first,
        )
        .distinct()
    ).all()

    for product_id in product_ids:
        stage = _parent_dispatch_stage(db, product_id, from_date)
        if not stage or not stage.route_operation_id:
            continue
        stage_ids = _parent_dispatch_stage_ids(db, product_id)
        alloc = db.scalar(
            select(StageScheduleAllocation)
            .where(
                StageScheduleAllocation.stage_id.in_(stage_ids),
                StageScheduleAllocation.month == first,
                StageScheduleAllocation.effective_from <= from_date,
            )
            .order_by(StageScheduleAllocation.effective_from.desc(), StageScheduleAllocation.revision_no.desc())
            .limit(1)
        )
        if not alloc:
            continue
        issued_before = _issued_dispatch_plan_before(db, product_id, first, from_date)
        balance = max(ZERO, Decimal(str(alloc.allocated_qty)) - issued_before)
        days = working_days(db, from_date, last, product_plant(db, product_id))
        distribution = split_integer_quantity(balance, days)
        existing = {
            r.req_date: r
            for r in db.scalars(
                select(DailyRequirement).where(
                    DailyRequirement.route_operation_id == stage.route_operation_id,
                    DailyRequirement.req_date >= from_date,
                    DailyRequirement.req_date <= last,
                )
            )
        }
        d = from_date
        while d <= last:
            row = existing.get(d)
            qty = distribution.get(d, ZERO)
            if row is None:
                db.add(
                    DailyRequirement(
                        req_date=d,
                        product_id=product_id,
                        route_operation_id=stage.route_operation_id,
                        baseline_plan_qty=ZERO,
                        revised_plan_qty=qty,
                        is_frozen=False,
                    )
                )
            elif not row.is_frozen:
                row.revised_plan_qty = qty
            d = date.fromordinal(d.toordinal() + 1)
        count += 1

    # Legacy products remain supported.
    legacy_product_ids = db.scalars(
        select(ScheduleRevision.product_id).where(ScheduleRevision.month == first).distinct()
    ).all()
    for product_id in legacy_product_ids:
        if product_id in product_ids:
            continue
        rev = db.scalar(
            select(ScheduleRevision)
            .where(
                ScheduleRevision.product_id == product_id,
                ScheduleRevision.month == first,
                ScheduleRevision.effective_from <= from_date,
            )
            .order_by(ScheduleRevision.effective_from.desc(), ScheduleRevision.revision_no.desc())
            .limit(1)
        )
        if rev:
            apply_schedule_revision(db, rev, preserve_before=from_date)
            count += 1

    db.commit()
    return {"products_recalculated": count, "from_date": from_date, "source": "Disp_Done / Stage Schedule"}
