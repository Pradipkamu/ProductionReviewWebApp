from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user, hash_password
from ..db import get_db
from ..enums import OEEComponent, OperationType, UserRole
from ..models import (
    Customer, LossCategory, Machine, Operation, Product, RouteOperation,
    RouteVersion, SalesPriceHistory, User, Vendor, WorkingCalendar, WorkingCalendarChangeLog,
    OperationMachineMap, StandardCycleTime, DailyMIS,
)
from ..schemas import (MasterCreate, RouteVersionCreate, MachineMapCreate, CycleTimeCreate, CalendarUpsert,
                       CalendarBulkUpdate, UserCreate, ProductMasterUpdate, SalesPriceRevisionCreate)
from ..services.pricing import create_or_replace_manual_price, price_for_date

router = APIRouter(prefix="/masters", tags=["masters"])


@router.get("/customers")
def customers(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return [{"id": x.id, "code": x.code, "name": x.name} for x in db.scalars(select(Customer).order_by(Customer.name)).all()]


@router.get("/products")
def products(
    plant: str | None = None,
    product_group: str | None = None,
    customer_id: int | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = select(Product, Customer).outerjoin(Customer, Customer.id == Product.customer_id)
    if plant:
        q = q.where(Product.plant == plant)
    if product_group:
        q = q.where(Product.product_group == product_group)
    if customer_id is not None:
        q = q.where(Product.customer_id == customer_id)
    rows = db.execute(q.order_by(Product.sort_order, Product.name)).all()
    return [{
        "id": p.id, "code": p.code, "name": p.name, "customer": c.name if c else None,
        "customer_id": p.customer_id, "actual_measure": p.actual_measure,
        "plant": p.plant, "product_group": p.product_group,
        "finish_weight_kg": float(p.finish_weight_kg) if p.finish_weight_kg is not None else None,
    } for p, c in rows]


@router.get("/filter-options")
def filter_options(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    plants = [x for x in db.scalars(
        select(Product.plant).where(Product.plant.is_not(None), Product.plant != "").distinct().order_by(Product.plant)
    ).all() if x]
    groups = [x for x in db.scalars(
        select(Product.product_group).where(Product.product_group.is_not(None), Product.product_group != "").distinct().order_by(Product.product_group)
    ).all() if x]
    customers = [{"id": x.id, "code": x.code, "name": x.name} for x in db.scalars(select(Customer).order_by(Customer.name)).all()]
    return {"plants": plants, "product_groups": groups, "customers": customers}


@router.patch("/products/{product_id}")
def update_product_master(product_id: int, payload: ProductMasterUpdate, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    row = db.get(Product, product_id)
    if not row:
        raise HTTPException(404, "Product not found")
    row.plant = payload.plant.strip() if payload.plant else None
    row.product_group = payload.product_group.strip() if payload.product_group else None
    row.finish_weight_kg = payload.finish_weight_kg
    db.commit(); db.refresh(row)
    return {
        "id": row.id, "name": row.name, "plant": row.plant,
        "product_group": row.product_group,
        "finish_weight_kg": float(row.finish_weight_kg) if row.finish_weight_kg is not None else None,
    }


@router.get("/operations")
def operations(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return [{"id": x.id, "code": x.code, "name": x.name, "type": x.operation_type.value} for x in db.scalars(select(Operation).order_by(Operation.name)).all()]


@router.get("/vendors")
def vendors(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return [{"id": x.id, "code": x.code, "name": x.name} for x in db.scalars(select(Vendor).order_by(Vendor.name)).all()]


@router.get("/machines")
def machines(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return [{"id": x.id, "code": x.code, "name": x.name, "department": x.department, "active": x.is_active} for x in db.scalars(select(Machine).order_by(Machine.code)).all()]


@router.post("/machines")
def create_machine(payload: MasterCreate, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    if db.scalar(select(Machine).where(Machine.code == payload.code)):
        raise HTTPException(409, "Machine code already exists")
    row = Machine(code=payload.code, name=payload.name)
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id, "code": row.code, "name": row.name}


@router.get("/loss-categories")
def losses(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return [{"id": x.id, "code": x.code, "name": x.name, "component": x.oee_component.value} for x in db.scalars(select(LossCategory).order_by(LossCategory.name)).all()]


@router.post("/loss-categories")
def create_loss(code: str, name: str, component: OEEComponent, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    row = LossCategory(code=code, name=name, oee_component=component)
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id}


@router.get("/users")
def users(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return [{"id": x.id, "username": x.username, "full_name": x.full_name, "role": x.role.value, "is_active": x.is_active, "must_change_password": x.must_change_password} for x in db.scalars(select(User).order_by(User.full_name)).all()]


@router.post("/users")
def create_user(payload: UserCreate, db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    if current.role != UserRole.ADMIN:
        raise HTTPException(403, "Only ADMIN can create users")
    if db.scalar(select(User).where(User.username == payload.username)):
        raise HTTPException(409, "Username already exists")
    try:
        role = UserRole(payload.role)
    except Exception:
        raise HTTPException(400, "Invalid role")
    from ..security_policy import validate_password
    validate_password(payload.password)
    row = User(username=payload.username, full_name=payload.full_name, password_hash=hash_password(payload.password), role=role, is_active=True)
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id, "username": row.username, "full_name": row.full_name, "role": row.role.value}


@router.get("/routes/{product_id}")
def routes(product_id: int, on_date: date | None = None, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    q = select(RouteVersion).where(RouteVersion.product_id == product_id).order_by(RouteVersion.revision_no.desc())
    versions = db.scalars(q).all()
    out = []
    for rv in versions:
        ops = db.execute(
            select(RouteOperation, Operation, Vendor)
            .join(Operation, Operation.id == RouteOperation.operation_id)
            .outerjoin(Vendor, Vendor.id == RouteOperation.vendor_id)
            .where(RouteOperation.route_version_id == rv.id)
            .order_by(RouteOperation.sequence_no)
        ).all()
        out.append({
            "id": rv.id, "revision_no": rv.revision_no, "effective_from": rv.effective_from,
            "effective_to": rv.effective_to, "description": rv.description,
            "operations": [{
                "route_operation_id": ro.id, "sequence_no": ro.sequence_no, "operation_id": op.id,
                "operation": op.name, "type": op.operation_type.value,
                "vendor": vendor.name if vendor else None, "yield": float(ro.standard_yield),
                "lead_time_days": ro.standard_lead_time_days, "is_dispatch": ro.is_dispatch,
            } for ro, op, vendor in ops],
        })
    return out


@router.get("/prices/{product_id}")
def price_history(product_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    if not db.get(Product, product_id):
        raise HTTPException(404, "Product not found")
    rows = db.scalars(select(SalesPriceHistory).where(
        SalesPriceHistory.product_id == product_id
    ).order_by(SalesPriceHistory.effective_from.desc(), SalesPriceHistory.id.desc())).all()
    return [{
        "id": x.id, "effective_from": x.effective_from, "effective_to": x.effective_to,
        "price": float(x.price), "reason": x.reason, "revision_reference": x.revision_reference,
        "source_document": x.source_document, "source": x.source,
        "entered_by_id": x.entered_by_id, "created_at": x.created_at,
    } for x in rows]


@router.get("/prices/{product_id}/on-date")
def price_on_date(product_id: int, on_date: date, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    if not db.get(Product, product_id):
        raise HTTPException(404, "Product not found")
    return {"product_id": product_id, "date": on_date, "price": float(price_for_date(db, product_id, on_date))}


@router.post("/prices")
def create_price_revision(payload: SalesPriceRevisionCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not db.get(Product, payload.product_id):
        raise HTTPException(404, "Product not found")
    if payload.reason:
        db.info['reason'] = payload.reason
    row = create_or_replace_manual_price(
        db, payload.product_id, payload.effective_from, Decimal(str(payload.price)), payload.reason, user.id
    )
    db.commit(); db.refresh(row)
    return {"id": row.id, "product_id": row.product_id, "effective_from": row.effective_from,
            "effective_to": row.effective_to, "price": float(row.price), "reason": row.reason, "source": row.source}


@router.get("/calendar")
def calendar_rows(month: date, plant: str = "Main Plant", db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    first = month.replace(day=1)
    import calendar as cal
    last = date(first.year, first.month, cal.monthrange(first.year, first.month)[1])
    explicit = {x.work_date: x for x in db.scalars(select(WorkingCalendar).where(
        WorkingCalendar.work_date >= first,
        WorkingCalendar.work_date <= last,
        WorkingCalendar.plant == plant,
    )).all()}
    out=[]
    d=first
    while d <= last:
        x=explicit.get(d)
        if x:
            out.append({"date": d, "plant": plant, "working": x.is_working_day, "holiday": x.holiday_name,
                        "reason": x.reason, "explicit": True})
        else:
            out.append({"date": d, "plant": plant, "working": d.weekday()!=6, "holiday": None,
                        "reason": "Default Mon-Sat working / Sunday off", "explicit": False})
        d += timedelta(days=1)
    return out


def _write_calendar_day(db: Session, payload: CalendarUpsert, user_id: int | None):
    row = db.scalar(select(WorkingCalendar).where(
        WorkingCalendar.work_date == payload.work_date,
        WorkingCalendar.plant == payload.plant,
    ))
    old_working = row.is_working_day if row else None
    old_holiday = row.holiday_name if row else None
    old_reason = row.reason if row else None
    if not row:
        row = WorkingCalendar(work_date=payload.work_date, plant=payload.plant)
        db.add(row)
    row.is_working_day = payload.is_working_day
    row.holiday_name = payload.holiday_name.strip() if payload.holiday_name else None
    row.reason = payload.reason.strip() if payload.reason else None
    if old_working != row.is_working_day or old_holiday != row.holiday_name or old_reason != row.reason:
        db.add(WorkingCalendarChangeLog(
            work_date=payload.work_date, plant=payload.plant,
            old_is_working_day=old_working, new_is_working_day=row.is_working_day,
            old_holiday_name=old_holiday, new_holiday_name=row.holiday_name,
            old_reason=old_reason, new_reason=row.reason, changed_by_id=user_id,
        ))
    return row


@router.post("/calendar")
def upsert_calendar(payload: CalendarUpsert, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = _write_calendar_day(db, payload, user.id)
    db.commit(); db.refresh(row)
    return {"id": row.id, "date": row.work_date, "working": row.is_working_day}


@router.post("/calendar/bulk")
def bulk_calendar(payload: CalendarBulkUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if payload.end_date < payload.start_date:
        raise HTTPException(400, "End date must be on or after start date")
    changed = 0
    d = payload.start_date
    while d <= payload.end_date:
        apply = payload.mode != "SUNDAYS_OFF" or d.weekday() == 6
        if apply:
            working = payload.mode == "SET_WORKING"
            holiday = None if working else (payload.holiday_name or ("Sunday" if payload.mode == "SUNDAYS_OFF" else "Off day"))
            _write_calendar_day(db, CalendarUpsert(
                work_date=d, plant=payload.plant, is_working_day=working,
                holiday_name=holiday, reason=payload.reason,
            ), user.id)
            changed += 1
        d += timedelta(days=1)
    db.commit()
    return {"plant": payload.plant, "mode": payload.mode, "days_processed": changed}


@router.get("/calendar/history")
def calendar_history(month: date, plant: str = "Main Plant", db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    import calendar as cal
    first = month.replace(day=1)
    last = date(first.year, first.month, cal.monthrange(first.year, first.month)[1])
    rows = db.scalars(select(WorkingCalendarChangeLog).where(
        WorkingCalendarChangeLog.work_date >= first,
        WorkingCalendarChangeLog.work_date <= last,
        WorkingCalendarChangeLog.plant == plant,
    ).order_by(WorkingCalendarChangeLog.changed_at.desc()).limit(100)).all()
    return [{
        "id": x.id, "date": x.work_date, "plant": x.plant,
        "old_working": x.old_is_working_day, "new_working": x.new_is_working_day,
        "old_holiday": x.old_holiday_name, "new_holiday": x.new_holiday_name,
        "old_reason": x.old_reason, "new_reason": x.new_reason,
        "changed_by_id": x.changed_by_id, "changed_at": x.changed_at,
    } for x in rows]


@router.post("/routes/{product_id}")
def create_route_version(product_id: int, payload: RouteVersionCreate, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    from ..models import ProcessFlowVersion
    if db.scalar(select(ProcessFlowVersion.id).where(ProcessFlowVersion.product_id==product_id).limit(1)):
        raise HTTPException(409,'This product uses explicit process flows. Import a new Flow Definition revision.')
    if not db.get(Product, product_id):
        raise HTTPException(404, "Product not found")
    max_rev = db.scalar(select(RouteVersion.revision_no).where(RouteVersion.product_id == product_id).order_by(RouteVersion.revision_no.desc()).limit(1))
    revision_no = (max_rev if max_rev is not None else -1) + 1
    previous = db.scalar(select(RouteVersion).where(
        RouteVersion.product_id == product_id,
        RouteVersion.effective_from < payload.effective_from,
        RouteVersion.is_active.is_(True),
    ).order_by(RouteVersion.effective_from.desc()).limit(1))
    if previous and (previous.effective_to is None or previous.effective_to >= payload.effective_from):
        previous.effective_to = payload.effective_from - timedelta(days=1)
    route = RouteVersion(product_id=product_id, revision_no=revision_no, effective_from=payload.effective_from, description=payload.description)
    db.add(route); db.flush()
    for item in sorted(payload.operations, key=lambda x: x.sequence_no):
        db.add(RouteOperation(route_version_id=route.id, **item.model_dump()))
    db.commit(); db.refresh(route)
    return {"id": route.id, "revision_no": route.revision_no}


@router.post("/machine-maps")
def add_machine_map(payload: MachineMapCreate, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    row = OperationMachineMap(**payload.model_dump())
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id}


@router.post("/cycle-times")
def add_cycle_time(payload: CycleTimeCreate, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    row = StandardCycleTime(**payload.model_dump())
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id}

