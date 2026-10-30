from ..time_utils import ist_today
from datetime import date
from decimal import Decimal
import uuid
from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..models import Product, RouteOperation, Operation, User, Vendor, VendorMovement, VendorReceipt, RouteVersion
from ..schemas import VendorMovementCreate

router = APIRouter(prefix="/vendor", tags=["vendor"])


def _serialize(vm: VendorMovement, product: Product, op: Operation, vendor: Vendor) -> dict:
    pending = float(vm.outward_qty - vm.receipt_qty)
    age = (ist_today() - vm.outward_date).days if pending > 0 else 0
    overdue = bool(pending > 0 and vm.expected_return_date and vm.expected_return_date < ist_today())
    return {
        "id": vm.id,
        "product_id": vm.product_id,
        "product": product.name,
        "route_operation_id": vm.route_operation_id,
        "operation": op.name,
        "vendor_id": vm.vendor_id,
        "vendor": vendor.name,
        "outward_date": vm.outward_date,
        "outward_qty": float(vm.outward_qty),
        "receipt_date": vm.receipt_date,
        "receipt_qty": float(vm.receipt_qty),
        "reject_qty": float(vm.reject_qty),
        "pending_qty": pending,
        "challan_no": vm.challan_no,
        "expected_return_date": vm.expected_return_date,
        "age_days": age,
        "overdue": overdue,
        "remarks": vm.remarks,
    }


@router.get("/movements")
def list_movements(product_id: int | None = None, pending_only: bool = False,
                   db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    q = (
        select(VendorMovement, Product, Operation, Vendor)
        .join(Product, Product.id == VendorMovement.product_id)
        .join(RouteOperation, RouteOperation.id == VendorMovement.route_operation_id)
        .join(Operation, Operation.id == RouteOperation.operation_id)
        .join(Vendor, Vendor.id == VendorMovement.vendor_id)
        .order_by(VendorMovement.outward_date.desc())
    )
    if product_id:
        q = q.where(VendorMovement.product_id == product_id)
    rows = [_serialize(*r) for r in db.execute(q).all()]
    if pending_only:
        rows = [r for r in rows if r["pending_qty"] > 0]
    return rows


@router.get("/performance")
def vendor_performance(as_of: date | None = None, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Read-only vendor scorecard derived from the outward/receipt ledger."""
    cutoff = as_of or ist_today()
    q = (
        select(VendorMovement, Product, Operation, Vendor)
        .join(Product, Product.id == VendorMovement.product_id)
        .join(RouteOperation, RouteOperation.id == VendorMovement.route_operation_id)
        .join(Operation, Operation.id == RouteOperation.operation_id)
        .join(Vendor, Vendor.id == VendorMovement.vendor_id)
        .order_by(Vendor.name, VendorMovement.outward_date)
    )
    movements = [_serialize(*row) for row in db.execute(q).all()]
    for row in movements:
        row["age_days"] = max(0, (cutoff - row["outward_date"]).days) if row["pending_qty"] > 0 else 0
        row["overdue"] = bool(row["pending_qty"] > 0 and row["expected_return_date"] and row["expected_return_date"] < cutoff)
    pending = [row for row in movements if row["pending_qty"] > 0]
    vendor_rows: dict[int, dict] = {}
    buckets = {"0-7 days": 0.0, "8-15 days": 0.0, "16-30 days": 0.0, "Over 30 days": 0.0}
    for row in pending:
        item = vendor_rows.setdefault(row["vendor_id"], {
            "vendor_id": row["vendor_id"], "vendor": row["vendor"],
            "open_lots": 0, "pending_qty": 0.0, "overdue_lots": 0,
            "overdue_qty": 0.0, "oldest_age_days": 0,
        })
        age = max(0, (cutoff - row["outward_date"]).days)
        item["open_lots"] += 1
        item["pending_qty"] += row["pending_qty"]
        item["oldest_age_days"] = max(item["oldest_age_days"], age)
        if row["expected_return_date"] and row["expected_return_date"] < cutoff:
            item["overdue_lots"] += 1
            item["overdue_qty"] += row["pending_qty"]
        bucket = "0-7 days" if age <= 7 else "8-15 days" if age <= 15 else "16-30 days" if age <= 30 else "Over 30 days"
        buckets[bucket] += row["pending_qty"]
    return {
        "as_of": cutoff,
        "summary": {
            "open_lots": len(pending),
            "pending_qty": sum(row["pending_qty"] for row in pending),
            "overdue_lots": sum(1 for row in pending if row["expected_return_date"] and row["expected_return_date"] < cutoff),
            "overdue_qty": sum(row["pending_qty"] for row in pending if row["expected_return_date"] and row["expected_return_date"] < cutoff),
            "vendors_with_pending": len(vendor_rows),
        },
        "aging_buckets": [{"bucket": key, "pending_qty": value} for key, value in buckets.items()],
        "vendors": sorted(vendor_rows.values(), key=lambda item: (-item["overdue_qty"], -item["pending_qty"], item["vendor"].casefold())),
        "movements": sorted(pending, key=lambda row: (row["expected_return_date"] or date.max, -row["age_days"])),
    }


@router.post("/movements")
def create_movement(payload: VendorMovementCreate, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    route = db.get(RouteOperation, payload.route_operation_id)
    version = db.get(RouteVersion, route.route_version_id) if route else None
    if not route or not version or version.product_id != payload.product_id or not db.get(Vendor,payload.vendor_id):
        raise HTTPException(422, 'Product, route operation and vendor must match valid masters')
    from ..models import ProcessFlowStage
    from ..services.process_flows import active_flow
    stage=db.scalar(select(ProcessFlowStage).where(ProcessFlowStage.route_operation_id==route.id))
    if stage:
        flow=active_flow(db,payload.product_id,payload.outward_date)
        if not flow or stage.flow_id!=flow.id or stage.role!='VENDOR_OUT' or not stage.is_active or route.vendor_id!=payload.vendor_id:
            raise HTTPException(422,'Use an active vendor outward stage and its assigned vendor')
    if payload.outward_qty <= 0 or payload.receipt_qty or payload.reject_qty or payload.receipt_date:
        raise HTTPException(422, 'Outward quantity must be positive; record receipts separately')
    if payload.expected_return_date and payload.expected_return_date < payload.outward_date:
        raise HTTPException(422, 'Expected return cannot precede outward date')
    row = VendorMovement(**payload.model_dump())
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id}



class ReceiptCreate(BaseModel):
    receipt_date: date
    receipt_qty: Decimal = Field(gt=0)
    reject_qty: Decimal = Field(default=Decimal('0'), ge=0)
    reference: str = Field(min_length=1, max_length=160)
    remarks: str | None = None


def append_receipt(movement_id, payload, db, user):
    row = db.scalar(select(VendorMovement).where(VendorMovement.id == movement_id).with_for_update())
    if not row:
        raise HTTPException(404, 'Vendor movement not found')
    previous = db.scalar(select(VendorReceipt).where(VendorReceipt.movement_id == movement_id, VendorReceipt.reference == payload.reference))
    if previous:
        if previous.receipt_qty != payload.receipt_qty or previous.reject_qty != payload.reject_qty or previous.receipt_date != payload.receipt_date:
            raise HTTPException(409, 'Receipt reference already exists with different values')
        return {'id': previous.id, 'status': 'already_received', 'pending_qty': float(row.outward_qty-row.receipt_qty)}
    if payload.receipt_date < row.outward_date:
        raise HTTPException(422, 'Receipt date cannot precede outward date')
    if payload.reject_qty > payload.receipt_qty:
        raise HTTPException(422, 'Reject quantity is included in received quantity and cannot exceed it')
    if payload.receipt_qty > row.outward_qty-row.receipt_qty:
        raise HTTPException(409, 'Receipt exceeds pending quantity')
    receipt = VendorReceipt(movement_id=row.id, **payload.model_dump(), entered_by_id=user.id)
    db.add(receipt)
    row.receipt_qty += payload.receipt_qty
    row.reject_qty += payload.reject_qty
    row.receipt_date = max(row.receipt_date or payload.receipt_date,payload.receipt_date)
    db.commit(); db.refresh(receipt)
    return {'id': receipt.id, 'pending_qty': float(row.outward_qty-row.receipt_qty)}

@router.post('/movements/{movement_id}/receipts')
def add_receipt(movement_id: int, payload: ReceiptCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return append_receipt(movement_id,payload,db,user)

@router.get('/movements/{movement_id}/receipts')
def receipts(movement_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.scalars(select(VendorReceipt).where(VendorReceipt.movement_id==movement_id).order_by(VendorReceipt.receipt_date,VendorReceipt.id)).all()

@router.patch('/movements/{movement_id}/receipt')
def receive(movement_id: int, receipt_date: date, receipt_qty: float, reject_qty: float = 0,
            remarks: str | None = None, reference: str | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return append_receipt(movement_id, ReceiptCreate(receipt_date=receipt_date, receipt_qty=Decimal(str(receipt_qty)), reject_qty=Decimal(str(reject_qty)), reference=reference or uuid.uuid4().hex, remarks=remarks), db, user)
